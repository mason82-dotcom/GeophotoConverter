from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from app import raster_processing as raster_module
from app.config import DATA_ROOT
from app.storage import store


def _write_multiband(path: Path, *, descriptions: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.zeros((4, 4, 6), dtype=np.float32)
    data[0] = 0.20
    data[1] = 0.40
    data[2] = 0.80
    data[3] = 0.30

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=6,
        height=4,
        count=4,
        dtype="float32",
        crs="EPSG:32632",
        transform=from_origin(500000.0, 5500000.0, 0.05, 0.05),
    ) as dst:
        dst.write(data)
        if descriptions:
            dst.set_band_description(1, "Red")
            dst.set_band_description(2, "Green")
            dst.set_band_description(3, "NIR")
            dst.set_band_description(4, "Red Edge")


def _source_job(*, workflow: str = "multispectral", descriptions: bool = True):
    dataset = store.create_dataset("Raster source", None)
    job = store.create_job(dataset["id"], "odm", "standard", workflow)
    source = (
        DATA_ROOT
        / "jobs"
        / job["id"]
        / "project"
        / "odm_orthophoto"
        / "odm_orthophoto.tif"
    )
    _write_multiband(source, descriptions=descriptions)
    store.update_job(
        job["id"],
        status="completed",
        progress=100,
        artifacts=[
            {
                "type": "multiband_orthophoto",
                "name": source.name,
                "relative_path": source.relative_to(DATA_ROOT).as_posix(),
                "size_bytes": source.stat().st_size,
            }
        ],
    )
    return store.get_job(job["id"])


def test_vegetation_index_endpoint_enqueues_internal_raster_job(
    client,
    monkeypatch,
):
    source_job = _source_job()
    queued = {}

    monkeypatch.setattr(raster_module, "redis_ping", lambda: True)

    def fake_enqueue(engine, payload):
        queued["engine"] = engine
        queued["payload"] = payload
        return "1-0"

    monkeypatch.setattr(raster_module, "enqueue", fake_enqueue)

    response = client.post(
        f"/api/v1/jobs/{source_job['id']}/artifacts/0/vegetation-index",
        json={
            "index_type": "ndvi",
            "backend": "cpu",
            "tile_size": 128,
        },
    )

    assert response.status_code == 201
    job = response.json()
    assert job["engine"] == "raster-processing"
    assert job["profile"] == "derived"
    assert job["workflow"] == "vegetation_index_ndvi"
    assert queued["engine"] == "raster-processing"
    assert queued["payload"]["job_id"] == job["id"]

    options = job["options"]
    assert options["operation"] == "vegetation_index"
    assert options["source_job_id"] == source_job["id"]
    assert options["source_artifact_index"] == 0
    assert options["index_type"] == "ndvi"
    assert options["backend"] == "cpu"
    assert options["output_relative_path"] == (
        f"jobs/{job['id']}/derived/ndvi.tif"
    )
    assert options["inspection"]["band_map"] == {
        "red": 1,
        "green": 2,
        "nir": 3,
        "rededge": 4,
    }


def test_m3m_fallback_requires_multispectral_odm_source(
    client,
    monkeypatch,
):
    source_job = _source_job(workflow="mapping", descriptions=False)
    monkeypatch.setattr(
        raster_module,
        "redis_ping",
        lambda: (_ for _ in ()).throw(AssertionError("queue must not be checked")),
    )

    response = client.post(
        f"/api/v1/jobs/{source_job['id']}/artifacts/0/vegetation-index",
        json={
            "index_type": "ndvi",
            "allow_m3m_fallback": True,
        },
    )

    assert response.status_code == 422
    assert "M3M-Bandfallback" in response.json()["detail"]


def test_ndvi_zones_endpoint_accepts_only_derived_ndvi(
    client,
    monkeypatch,
):
    dataset = store.create_dataset("NDVI", None)
    source_job = store.create_job(
        dataset["id"],
        "raster-processing",
        "derived",
        "vegetation_index_ndvi",
    )
    source = DATA_ROOT / "jobs" / source_job["id"] / "derived" / "ndvi.tif"
    source.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:32632",
        transform=from_origin(500000.0, 5500000.0, 0.10, 0.10),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.asarray([[0.1, 0.3], [0.5, 0.9]], dtype=np.float32), 1)

    store.update_job(
        source_job["id"],
        status="completed",
        progress=100,
        artifacts=[
            {
                "type": "vegetation_index_ndvi",
                "name": source.name,
                "relative_path": source.relative_to(DATA_ROOT).as_posix(),
                "size_bytes": source.stat().st_size,
            }
        ],
    )

    queued = {}
    monkeypatch.setattr(raster_module, "redis_ping", lambda: True)
    monkeypatch.setattr(
        raster_module,
        "enqueue",
        lambda engine, payload: queued.update(engine=engine, payload=payload) or "1-0",
    )

    response = client.post(
        f"/api/v1/jobs/{source_job['id']}/artifacts/0/ndvi-zones",
        json={
            "thresholds": [0.2, 0.4, 0.6, 0.8],
            "tile_size": 128,
        },
    )

    assert response.status_code == 201
    job = response.json()
    assert job["engine"] == "raster-processing"
    assert job["workflow"] == "ndvi_scouting_zones"
    assert job["options"]["operation"] == "ndvi_zones"
    assert job["options"]["thresholds"] == [0.2, 0.4, 0.6, 0.8]
    assert job["options"]["output_relative_path"] == (
        f"jobs/{job['id']}/derived/ndvi_scouting_zones.tif"
    )
    assert queued["engine"] == "raster-processing"


def test_raster_processing_queue_unavailable_after_source_validation(
    client,
    monkeypatch,
):
    source_job = _source_job()
    monkeypatch.setattr(raster_module, "redis_ping", lambda: False)

    response = client.post(
        f"/api/v1/jobs/{source_job['id']}/artifacts/0/vegetation-index",
        json={"index_type": "gndvi"},
    )

    assert response.status_code == 503


def test_raster_processing_is_not_public_dataset_engine(client):
    dataset = store.create_dataset("Internal raster engine", None)

    response = client.post(
        "/api/v1/jobs",
        json={
            "dataset_id": dataset["id"],
            "engine": "raster-processing",
            "profile": "standard",
            "workflow": "rgb",
        },
    )

    assert response.status_code == 422
    assert "Unbekannte Engine" in response.json()["detail"]
