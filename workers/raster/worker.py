from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from app.photogrammetry_multispectral import (
    RasterProcessingCancelled,
    classify_ndvi_zones,
    compute_vegetation_index,
)
from common.runtime import (
    DATA_ROOT,
    cancellation_requested,
    consume,
    update_job,
)


ENGINE = "raster-processing"


def _relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Raster artifact path must be a non-empty relative path.")
    raw = value.replace("\\", "/").strip()
    if raw.startswith("/"):
        raise ValueError("Raster artifact path must be relative.")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Raster artifact path contains unsafe components.")
    return path


def _data_path(relative: PurePosixPath) -> Path:
    root = DATA_ROOT.resolve()
    path = (root / Path(*relative.parts)).resolve()
    if path != root and root not in path.parents:
        raise ValueError("Raster artifact path leaves the data root.")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


def _append_log(job_id: str, message: str) -> None:
    path = DATA_ROOT / "jobs" / job_id / "worker.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(message.rstrip() + "\n")


def _paths_for_job(
    job_id: str,
    options: Mapping[str, Any],
) -> tuple[PurePosixPath, PurePosixPath, Path, Path]:
    source_relative = _relative_path(options.get("source_relative_path"))
    output_relative = _relative_path(options.get("output_relative_path"))

    expected_root = PurePosixPath("jobs") / job_id / "derived"
    if output_relative.parent != expected_root:
        raise ValueError("Raster output must belong to its processing job.")

    source_path = _data_path(source_relative)
    output_path = _data_path(output_relative)
    if not source_path.is_file():
        raise FileNotFoundError(f"Source raster not found: {source_relative}")
    if source_path.suffix.lower() not in {".tif", ".tiff"}:
        raise ValueError("Raster processing source must be a GeoTIFF.")
    if output_path.suffix.lower() not in {".tif", ".tiff"}:
        raise ValueError("Raster processing output must be a GeoTIFF.")

    return source_relative, output_relative, source_path, output_path


def _progress_updater(job_id: str):
    last = {"value": -1}

    def callback(done: int, total: int) -> None:
        if total <= 0:
            return
        percent = 10 + int(80 * min(done, total) / total)
        if percent <= last["value"]:
            return
        last["value"] = percent
        update_job(
            job_id,
            progress=float(percent),
            phase="raster_processing",
            message=f"Raster-Tiles verarbeitet: {done}/{total}.",
        )

    return callback


def _cancelled(job_id: str) -> bool:
    return cancellation_requested(job_id)


def _provenance_base(
    *,
    job_id: str,
    options: Mapping[str, Any],
    source_relative: PurePosixPath,
    output_relative: PurePosixPath,
    source_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "geophoto.raster-processing-provenance.v1",
        "processing_job_id": job_id,
        "operation": options.get("operation"),
        "source_job_id": options.get("source_job_id"),
        "source_artifact_index": options.get("source_artifact_index"),
        "source_artifact_type": options.get("source_artifact_type"),
        "source_relative_path": source_relative.as_posix(),
        "source_sha256": source_sha256,
        "output_relative_path": output_relative.as_posix(),
        "software": {
            "module": "app.photogrammetry_multispectral",
        },
    }


