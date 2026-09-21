from __future__ import annotations

import json
from collections import deque
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import (
    DATA_ROOT,
    DATASETS_ROOT,
    ENGINE_NAMES,
    PROFILE_NAMES,
    SUPPORTED_EXTENSIONS,
    ensure_directories,
)
from .metadata import read_metadata
from .maps import router as maps_router
from .queue import enqueue, ping as redis_ping, worker_state
from .storage import store

app = FastAPI(
    title="GeoPhoto Converter API",
    version="0.1.0",
    description="Local aerial imagery ingestion and photogrammetry processing orchestration.",
)

app.include_router(maps_router)


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class JobCreate(BaseModel):
    dataset_id: str
    engine: str
    profile: str = "standard"


def _dataset_or_404(dataset_id: str) -> dict:
    dataset = store.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


def _safe_relative_path(value: str, fallback: str) -> Path:
    normalized = value.replace("\\", "/").strip("/")
    candidate = PurePosixPath(normalized or fallback)
    if candidate.is_absolute() or any(part in ("", ".", "..") for part in candidate.parts):
        candidate = PurePosixPath(fallback)
    return Path(*candidate.parts)


@app.on_event("startup")
def startup() -> None:
    ensure_directories()


@app.get("/api/v1/health")
def health() -> dict:
    return {
        "status": "ok",
        "redis": "ok" if redis_ping() else "unavailable",
        "version": app.version,
    }


@app.get("/api/v1/services")
def services() -> dict:
    queue_ok = redis_ping()
    engines = {}
    for engine in ("odm", "micmac", "gsplat"):
        if queue_ok:
            try:
                engines[engine] = worker_state(engine)
            except Exception:
                engines[engine] = {"engine": engine, "status": "unknown", "queue_depth": None}
        else:
            engines[engine] = {"engine": engine, "status": "unavailable", "queue_depth": None}

    engines["odm"]["profile"] = "odm"
    engines["micmac"]["profile"] = "micmac"
    engines["gsplat"]["profile"] = "gsplat"
    engines["gsplat"]["gpu"] = True

    return {
        "redis": {"status": "ok" if queue_ok else "unavailable"},
        **engines,
        "telesculptor": {
            "status": "experimental",
            "profile": "experimental",
            "note": "Legacy comparison engine; not part of the default automated pipeline.",
        },
        "dronedb": {"status": "optional", "profile": "dronedb"},
        "open_webui": {"status": "optional", "profile": "ai"},
    }


@app.post("/api/v1/datasets", status_code=201)
def create_dataset(body: DatasetCreate) -> dict:
    dataset = store.create_dataset(body.name.strip(), body.description)
    (DATASETS_ROOT / dataset["id"] / "images").mkdir(parents=True, exist_ok=True)
    return dataset


@app.get("/api/v1/datasets")
def list_datasets() -> list[dict]:
    datasets = store.list_datasets()
    for dataset in datasets:
        total = dataset.get("image_count") or 0
        tagged = dataset.get("geotagged_count") or 0
        dataset["geotagged_percent"] = round(tagged * 100 / total, 1) if total else 0.0
    return datasets


@app.get("/api/v1/datasets/{dataset_id}")
def get_dataset(dataset_id: str) -> dict:
    dataset = _dataset_or_404(dataset_id)
    files = store.list_files(dataset_id)
    total = len(files)
    tagged = sum(
        1
        for item in files
        if (item.get("metadata") or {}).get("gps", {}).get("latitude") is not None
    )
    dataset["files"] = files
    dataset["geotagged_percent"] = round(tagged * 100 / total, 1) if total else 0.0
    return dataset


