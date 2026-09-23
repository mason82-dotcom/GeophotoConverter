from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from pyproj import CRS
from pyproj.exceptions import CRSError

from app.pointcloud_processing import (
    build_reprojection_pipeline,
    reprojection_provenance,
)
from common.runtime import (
    ARTIFACT_JOB_BACKEND,
    DATA_ROOT,
    DB_PATH,
    consume,
    run_process,
)

PROCESSOR = "pdal"
PDAL_TIMEOUT_SECONDS = max(
    10,
    int(os.getenv("GEOPHOTO_PDAL_TIMEOUT_SECONDS", "120")),
)


def _json_object(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_relative(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Artifact path must be a non-empty relative path.")
    raw = value.replace("\\", "/").strip()
    if raw.startswith("/"):
        raise ValueError("Artifact path must be relative.")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Artifact path contains unsafe path components.")
    return path


def _resolve_data_path(value: Any) -> Path:
    relative = _safe_relative(value)
    target = (DATA_ROOT / Path(*relative.parts)).resolve()
    root = DATA_ROOT.resolve()
    if target != root and root not in target.parents:
        raise ValueError("Artifact path escapes the data root.")
    return target


def _owned_output_path(artifact_job_id: str, value: Any) -> Path:
    target = _resolve_data_path(value)
    owner = (DATA_ROOT / "artifact-jobs" / artifact_job_id).resolve()
    if target != owner and owner not in target.parents:
        raise ValueError("Derived output must stay inside its artifact-job root.")
    if target.suffix.lower() != ".laz":
        raise ValueError("Derived reprojection output must be LAZ.")
    return target


def _source_artifact(
    source_job_id: str,
    source_artifact_index: int,
) -> dict[str, Any]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT artifacts_json FROM jobs WHERE id=?",
            (source_job_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Source job no longer exists.")

    raw = row["artifacts_json"]
    try:
        artifacts = json.loads(raw) if raw else []
    except json.JSONDecodeError as exc:
        raise ValueError("Source job contains invalid artifact metadata.") from exc
    if not isinstance(artifacts, list):
        raise ValueError("Source job artifact metadata is invalid.")
    if source_artifact_index < 0 or source_artifact_index >= len(artifacts):
        raise ValueError("Source artifact index is no longer valid.")

    artifact = artifacts[source_artifact_index]
    if not isinstance(artifact, dict):
        raise ValueError("Source artifact metadata is invalid.")
    return artifact


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.part")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _pdal_summary(path: Path) -> dict[str, Any]:
    process = subprocess.run(
        ["pdal", "info", "--summary", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=PDAL_TIMEOUT_SECONDS,
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()
        raise RuntimeError(
            f"PDAL summary failed for {path.name}: "
            f"{detail[-2000:] or process.returncode}"
        )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PDAL summary returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("PDAL summary returned no JSON object.")
    return payload


def _summary_root(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    summary = payload.get("summary")
    return summary if isinstance(summary, Mapping) else {}


def _point_count(payload: Mapping[str, Any]) -> int:
    value = _summary_root(payload).get("num_points")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("PDAL summary contains no valid point count.") from exc
    if count <= 0:
        raise RuntimeError("Point cloud is empty after processing.")
    return count


def _summary_crs(payload: Mapping[str, Any]) -> CRS:
    raw = _summary_root(payload).get("srs")
    candidate: Any = raw
    if isinstance(raw, Mapping):
        candidate = (
            raw.get("compoundwkt")
            or raw.get("wkt")
            or raw.get("horizontal")
            or raw.get("proj4")
        )
    if not candidate:
        raise RuntimeError("PDAL output summary contains no CRS.")
    try:
        return CRS.from_user_input(candidate)
    except (CRSError, ValueError, TypeError) as exc:
        raise RuntimeError("PDAL output CRS could not be parsed.") from exc


def _relative_to_data(path: Path) -> str:
    return path.resolve().relative_to(DATA_ROOT.resolve()).as_posix()


def handle(payload: dict[str, Any]) -> None:
    artifact_job_id = str(
        payload.get("artifact_job_id")
        or payload.get("job_id")
        or ""
    )
    if not artifact_job_id:
        raise ValueError("Artifact job ID is missing.")

    row = ARTIFACT_JOB_BACKEND.get(artifact_job_id)
    if not row:
        raise ValueError("Artifact job no longer exists.")
    if row["processor"] != PROCESSOR or row["operation"] != "reproject":
        raise ValueError("Unsupported artifact processing operation.")

    options = _json_object(row.get("options_json"))
    source_job_id = str(row["source_job_id"])
    source_index = int(row["source_artifact_index"])
    artifact = _source_artifact(source_job_id, source_index)

    expected_source_relative = str(options.get("source_relative_path") or "")
    actual_source_relative = str(artifact.get("relative_path") or "")
    if not actual_source_relative or actual_source_relative != expected_source_relative:
        raise ValueError("Source artifact changed after the job was prepared.")

    source_path = _resolve_data_path(actual_source_relative)
    if not source_path.is_file():
        raise ValueError("Source point cloud no longer exists.")
    if source_path.suffix.lower() not in {".las", ".laz"}:
        raise ValueError("Reprojection source must be LAS/LAZ/COPC-LAZ.")

    final_path = _owned_output_path(
        artifact_job_id,
        options.get("output_relative_path"),
    )
    source_crs = options.get("source_crs")
    target_crs = options.get("target_crs")
    if not source_crs or not target_crs:
        raise ValueError("Stored reprojection CRS contract is incomplete.")

    contract = build_reprojection_pipeline(
        source_path,
        final_path,
        source_crs=source_crs,
        target_crs=target_crs,
    )

    job_root = DATA_ROOT / "artifact-jobs" / artifact_job_id
    work_dir = job_root / "work"
    derived_dir = job_root / "derived"
    work_dir.mkdir(parents=True, exist_ok=True)
    derived_dir.mkdir(parents=True, exist_ok=True)
    log_path = ARTIFACT_JOB_BACKEND.log_path(artifact_job_id)
    temp_output = work_dir / "reprojecting.laz"

    # Crash recovery is idempotent within this artifact job only.
    temp_output.unlink(missing_ok=True)
    final_path.unlink(missing_ok=True)

    source_sha = _sha256(source_path)
    expected_sha = artifact.get("sha256")
    if expected_sha and str(expected_sha).lower() != source_sha.lower():
        raise ValueError("Source point cloud checksum changed after creation.")

    ARTIFACT_JOB_BACKEND.update(
        artifact_job_id,
        status="running",
        progress=5,
        phase="preflight_qa",
        message="Source-Punktwolke und Reprojection-Vertrag werden geprüft.",
    )
    before = _pdal_summary(source_path)
    before_count = _point_count(before)

    canonical_pipeline = contract["pipeline"]
    execution_pipeline = copy.deepcopy(canonical_pipeline)
    stages = execution_pipeline.get("pipeline")
    if not isinstance(stages, list) or not stages:
        raise RuntimeError("Reprojection contract contains no PDAL stages.")
    writer = stages[-1]
    if not isinstance(writer, dict) or writer.get("type") != "writers.las":
        raise RuntimeError("Reprojection contract has no LAS writer.")
    writer["filename"] = str(temp_output)

    contract_path = job_root / "pipeline-contract.json"
    execution_path = work_dir / "pipeline-execution.json"
    _atomic_json(contract_path, canonical_pipeline)
    _atomic_json(execution_path, execution_pipeline)

    ARTIFACT_JOB_BACKEND.update(
        artifact_job_id,
        progress=20,
        phase="reprojecting",
        message="PDAL reprojiziert die Punktwolke horizontal.",
    )
    code = run_process(
        artifact_job_id,
        ["pdal", "pipeline", str(execution_path)],
        cwd=job_root,
        log_path=log_path,
        backend=ARTIFACT_JOB_BACKEND,
    )
    if code == 130:
        temp_output.unlink(missing_ok=True)
        return
    if code != 0:
        temp_output.unlink(missing_ok=True)
        raise RuntimeError(f"PDAL pipeline exited with code {code}.")
    if not temp_output.is_file():
        raise RuntimeError("PDAL produced no reprojection output.")

    ARTIFACT_JOB_BACKEND.update(
        artifact_job_id,
        progress=82,
        phase="postflight_qa",
        message="Reprojizierte Punktwolke wird fachlich geprüft.",
    )
    after = _pdal_summary(temp_output)
    after_count = _point_count(after)
    if before_count != after_count:
        raise RuntimeError(
            "Pure reprojection changed the point count "
            f"({before_count} -> {after_count})."
        )

    expected_target = CRS.from_user_input(contract["target"]["crs"])
    actual_target = _summary_crs(after)
    if not actual_target.equals(expected_target):
        raise RuntimeError(
            "Reprojected point cloud CRS does not match the requested target."
        )

    ARTIFACT_JOB_BACKEND.update(
        artifact_job_id,
        progress=94,
        phase="finalizing",
        message="QA bestanden; abgeleitetes LAZ wird atomisch finalisiert.",
    )
    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temp_output, final_path)
    output_sha = _sha256(final_path)

    qa = {
        "schema_version": 1,
        "operation": "reproject",
        "point_count_before": before_count,
        "point_count_after": after_count,
        "point_count_equal": True,
        "target_crs_verified": True,
        "source_summary": before,
        "output_summary": after,
    }
    qa_path = job_root / "qa.json"
    _atomic_json(qa_path, qa)

    provenance = reprojection_provenance(
        contract,
        source_job_id=source_job_id,
        source_artifact_index=source_index,
        source_sha256=source_sha,
    )
    provenance.update(
        {
            "artifact_job_id": artifact_job_id,
            "output_sha256": output_sha,
            "output_relative_path": _relative_to_data(final_path),
            "executed_pipeline": execution_pipeline,
            "atomic_finalization": True,
        }
    )
    provenance_path = job_root / "provenance.json"
    _atomic_json(provenance_path, provenance)
    ARTIFACT_JOB_BACKEND.update_provenance(
        artifact_job_id,
        provenance,
    )

    artifacts = [
        {
            "type": "point_cloud_laz",
            "name": final_path.name,
            "relative_path": _relative_to_data(final_path),
            "size_bytes": final_path.stat().st_size,
            "sha256": output_sha,
        },
        {
            "type": "pointcloud_processing_pipeline",
            "name": contract_path.name,
            "relative_path": _relative_to_data(contract_path),
            "size_bytes": contract_path.stat().st_size,
        },
        {
            "type": "pointcloud_processing_qa",
            "name": qa_path.name,
            "relative_path": _relative_to_data(qa_path),
            "size_bytes": qa_path.stat().st_size,
        },
        {
            "type": "pointcloud_processing_provenance",
            "name": provenance_path.name,
            "relative_path": _relative_to_data(provenance_path),
            "size_bytes": provenance_path.stat().st_size,
        },
    ]
    ARTIFACT_JOB_BACKEND.update(
        artifact_job_id,
        status="completed",
        progress=100,
        phase="completed",
        message=(
            "Punktwolken-Reprojection abgeschlossen; "
            "Point Count und Ziel-CRS wurden verifiziert."
        ),
        artifacts=artifacts,
    )


if __name__ == "__main__":
    consume(
        PROCESSOR,
        handle,
        backend=ARTIFACT_JOB_BACKEND,
    )
