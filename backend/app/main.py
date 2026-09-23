from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import deque
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import (
    DATA_ROOT,
    DATASETS_ROOT,
    ENGINE_NAMES,
    MAX_DATASET_BYTES,
    MAX_FILE_BYTES,
    PROFILE_NAMES,
    SUPPORTED_EXTENSIONS,
    WORKFLOW_NAMES,
    ensure_directories,
)
from .metadata import read_metadata
from .maps import router as maps_router
from .job_options import normalize_job_options
from .dronedb import router as dronedb_router
from .queue import enqueue, ping as redis_ping, worker_state
from .profiles import processing_catalog
from .previews import router as previews_router
from .photogrammetry import fuse_photogrammetry_metadata
from .pointcloud import router as pointcloud_router
from .qa import dataset_qa
from .services import external_services
from .storage import store

app = FastAPI(
    title="GeoPhoto Converter API",
    version="1.0.1",
    description="Lokale Aufnahme, Prüfung und Verarbeitung georeferenzierter Luftbilder.",
)

app.include_router(maps_router)
app.include_router(previews_router)
app.include_router(dronedb_router)
app.include_router(pointcloud_router)


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class JobCreate(BaseModel):
    dataset_id: str
    engine: str
    profile: str = "standard"
    workflow: str = "rgb"
    options: dict[str, object] = Field(default_factory=dict)


class Fh2MediaUpdate(BaseModel):
    media: dict[str, object] | None


def _canonical_photogrammetry(item: dict) -> dict:
    return fuse_photogrammetry_metadata(
        item.get("metadata"),
        item.get("fh2_media"),
    )


def _canonical_workflow(engine: str, workflow: str) -> str:
    """Translate legacy workflow identifiers to engine-specific canonical names."""
    if workflow == "rgb":
        if engine in {"odm", "micmac"}:
            return "mapping"
        if engine == "gsplat":
            return "reconstruction"
    return workflow


def _dataset_or_404(dataset_id: str) -> dict:
    dataset = store.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Datensatz nicht gefunden")
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


@app.get("/api/v1/processing/profiles")
def processing_profiles() -> dict:
    return processing_catalog()


