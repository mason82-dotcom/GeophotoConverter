from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .config import DATA_ROOT
from .queue import enqueue, ping as redis_ping
from .storage import store


router = APIRouter(prefix="/api/v1", tags=["raster-processing"])

_RASTER_PROCESSING_ENGINE = "raster-processing"
_RASTER_SUFFIXES = {".tif", ".tiff"}
_DEFAULT_CUDA_MIN_PIXELS = 1_048_576


class VegetationIndexRequest(BaseModel):
    index_type: Literal["ndvi", "ndre", "gndvi"]
    backend: Literal["auto", "cpu", "cuda"] = "auto"
    tile_size: int | Literal["auto"] = "auto"
    cuda_min_pixels: int = Field(
        default=_DEFAULT_CUDA_MIN_PIXELS,
        ge=0,
        le=4_000_000_000,
    )
    allow_m3m_fallback: bool = False


class NdviZonesRequest(BaseModel):
    thresholds: list[float] = Field(
        default_factory=lambda: [0.20, 0.40, 0.60, 0.80],
        min_length=4,
        max_length=4,
    )
    tile_size: int | Literal["auto"] = "auto"


def _job_or_404(job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden")
    return job


def _artifact_or_404(
    job_id: str,
    artifact_index: int,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    job = _job_or_404(job_id)
    artifacts = job.get("artifacts") or []
    if artifact_index < 0 or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="Artefakt nicht gefunden")

    artifact = artifacts[artifact_index]
    relative = artifact.get("relative_path")
    if not isinstance(relative, str) or not relative.strip():
        raise HTTPException(status_code=404, detail="Artefaktpfad ist nicht verfügbar")

    path = (DATA_ROOT / relative).resolve()
    root = DATA_ROOT.resolve()
    if path != root and root not in path.parents:
        raise HTTPException(status_code=403, detail="Ungültiger Artefaktpfad")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Rasterartefakt nicht gefunden")
    if path.suffix.lower() not in _RASTER_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail="Rasterverarbeitung unterstützt ausschließlich GeoTIFF-Artefakte.",
        )

    return job, artifact, path


def _validate_tile_size(value: int | str) -> None:
    if value == "auto":
        return
    if not isinstance(value, int) or value < 128 or value > 4096:
        raise HTTPException(
            status_code=422,
            detail="tile_size muss 'auto' oder eine Ganzzahl zwischen 128 und 4096 sein.",
        )


def _validate_thresholds(values: list[float]) -> tuple[float, float, float, float]:
    thresholds = tuple(float(value) for value in values)
    if len(thresholds) != 4:
        raise HTTPException(status_code=422, detail="Vier NDVI-Schwellen sind erforderlich.")
    if not all(isfinite(value) and -1.0 <= value <= 1.0 for value in thresholds):
        raise HTTPException(
            status_code=422,
            detail="NDVI-Schwellen müssen endlich und zwischen -1 und +1 liegen.",
        )
    if not all(left < right for left, right in zip(thresholds, thresholds[1:])):
        raise HTTPException(
            status_code=422,
            detail="NDVI-Schwellen müssen streng aufsteigend sein.",
        )
    return thresholds  # type: ignore[return-value]


def _enqueue_derived_job(
    *,
    source_job: dict[str, Any],
    workflow: str,
    options: dict[str, Any],
    job_id: str,
) -> dict[str, Any]:
    if not redis_ping():
        raise HTTPException(
            status_code=503,
            detail="Raster-Processing-Warteschlange ist nicht verfügbar.",
        )

    processing_job = store.create_job(
        source_job["dataset_id"],
        _RASTER_PROCESSING_ENGINE,
        "derived",
        workflow,
        options,
        job_id=job_id,
    )
    enqueue(
        _RASTER_PROCESSING_ENGINE,
        {
            "job_id": job_id,
            "dataset_id": source_job["dataset_id"],
            "engine": _RASTER_PROCESSING_ENGINE,
            "profile": "derived",
            "workflow": workflow,
            "options": options,
        },
    )
    return processing_job


