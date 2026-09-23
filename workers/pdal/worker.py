from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from common.runtime import DATA_ROOT, consume, run_process, update_job

ENGINE = "pdal-processing"
PROCESSING_TIMEOUT_SECONDS = max(
    60,
    int(os.getenv("GEOPHOTO_PDAL_PROCESSING_TIMEOUT_SECONDS", "3600")),
)
INFO_TIMEOUT_SECONDS = max(
    10,
    int(os.getenv("GEOPHOTO_PDAL_TIMEOUT_SECONDS", "120")),
)


def _relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Processing artifact path must be a non-empty relative path.")
    raw = value.replace("\\", "/").strip()
    if raw.startswith("/"):
        raise ValueError("Processing artifact path must be relative.")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Processing artifact path contains unsafe components.")
    return path


def _data_path(relative: PurePosixPath) -> Path:
    root = DATA_ROOT.resolve()
    path = (root / Path(*relative.parts)).resolve()
    if path != root and root not in path.parents:
        raise ValueError("Processing artifact path leaves the data root.")
    return path


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _pdal_summary(path: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["pdal", "info", "--summary", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=INFO_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"PDAL summary exceeded {INFO_TIMEOUT_SECONDS} seconds."
        ) from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            detail[-2000:] or f"pdal info failed with code {proc.returncode}."
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("pdal info returned invalid JSON.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("summary"), dict):
        raise RuntimeError("pdal info returned no summary object.")
    return payload


def _summary_qa(payload: Mapping[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        raise ValueError("PDAL summary is missing.")

    try:
        point_count = int(summary.get("num_points"))
    except (TypeError, ValueError) as exc:
        raise ValueError("PDAL summary has no valid point count.") from exc
    if point_count < 0:
        raise ValueError("PDAL summary has a negative point count.")

    bounds = summary.get("bounds")
    if not isinstance(bounds, Mapping):
        raise ValueError("PDAL summary has no bounds.")
    keys = ("minx", "miny", "minz", "maxx", "maxy", "maxz")
    values: dict[str, float] = {}
    for key in keys:
        try:
            value = float(bounds[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"PDAL summary has invalid bound {key}.") from exc
        if not math.isfinite(value):
            raise ValueError(f"PDAL summary bound {key} is not finite.")
        values[key] = value
    if values["minx"] > values["maxx"] or values["miny"] > values["maxy"]:
        raise ValueError("PDAL summary has inverted horizontal bounds.")

    return {
        "point_count": point_count,
        "bounds": values,
        "srs": summary.get("srs"),
    }


def _validate_contract(
    job_id: str,
    options: Mapping[str, Any],
) -> tuple[dict[str, Any], PurePosixPath, PurePosixPath]:
    contract = options.get("contract")
    if not isinstance(contract, dict):
        raise ValueError("Processing job has no reprojection contract.")
    if contract.get("operation") != "horizontal_reprojection":
        raise ValueError("Unsupported point-cloud processing operation.")

    source = contract.get("source")
    output = contract.get("output")
    pipeline = contract.get("pipeline")
    if not isinstance(source, Mapping) or not isinstance(output, Mapping):
        raise ValueError("Reprojection contract is missing source/output.")
    if not isinstance(pipeline, Mapping):
        raise ValueError("Reprojection contract is missing pipeline.")

    source_relative = _relative_path(source.get("relative_path"))
    output_relative = _relative_path(output.get("relative_path"))
    expected_output = PurePosixPath("jobs") / job_id / "derived" / "reprojected.laz"
    if output_relative != expected_output:
        raise ValueError("Reprojection output must belong to its processing job.")

    stages = pipeline.get("pipeline")
    if not isinstance(stages, list) or len(stages) != 3:
        raise ValueError("Reprojection pipeline must contain exactly three stages.")
    reader, reprojection, writer = stages
    if not all(isinstance(stage, Mapping) for stage in stages):
        raise ValueError("Reprojection pipeline contains an invalid stage.")
    if reader.get("type") not in {"readers.las", "readers.copc"}:
        raise ValueError("Reprojection pipeline has an unsupported reader.")
    if reprojection.get("type") != "filters.reprojection":
        raise ValueError("Reprojection pipeline is missing filters.reprojection.")
    if writer.get("type") != "writers.las":
        raise ValueError("Reprojection pipeline has an unsupported writer.")

    expected_source = str(PurePosixPath("/data") / source_relative)
    expected_output_abs = str(PurePosixPath("/data") / output_relative)
    if reader.get("filename") != expected_source:
        raise ValueError("Reprojection reader path does not match source artifact.")
    if writer.get("filename") != expected_output_abs:
        raise ValueError("Reprojection writer path does not match output artifact.")
    if writer.get("compression") is not True:
        raise ValueError("Reprojection output must be compressed LAZ.")
    if writer.get("forward") != "header,vlr":
        raise ValueError("Reprojection writer forward contract changed unexpectedly.")
    if writer.get("a_srs") != output.get("crs"):
        raise ValueError("Reprojection writer CRS does not match output contract.")

    return contract, source_relative, output_relative


def _target_srs_evidence(post: Mapping[str, Any], target_crs: str) -> bool:
    srs = post.get("srs")
    if not isinstance(srs, (Mapping, str)):
        return False
    text = json.dumps(srs, ensure_ascii=False) if isinstance(srs, Mapping) else srs
    authority, sep, code = target_crs.partition(":")
    if sep and authority.upper() == "EPSG" and code.isdigit():
        return code in text
    return target_crs in text


def handle(payload: dict) -> None:
    job_id = str(payload["job_id"])
    options = payload.get("options")
    if not isinstance(options, Mapping):
        raise ValueError("Pointcloud processing options are missing.")

    contract, source_relative, output_relative = _validate_contract(job_id, options)
    source_path = _data_path(source_relative)
    output_path = _data_path(output_relative)
    if not source_path.is_file():
        raise FileNotFoundError(f"Source point cloud not found: {source_relative}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    job_root = DATA_ROOT / "jobs" / job_id
    job_root.mkdir(parents=True, exist_ok=True)
    pipeline_path = job_root / "reprojection-pipeline.json"
    provenance_path = job_root / "reprojection-provenance.json"
    log_path = job_root / "worker.log"

    output_path.unlink(missing_ok=True)
    provenance_path.unlink(missing_ok=True)
    _atomic_json(pipeline_path, contract["pipeline"])

    update_job(
        job_id,
        status="running",
        progress=5,
        phase="source_qa",
        message="Source-Punktwolke und Reprojection-Vertrag werden geprüft.",
    )
    source_summary_raw = _pdal_summary(source_path)
    source_qa = _summary_qa(source_summary_raw)
    source_sha256 = _sha256(source_path)

    update_job(
        job_id,
        progress=20,
        phase="reprojection",
        message="PDAL reprojiziert die Punktwolke in ein neues LAZ-Artefakt.",
    )
    code = run_process(
        job_id,
        [
            "timeout",
            "--signal=TERM",
            "--kill-after=10s",
            str(PROCESSING_TIMEOUT_SECONDS),
            "pdal",
            "pipeline",
            str(pipeline_path),
        ],
        cwd=job_root,
        log_path=log_path,
    )
    if code == 130:
        output_path.unlink(missing_ok=True)
        return
    if code == 124:
        output_path.unlink(missing_ok=True)
        raise TimeoutError(
            f"PDAL reprojection exceeded {PROCESSING_TIMEOUT_SECONDS} seconds."
        )
    if code != 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"PDAL reprojection failed with code {code}.")
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("PDAL reprojection produced no output artifact.")

    try:
        update_job(
            job_id,
            progress=85,
            phase="result_qa",
            message="Reprojection-Ergebnis wird gegen Source und Ziel-CRS geprüft.",
        )
        output_summary_raw = _pdal_summary(output_path)
        output_qa = _summary_qa(output_summary_raw)
        if output_qa["point_count"] != source_qa["point_count"]:
            raise RuntimeError(
                "Reprojection changed point count "
                f"({source_qa['point_count']} -> {output_qa['point_count']})."
            )

        target_crs = str(contract["output"]["crs"])
        if not _target_srs_evidence(output_qa, target_crs):
            raise RuntimeError(
                f"Output SRS does not provide evidence for target CRS {target_crs}."
            )

        output_sha256 = _sha256(output_path)
        base_provenance = options.get("provenance")
        provenance = (
            json.loads(json.dumps(base_provenance))
            if isinstance(base_provenance, Mapping)
            else {}
        )
        provenance.update(
            {
                "source_sha256": source_sha256,
                "output_sha256": output_sha256,
                "pdal_processing_timeout_seconds": PROCESSING_TIMEOUT_SECONDS,
                "qa": {
                    "source": source_qa,
                    "output": output_qa,
                    "point_count_preserved": True,
                    "target_srs_verified": True,
                },
            }
        )
        _atomic_json(provenance_path, provenance)

        artifacts = [
            {
                "type": "point_cloud_laz",
                "name": output_path.name,
                "relative_path": output_relative.as_posix(),
                "size_bytes": output_path.stat().st_size,
                "sha256": output_sha256,
                "derived_from": {
                    "job_id": provenance.get("source_job_id"),
                    "artifact_index": provenance.get("source_artifact_index"),
                },
                "crs": target_crs,
            },
            {
                "type": "pointcloud_reprojection_pipeline",
                "name": pipeline_path.name,
                "relative_path": (
                    PurePosixPath("jobs") / job_id / pipeline_path.name
                ).as_posix(),
                "size_bytes": pipeline_path.stat().st_size,
                "sha256": _sha256(pipeline_path),
            },
            {
                "type": "pointcloud_reprojection_provenance",
                "name": provenance_path.name,
                "relative_path": (
                    PurePosixPath("jobs") / job_id / provenance_path.name
                ).as_posix(),
                "size_bytes": provenance_path.stat().st_size,
                "sha256": _sha256(provenance_path),
            },
        ]
    except Exception:
        output_path.unlink(missing_ok=True)
        provenance_path.unlink(missing_ok=True)
        raise

    update_job(
        job_id,
        status="completed",
        progress=100,
        phase="completed",
        message="PDAL-Reprojection abgeschlossen und Ergebnis-QA bestanden.",
        artifacts=artifacts,
    )


if __name__ == "__main__":
    consume(ENGINE, handle)