@app.get("/api/v1/datasets/{dataset_id}/geojson")
def dataset_geojson(dataset_id: str) -> dict:
    _dataset_or_404(dataset_id)
    features = []
    for item in store.list_files(dataset_id):
        metadata = item.get("metadata") or {}
        gps = metadata.get("gps") or {}
        latitude = gps.get("latitude")
        longitude = gps.get("longitude")
        if latitude is None or longitude is None:
            continue

        features.append(
            {
                "type": "Feature",
                "id": item["id"],
                "geometry": {
                    "type": "Point",
                    "coordinates": [longitude, latitude],
                },
                "properties": {
                    "file_id": item["id"],
                    "relative_path": item["relative_path"],
                    "altitude": gps.get("altitude"),
                    "capture_time": metadata.get("capture_time"),
                    "camera": metadata.get("camera"),
                    "dji": metadata.get("dji"),
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


@app.post("/api/v1/datasets/{dataset_id}/files")
async def upload_files(
    dataset_id: str,
    files: list[UploadFile] = File(...),
    relative_paths: str | None = Form(default=None),
) -> dict:
    _dataset_or_404(dataset_id)

    declared_paths: list[str] = []
    if relative_paths:
        try:
            value = json.loads(relative_paths)
            if isinstance(value, list):
                declared_paths = [str(item) for item in value]
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="relative_paths must be a JSON array") from exc

    image_root = DATASETS_ROOT / dataset_id / "images"
    image_root.mkdir(parents=True, exist_ok=True)

    accepted: list[dict] = []
    rejected: list[dict] = []

    for index, upload in enumerate(files):
        original_name = upload.filename or f"upload-{index}"
        requested_path = declared_paths[index] if index < len(declared_paths) else original_name
        rel_path = _safe_relative_path(requested_path, original_name)
        suffix = rel_path.suffix.lower()

        if suffix not in SUPPORTED_EXTENSIONS:
            rejected.append({"name": original_name, "reason": f"Unsupported extension: {suffix or 'none'}"})
            await upload.close()
            continue

        target = (image_root / rel_path).resolve()
        if image_root.resolve() not in target.parents:
            rejected.append({"name": original_name, "reason": "Unsafe path"})
            await upload.close()
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with target.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                handle.write(chunk)
                size += len(chunk)
        await upload.close()

        record = store.add_file(
            dataset_id=dataset_id,
            relative_path=rel_path.as_posix(),
            stored_path=target,
            size_bytes=size,
            media_type=upload.content_type,
        )
        accepted.append(record)

    return {"accepted": accepted, "rejected": rejected}


@app.post("/api/v1/datasets/{dataset_id}/scan")
def scan_dataset(dataset_id: str) -> dict:
    _dataset_or_404(dataset_id)
    store.set_dataset_scan_status(dataset_id, "running")
    scanned = 0
    failed = 0

    for item in store.list_files(dataset_id):
        try:
            metadata = read_metadata(Path(item["stored_path"]))
            store.update_file_scan(item["id"], metadata, None)
            scanned += 1
        except Exception as exc:
            store.update_file_scan(item["id"], None, str(exc))
            failed += 1

    store.set_dataset_scan_status(dataset_id, "completed" if failed == 0 else "completed_with_errors")
    dataset = get_dataset(dataset_id)
    return {
        "dataset": dataset,
        "scanned": scanned,
        "failed": failed,
    }


@app.get("/api/v1/jobs")
def list_jobs() -> list[dict]:
    return store.list_jobs()


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    artifacts = job.get("artifacts") or []
    for index, artifact in enumerate(artifacts):
        artifact["download_url"] = f"/api/v1/jobs/{job_id}/artifacts/{index}"
    return job


@app.get("/api/v1/jobs/{job_id}/logs")
def get_job_logs(
    job_id: str,
    tail: int = Query(default=200, ge=1, le=5000),
) -> dict:
    get_job(job_id)
    log_path = DATA_ROOT / "jobs" / job_id / "worker.log"
    if not log_path.is_file():
        return {"job_id": job_id, "lines": [], "available": False}

    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = list(deque((line.rstrip("\n") for line in handle), maxlen=tail))

    return {
        "job_id": job_id,
        "lines": lines,
        "available": True,
    }


@app.get("/api/v1/jobs/{job_id}/artifacts/{artifact_index}")
def download_job_artifact(job_id: str, artifact_index: int) -> FileResponse:
    job = get_job(job_id)
    artifacts = job.get("artifacts") or []
    if artifact_index < 0 or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="Artifact not found")

    artifact = artifacts[artifact_index]
    relative_path = artifact.get("relative_path")
    if not relative_path:
        raise HTTPException(status_code=404, detail="Artifact path is unavailable")

    path = (DATA_ROOT / relative_path).resolve()
    data_root = DATA_ROOT.resolve()
    if data_root not in path.parents:
        raise HTTPException(status_code=403, detail="Invalid artifact path")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")

    return FileResponse(
        path=path,
        filename=artifact.get("name") or path.name,
    )


@app.post("/api/v1/jobs", status_code=201)
def create_job(body: JobCreate) -> dict:
    _dataset_or_404(body.dataset_id)
    engine = body.engine.lower().strip()
    profile = body.profile.lower().strip()

    if engine not in ENGINE_NAMES:
        raise HTTPException(status_code=422, detail=f"Unknown engine: {engine}")
    if profile not in PROFILE_NAMES:
        raise HTTPException(status_code=422, detail=f"Unknown profile: {profile}")
    if engine == "telesculptor":
        raise HTTPException(
            status_code=409,
            detail="TeleSculptor is currently exposed as an experimental manual comparison service, not an automated job engine.",
        )
    if not redis_ping():
        raise HTTPException(status_code=503, detail="Job queue is unavailable")

    job = store.create_job(body.dataset_id, engine, profile)
    enqueue(
        engine,
        {
            "job_id": job["id"],
            "dataset_id": body.dataset_id,
            "engine": engine,
            "profile": profile,
        },
    )
    return job


@app.post("/api/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = get_job(job_id)
    if job["status"] in {"completed", "failed", "cancelled"}:
        return job
    store.update_job(job_id, status="cancel_requested", message="Cancellation requested")
    return get_job(job_id)