def _handle_vegetation_index(
    job_id: str,
    options: Mapping[str, Any],
    source_relative: PurePosixPath,
    output_relative: PurePosixPath,
    source_path: Path,
    output_path: Path,
    source_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    index_type = str(options.get("index_type") or "").lower()
    if index_type not in {"ndvi", "ndre", "gndvi"}:
        raise ValueError("Unsupported vegetation index operation.")
    expected_name = f"{index_type}.tif"
    if output_relative.name != expected_name:
        raise ValueError("Vegetation-index output filename does not match index type.")
    if options.get("source_artifact_type") != "multiband_orthophoto":
        raise ValueError("Vegetation-index source must be a multiband orthophoto.")

    result = compute_vegetation_index(
        source_path,
        output_path,
        index_type=index_type,
        backend=str(options.get("backend") or "auto"),
        tile_size=options.get("tile_size", "auto"),
        cuda_min_pixels=int(options.get("cuda_min_pixels", 1_048_576)),
        allow_m3m_fallback=bool(options.get("allow_m3m_fallback", False)),
        progress_callback=_progress_updater(job_id),
        cancel_check=lambda: _cancelled(job_id),
    )
    output_sha256 = _sha256(output_path)
    provenance = _provenance_base(
        job_id=job_id,
        options=options,
        source_relative=source_relative,
        output_relative=output_relative,
        source_sha256=source_sha256,
    )
    provenance.update(
        {
            "output_sha256": output_sha256,
            "index_type": index_type,
            "backend_requested": result["backend_requested"],
            "backend_used": result["backend_used"],
            "cuda": result["cuda"],
            "cuda_min_pixels": result["cuda_min_pixels"],
            "tile_size": result["tile_size"],
            "band_mapping_source": result["band_mapping_source"],
            "positive_band": result["positive_band"],
            "comparison_band": result["comparison_band"],
            "statistics": {
                "valid_pixels": result["valid_pixels"],
                "minimum": result["minimum"],
                "maximum": result["maximum"],
                "mean": result["mean"],
            },
            "warnings": result["warnings"],
        }
    )

    artifact = {
        "type": f"vegetation_index_{index_type}",
        "name": output_path.name,
        "relative_path": output_relative.as_posix(),
        "size_bytes": output_path.stat().st_size,
        "sha256": output_sha256,
        "derived_from": {
            "job_id": options.get("source_job_id"),
            "artifact_index": options.get("source_artifact_index"),
        },
        "index_type": index_type,
        "backend_used": result["backend_used"],
        "crs": (options.get("inspection") or {}).get("crs")
        if isinstance(options.get("inspection"), Mapping)
        else None,
    }
    return [artifact], provenance


def _handle_ndvi_zones(
    job_id: str,
    options: Mapping[str, Any],
    source_relative: PurePosixPath,
    output_relative: PurePosixPath,
    source_path: Path,
    output_path: Path,
    source_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if options.get("source_artifact_type") != "vegetation_index_ndvi":
        raise ValueError("NDVI scouting zones require a vegetation_index_ndvi source.")
    if output_relative.name != "ndvi_scouting_zones.tif":
        raise ValueError("Unexpected NDVI scouting-zone output filename.")

    raw_thresholds = options.get("thresholds")
    if not isinstance(raw_thresholds, list) or len(raw_thresholds) != 4:
        raise ValueError("NDVI scouting zones require four thresholds.")
    thresholds = tuple(float(value) for value in raw_thresholds)

    result = classify_ndvi_zones(
        source_path,
        output_path,
        thresholds=thresholds,  # type: ignore[arg-type]
        tile_size=options.get("tile_size", "auto"),
        progress_callback=_progress_updater(job_id),
        cancel_check=lambda: _cancelled(job_id),
    )
    output_sha256 = _sha256(output_path)
    provenance = _provenance_base(
        job_id=job_id,
        options=options,
        source_relative=source_relative,
        output_relative=output_relative,
        source_sha256=source_sha256,
    )
    provenance.update(
        {
            "output_sha256": output_sha256,
            "thresholds": result["thresholds"],
            "tile_size": result["tile_size"],
            "class_counts": result["class_counts"],
            "note": result["note"],
        }
    )
    artifact = {
        "type": "ndvi_scouting_zones",
        "name": output_path.name,
        "relative_path": output_relative.as_posix(),
        "size_bytes": output_path.stat().st_size,
        "sha256": output_sha256,
        "derived_from": {
            "job_id": options.get("source_job_id"),
            "artifact_index": options.get("source_artifact_index"),
        },
        "thresholds": result["thresholds"],
        "class_counts": result["class_counts"],
    }
    return [artifact], provenance


def handle(payload: dict[str, Any]) -> None:
    job_id = str(payload["job_id"])
    options = payload.get("options")
    if not isinstance(options, Mapping):
        raise ValueError("Raster processing options are missing.")

    operation = str(options.get("operation") or "")
    if operation not in {"vegetation_index", "ndvi_zones"}:
        raise ValueError("Unsupported raster processing operation.")

    source_relative, output_relative, source_path, output_path = _paths_for_job(
        job_id,
        options,
    )
    job_root = DATA_ROOT / "jobs" / job_id
    job_root.mkdir(parents=True, exist_ok=True)
    provenance_path = job_root / "raster-processing-provenance.json"

    output_path.unlink(missing_ok=True)
    provenance_path.unlink(missing_ok=True)

    update_job(
        job_id,
        status="running",
        progress=5,
        phase="source_qa",
        message="Rasterquelle und Processing-Vertrag werden geprüft.",
    )
    _append_log(
        job_id,
        f"Raster processing start: operation={operation} source={source_relative}",
    )
    source_sha256 = _sha256(source_path)

    try:
        if operation == "vegetation_index":
            artifacts, provenance = _handle_vegetation_index(
                job_id,
                options,
                source_relative,
                output_relative,
                source_path,
                output_path,
                source_sha256,
            )
        else:
            artifacts, provenance = _handle_ndvi_zones(
                job_id,
                options,
                source_relative,
                output_relative,
                source_path,
                output_path,
                source_sha256,
            )
    except RasterProcessingCancelled:
        output_path.unlink(missing_ok=True)
        provenance_path.unlink(missing_ok=True)
        update_job(
            job_id,
            status="cancelled",
            progress=0,
            phase="cancelled",
            message="Rasterverarbeitung wurde vom Benutzer abgebrochen.",
        )
        _append_log(job_id, "Raster processing cancelled.")
        return
    except Exception:
        output_path.unlink(missing_ok=True)
        provenance_path.unlink(missing_ok=True)
        raise

    provenance["output_artifact_type"] = artifacts[0]["type"]
    _atomic_json(provenance_path, provenance)
    artifacts.append(
        {
            "type": "raster_processing_provenance",
            "name": provenance_path.name,
            "relative_path": (
                PurePosixPath("jobs") / job_id / provenance_path.name
            ).as_posix(),
            "size_bytes": provenance_path.stat().st_size,
            "sha256": _sha256(provenance_path),
        }
    )

    update_job(
        job_id,
        status="completed",
        progress=100,
        phase="completed",
        message="Rasterverarbeitung abgeschlossen.",
        artifacts=artifacts,
    )
    _append_log(
        job_id,
        f"Raster processing completed: output={output_relative}",
    )


if __name__ == "__main__":
    consume(ENGINE, handle)