@router.post(
    "/jobs/{job_id}/artifacts/{artifact_index}/vegetation-index",
    status_code=201,
)
def create_vegetation_index(
    job_id: str,
    artifact_index: int,
    body: VegetationIndexRequest,
) -> dict[str, Any]:
    source_job, artifact, path = _artifact_or_404(job_id, artifact_index)
    if artifact.get("type") != "multiband_orthophoto":
        raise HTTPException(
            status_code=422,
            detail="Vegetationsindizes erfordern ein ODM-Multiband-Orthofoto.",
        )
    if body.allow_m3m_fallback and not (
        source_job.get("engine") == "odm"
        and source_job.get("workflow") == "multispectral"
    ):
        raise HTTPException(
            status_code=422,
            detail="M3M-Bandfallback ist nur für ODM-Multispektraljobs zulässig.",
        )
    _validate_tile_size(body.tile_size)

    try:
        from .photogrammetry_multispectral import inspect_multispectral_orthophoto

        inspection = inspect_multispectral_orthophoto(
            path,
            allow_m3m_fallback=body.allow_m3m_fallback,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Multispektrale Rasterunterstützung ist nicht verfügbar.",
        ) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Multiband-Orthofoto ist nicht verarbeitbar: {exc}",
        ) from exc

    processing_job_id = store.new_id()
    output_relative = (
        f"jobs/{processing_job_id}/derived/{body.index_type}.tif"
    )
    options = {
        "operation": "vegetation_index",
        "source_job_id": job_id,
        "source_artifact_index": artifact_index,
        "source_relative_path": artifact["relative_path"],
        "source_artifact_type": artifact.get("type"),
        "source_sha256": artifact.get("sha256"),
        "output_relative_path": output_relative,
        "index_type": body.index_type,
        "backend": body.backend,
        "tile_size": body.tile_size,
        "cuda_min_pixels": body.cuda_min_pixels,
        "allow_m3m_fallback": body.allow_m3m_fallback,
        "inspection": {
            "width": inspection["width"],
            "height": inspection["height"],
            "crs": inspection["crs"],
            "band_map": inspection["band_map"],
            "band_mapping_source": inspection["mapping_source"],
            "warnings": inspection["warnings"],
        },
    }
    return _enqueue_derived_job(
        source_job=source_job,
        workflow=f"vegetation_index_{body.index_type}",
        options=options,
        job_id=processing_job_id,
    )


@router.post(
    "/jobs/{job_id}/artifacts/{artifact_index}/ndvi-zones",
    status_code=201,
)
def create_ndvi_zones(
    job_id: str,
    artifact_index: int,
    body: NdviZonesRequest,
) -> dict[str, Any]:
    source_job, artifact, _ = _artifact_or_404(job_id, artifact_index)
    if artifact.get("type") != "vegetation_index_ndvi":
        raise HTTPException(
            status_code=422,
            detail="Scouting-Zonen erfordern ein abgeleitetes NDVI-Raster.",
        )
    _validate_tile_size(body.tile_size)
    thresholds = _validate_thresholds(body.thresholds)

    processing_job_id = store.new_id()
    output_relative = (
        f"jobs/{processing_job_id}/derived/ndvi_scouting_zones.tif"
    )
    options = {
        "operation": "ndvi_zones",
        "source_job_id": job_id,
        "source_artifact_index": artifact_index,
        "source_relative_path": artifact["relative_path"],
        "source_artifact_type": artifact.get("type"),
        "source_sha256": artifact.get("sha256"),
        "output_relative_path": output_relative,
        "thresholds": list(thresholds),
        "tile_size": body.tile_size,
    }
    return _enqueue_derived_job(
        source_job=source_job,
        workflow="ndvi_scouting_zones",
        options=options,
        job_id=processing_job_id,
    )