@app.get("/api/v1/services")
def services(request: Request) -> dict:
    queue_ok = redis_ping()
    engines = {}
    for engine in ("odm", "micmac", "gsplat", "thermal"):
        if queue_ok:
            try:
                engines[engine] = worker_state(engine)
            except Exception:
                engines[engine] = {
                    "engine": engine,
                    "status": "unknown",
                    "queue_depth": None,
                }
        else:
            engines[engine] = {
                "engine": engine,
                "status": "unavailable",
                "queue_depth": None,
            }

    engines["odm"]["profile"] = "odm"
    engines["micmac"]["profile"] = "micmac"
    engines["gsplat"]["profile"] = "gsplat"
    engines["gsplat"]["gpu"] = True
    engines["thermal"]["profile"] = "thermal"
    engines["thermal"]["requires_dji_tsdk"] = True
    engines["thermal"]["platforms"] = ["M3T", "M4T"]
    engines["thermal"]["wide_thermal_coregistered"] = False
    engines["thermal"]["georeferenced_temperature_raster"] = False

    return {
        "redis": {"status": "ok" if queue_ok else "unavailable"},
        **engines,
        "telesculptor": {
            "status": "experimental",
            "profile": "experimental",
            "note": (
                "Legacy comparison engine; not part of the default "
                "automated pipeline."
            ),
        },
        **external_services(request),
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
    qa = dataset_qa(files)
    tagged = 0
    for item in files:
        photogrammetry = _canonical_photogrammetry(item)
        position = photogrammetry["position"]
        if (
            position["latitude_deg"] is not None
            and position["longitude_deg"] is not None
        ):
            tagged += 1
        item["photogrammetry"] = photogrammetry
        item["classification"] = qa["classifications"].get(item["relative_path"])
        item["preview_url"] = (
            f"/api/v1/datasets/{dataset_id}/files/{item['id']}/preview"
        )
    qa.pop("classifications", None)

    dataset["files"] = files
    dataset["geotagged_percent"] = round(tagged * 100 / total, 1) if total else 0.0
    dataset["qa"] = qa
    return dataset


@app.get("/api/v1/datasets/{dataset_id}/qa")
def get_dataset_qa(dataset_id: str) -> dict:
    _dataset_or_404(dataset_id)
    qa = dataset_qa(store.list_files(dataset_id))
    qa.pop("classifications", None)
    return qa


@app.get("/api/v1/datasets/{dataset_id}/geojson")
def dataset_geojson(dataset_id: str) -> dict:
    _dataset_or_404(dataset_id)
    features = []
    for item in store.list_files(dataset_id):
        metadata = item.get("metadata") or {}
        gps = metadata.get("gps") or {}
        photogrammetry = _canonical_photogrammetry(item)
        position = photogrammetry["position"]
        latitude = position["latitude_deg"]
        longitude = position["longitude_deg"]
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
                    "ellipsoid_height_m": photogrammetry["height"]["ellipsoid_m"],
                    "relative_height_m": photogrammetry["height"]["relative_m"],
                    "capture_time": metadata.get("capture_time"),
                    "utc_at_exposure_ms": photogrammetry["time"]["utc_at_exposure_ms"],
                    "capture_uuid": photogrammetry["capture_uuid"],
                    "rtk_fixed": photogrammetry["rtk"]["fixed"],
                    "camera": metadata.get("camera"),
                    "dji": metadata.get("dji"),
                    "photogrammetry_provenance": photogrammetry["provenance"],
                    "photogrammetry_conflicts": photogrammetry["conflicts"],
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


@app.put("/api/v1/datasets/{dataset_id}/files/{file_id}/fh2-media")
def update_file_fh2_media(
    dataset_id: str,
    file_id: str,
    body: Fh2MediaUpdate,
) -> dict:
    _dataset_or_404(dataset_id)
    item = store.get_file(dataset_id, file_id)
    if not item:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")

    store.update_file_fh2_media(file_id, body.media)
    updated = store.get_file(dataset_id, file_id)
    assert updated is not None
    updated["photogrammetry"] = _canonical_photogrammetry(updated)
    return updated


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
            raise HTTPException(status_code=400, detail="relative_paths muss ein JSON-Array sein") from exc

    image_root = DATASETS_ROOT / dataset_id / "images"
    image_root.mkdir(parents=True, exist_ok=True)

    accepted: list[dict] = []
    rejected: list[dict] = []
    dataset_bytes = store.dataset_size_bytes(dataset_id)

    for index, upload in enumerate(files):
        original_name = upload.filename or f"upload-{index}"
        requested_path = declared_paths[index] if index < len(declared_paths) else original_name
        rel_path = _safe_relative_path(requested_path, original_name)
        suffix = rel_path.suffix.lower()

        if suffix not in SUPPORTED_EXTENSIONS:
            rejected.append({"name": original_name, "reason": f"Nicht unterstützte Dateiendung: {suffix or 'keine'}"})
            await upload.close()
            continue

        target = (image_root / rel_path).resolve()
        if image_root.resolve() not in target.parents:
            rejected.append({"name": original_name, "reason": "Unsicherer Dateipfad"})
            await upload.close()
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        size = 0
        digest = hashlib.sha256()
        exceeded_limit = False

        try:
            with temp_path.open("wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        exceeded_limit = True
                        break
                    digest.update(chunk)
                    handle.write(chunk)
        finally:
            await upload.close()

        if exceeded_limit:
            temp_path.unlink(missing_ok=True)
            rejected.append(
                {
                    "name": original_name,
                    "reason": f"Datei überschreitet das Limit von {MAX_FILE_BYTES // (1024 * 1024)} MiB",
                }
            )
            continue

        checksum = digest.hexdigest()
        duplicate = store.find_file_by_sha256(dataset_id, checksum)
        if duplicate is not None:
            temp_path.unlink(missing_ok=True)
            rejected.append(
                {
                    "name": original_name,
                    "reason": "Datei ist ein Duplikat",
                    "duplicate_of": duplicate["relative_path"],
                    "sha256": checksum,
                }
            )
            continue

        existing = store.get_file_by_relative_path(dataset_id, rel_path.as_posix())
        replaced_size = int(existing["size_bytes"]) if existing else 0
        projected_size = dataset_bytes - replaced_size + size
        if projected_size > MAX_DATASET_BYTES:
            temp_path.unlink(missing_ok=True)
            rejected.append(
                {
                    "name": original_name,
                    "reason": (
                        "Datensatz-Größenlimit überschritten "
                        f"({MAX_DATASET_BYTES / 1024 / 1024 / 1024:.0f} GiB)"
                    ),
                }
            )
            continue

        os.replace(temp_path, target)
        record = store.add_file(
            dataset_id=dataset_id,
            relative_path=rel_path.as_posix(),
            stored_path=target,
            size_bytes=size,
            media_type=upload.content_type,
            sha256=checksum,
        )
        dataset_bytes = projected_size
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
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden")

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
        raise HTTPException(status_code=404, detail="Artefakt nicht gefunden")

    artifact = artifacts[artifact_index]
    relative_path = artifact.get("relative_path")
    if not relative_path:
        raise HTTPException(status_code=404, detail="Artefaktpfad ist nicht verfügbar")

    path = (DATA_ROOT / relative_path).resolve()
    data_root = DATA_ROOT.resolve()
    if data_root not in path.parents:
        raise HTTPException(status_code=403, detail="Ungültiger Artefaktpfad")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artefaktdatei nicht gefunden")

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
        raise HTTPException(status_code=422, detail=f"Unbekannte Engine: {engine}")
    if profile not in PROFILE_NAMES:
        raise HTTPException(status_code=422, detail=f"Unbekanntes Profil: {profile}")

    workflow = body.workflow.lower().strip()
    if workflow not in WORKFLOW_NAMES:
        raise HTTPException(status_code=422, detail=f"Unbekannter Workflow: {workflow}")
    workflow = _canonical_workflow(engine, workflow)
    if workflow == "mapping" and engine not in {"odm", "micmac"}:
        raise HTTPException(
            status_code=422,
            detail="Der Mapping-Workflow ist derzeit nur mit ODM oder MicMac verfügbar.",
        )
    if workflow == "reconstruction" and engine != "gsplat":
        raise HTTPException(
            status_code=422,
            detail="Der Reconstruction-Workflow ist nur mit gsplat verfügbar.",
        )
    if workflow == "multispectral" and engine != "odm":
        raise HTTPException(
            status_code=422,
            detail="Der Multispektral-Workflow ist derzeit nur mit ODM verfügbar.",
        )
    if workflow == "thermal" and engine != "thermal":
        raise HTTPException(
            status_code=422,
            detail="Der Thermal-Workflow ist nur mit der Thermal-Engine verfügbar.",
        )
    if engine == "thermal" and workflow != "thermal":
        raise HTTPException(
            status_code=422,
            detail="Die Thermal-Engine erfordert workflow='thermal'.",
        )

    if engine in {"odm", "micmac", "gsplat", "thermal"}:
        qa = dataset_qa(store.list_files(body.dataset_id))
        readiness_key = (
            "odm_multispectral"
            if engine == "odm" and workflow == "multispectral"
            else "thermal"
            if engine == "thermal"
            else engine
        )
        engine_readiness = qa["readiness"][readiness_key]
        if not engine_readiness["ready"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": engine_readiness["reason"],
                    "engine": engine,
                    "workflow": workflow,
                    "eligible_images": engine_readiness["eligible_images"],
                    "engine_inputs": qa["engine_inputs"],
                },
            )
    try:
        job_options = normalize_job_options(engine, workflow, body.options)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if engine == "telesculptor":
        raise HTTPException(
            status_code=409,
            detail="TeleSculptor ist derzeit nur als experimenteller manueller Vergleichsdienst verfügbar und keine automatisierte Job-Engine.",
        )
    if not redis_ping():
        raise HTTPException(status_code=503, detail="Job-Warteschlange ist nicht verfügbar")

    job = store.create_job(
        body.dataset_id,
        engine,
        profile,
        workflow,
        job_options,
    )
    enqueue(
        engine,
        {
            "job_id": job["id"],
            "dataset_id": body.dataset_id,
            "engine": engine,
            "profile": profile,
            "workflow": workflow,
            "options": job_options,
        },
    )
    return job


@app.post("/api/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = get_job(job_id)
    if job["status"] in {"completed", "failed", "cancelled"}:
        return job
    store.update_job(job_id, status="cancel_requested", message="Abbruch angefordert")
    return get_job(job_id)
