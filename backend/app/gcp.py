from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .classifier import classify_media
from .photogrammetry_gcp import normalize_gcp_project
from .storage import store

router = APIRouter(prefix="/api/v1")


class GcpObservation(BaseModel):
    image_name: str = Field(min_length=1, max_length=1024)
    pixel_x: float = Field(ge=0, allow_inf_nan=False)
    pixel_y: float = Field(ge=0, allow_inf_nan=False)


class GcpPoint(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    role: Literal["control", "checkpoint"]
    x_m: float = Field(allow_inf_nan=False)
    y_m: float = Field(allow_inf_nan=False)
    z_m: float = Field(allow_inf_nan=False)
    sigma_x_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    sigma_y_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    sigma_z_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    observations: list[GcpObservation] = Field(default_factory=list)


class GcpProjectUpdate(BaseModel):
    project_crs: str = Field(min_length=1, max_length=512)
    points: list[GcpPoint] = Field(default_factory=list, max_length=10000)


def _dataset_or_404(dataset_id: str) -> dict:
    dataset = store.get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Datensatz nicht gefunden")
    return dataset


def _validate_dataset_observations(
    dataset_id: str,
    validation: dict,
) -> dict:
    files = store.list_files(dataset_id)
    mapping_paths: set[str] = set()
    all_paths: set[str] = set()

    for item in files:
        relative_path = str(item["relative_path"])
        all_paths.add(relative_path)
        classification = classify_media(
            relative_path,
            item.get("metadata"),
        )
        if classification.media_kind in {"RGB", "WIDE"}:
            mapping_paths.add(relative_path)

    issues = list(validation.get("issues") or [])
    for point in validation.get("points") or []:
        for observation in point.get("observations") or []:
            image_name = observation.get("image_name")
            if image_name not in all_paths:
                issues.append(
                    {
                        "code": "observation_image_not_in_dataset",
                        "severity": "blocked",
                        "point_id": point.get("id"),
                        "detail": str(image_name),
                    }
                )
            elif image_name not in mapping_paths:
                issues.append(
                    {
                        "code": "observation_image_not_mapping_input",
                        "severity": "blocked",
                        "point_id": point.get("id"),
                        "detail": str(image_name),
                    }
                )

    result = dict(validation)
    result["issues"] = issues
    if any(item.get("severity") == "blocked" for item in issues):
        result["status"] = "blocked"
    result["dataset_mapping_image_count"] = len(mapping_paths)
    return result


def _response(record: dict | None, dataset_id: str) -> dict:
    if record is None:
        return {
            "configured": False,
            "dataset_id": dataset_id,
            "project_crs": None,
            "points": [],
            "validation": None,
            "created_at": None,
            "updated_at": None,
        }
    return {
        "configured": True,
        "dataset_id": dataset_id,
        "project_crs": record["project_crs"],
        "points": record.get("points") or [],
        "validation": record.get("validation"),
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


@router.get("/datasets/{dataset_id}/gcp")
def get_gcp_project(dataset_id: str) -> dict:
    _dataset_or_404(dataset_id)
    return _response(store.get_gcp_project(dataset_id), dataset_id)


@router.put("/datasets/{dataset_id}/gcp")
def put_gcp_project(dataset_id: str, body: GcpProjectUpdate) -> dict:
    _dataset_or_404(dataset_id)
    points = [point.model_dump() for point in body.points]
    validation = normalize_gcp_project(points, body.project_crs)
    validation = _validate_dataset_observations(dataset_id, validation)

    record = store.upsert_gcp_project(
        dataset_id,
        body.project_crs.strip(),
        points,
        validation,
    )
    return _response(record, dataset_id)


@router.delete("/datasets/{dataset_id}/gcp")
def delete_gcp_project(dataset_id: str) -> dict:
    _dataset_or_404(dataset_id)
    deleted = store.delete_gcp_project(dataset_id)
    return {
        "dataset_id": dataset_id,
        "deleted": deleted,
    }
