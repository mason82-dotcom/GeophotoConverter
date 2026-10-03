from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin


def _load_worker():
    repo_root = Path(__file__).resolve().parents[2]
    workers_root = repo_root / "workers"
    backend_root = repo_root / "backend"
    sys.path.insert(0, str(workers_root))
    sys.path.insert(0, str(backend_root))
    try:
        spec = importlib.util.spec_from_file_location(
            "geophoto_raster_processing_worker_test",
            workers_root / "raster" / "worker.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)
        sys.path.pop(0)


def _write_multiband(path: Path) -> None:
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
        dst.set_band_description(1, "Red")
        dst.set_band_description(2, "Green")
        dst.set_band_description(3, "NIR")
        dst.set_band_description(4, "Red Edge")


def _index_payload(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "dataset_id": "dataset-1",
        "engine": "raster-processing",
        "profile": "derived",
        "workflow": "vegetation_index_ndvi",
        "options": {
            "operation": "vegetation_index",
            "source_job_id": "source-job",
            "source_artifact_index": 0,
            "source_relative_path": "jobs/source-job/project/odm_orthophoto.tif",
            "source_artifact_type": "multiband_orthophoto",
            "source_sha256": None,
            "output_relative_path": f"jobs/{job_id}/derived/ndvi.tif",
            "index_type": "ndvi",
            "backend": "cpu",
            "tile_size": 128,
            "cuda_min_pixels": 1_048_576,
            "allow_m3m_fallback": False,
            "inspection": {
                "width": 6,
                "height": 4,
                "crs": "EPSG:32632",
                "band_map": {
                    "red": 1,
                    "green": 2,
                    "nir": 3,
                    "rededge": 4,
                },
                "band_mapping_source": "raster_band_descriptions",
                "warnings": [],
            },
        },
    }


def test_raster_worker_creates_ndvi_and_provenance(monkeypatch, tmp_path):
    worker = _load_worker()
    monkeypatch.setattr(worker, "DATA_ROOT", tmp_path.resolve())
    monkeypatch.setattr(worker, "cancellation_requested", lambda job_id: False)

    source = tmp_path / "jobs" / "source-job" / "project" / "odm_orthophoto.tif"
    _write_multiband(source)

    updates = []
    monkeypatch.setattr(
        worker,
        "update_job",
        lambda job_id, **kwargs: updates.append((job_id, kwargs)),
    )

    job_id = "raster-job"
    worker.handle(_index_payload(job_id))

    final = updates[-1][1]
    assert final["status"] == "completed"
    assert final["progress"] == 100
    assert [item["type"] for item in final["artifacts"]] == [
        "vegetation_index_ndvi",
        "raster_processing_provenance",
    ]

    output = tmp_path / "jobs" / job_id / "derived" / "ndvi.tif"
    assert output.is_file()
    with rasterio.open(output) as dataset:
        assert dataset.crs.to_string() == "EPSG:32632"
        assert dataset.descriptions[0] == "NDVI"
        values = dataset.read(1)
        assert float(values[0, 0]) == pytest.approx(0.6, abs=1e-6)

    provenance_path = tmp_path / "jobs" / job_id / "raster-processing-provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["operation"] == "vegetation_index"
    assert provenance["index_type"] == "ndvi"
    assert provenance["backend_used"] == "cpu"
    assert provenance["source_job_id"] == "source-job"
    assert len(provenance["source_sha256"]) == 64
    assert len(provenance["output_sha256"]) == 64
    assert provenance["statistics"]["mean"] == pytest.approx(0.6, abs=1e-6)


def test_raster_worker_creates_ndvi_scouting_zones(monkeypatch, tmp_path):
    worker = _load_worker()
    monkeypatch.setattr(worker, "DATA_ROOT", tmp_path.resolve())
    monkeypatch.setattr(worker, "cancellation_requested", lambda job_id: False)

    source = tmp_path / "jobs" / "source-job" / "derived" / "ndvi.tif"
    source.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=3,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:32632",
        transform=from_origin(500000.0, 5500000.0, 0.10, 0.10),
        nodata=-9999.0,
    ) as dst:
        dst.write(
            np.asarray(
                [[-0.5, 0.1, 0.3], [0.5, 0.7, 0.9]],
                dtype=np.float32,
            ),
            1,
        )

    updates = []
    monkeypatch.setattr(
        worker,
        "update_job",
        lambda job_id, **kwargs: updates.append((job_id, kwargs)),
    )

    job_id = "zones-job"
    payload = {
        "job_id": job_id,
        "dataset_id": "dataset-1",
        "engine": "raster-processing",
        "profile": "derived",
        "workflow": "ndvi_scouting_zones",
        "options": {
            "operation": "ndvi_zones",
            "source_job_id": "source-job",
            "source_artifact_index": 0,
            "source_relative_path": "jobs/source-job/derived/ndvi.tif",
            "source_artifact_type": "vegetation_index_ndvi",
            "output_relative_path": f"jobs/{job_id}/derived/ndvi_scouting_zones.tif",
            "thresholds": [0.2, 0.4, 0.6, 0.8],
            "tile_size": 128,
        },
    }

    worker.handle(payload)

    final = updates[-1][1]
    assert final["status"] == "completed"
    assert final["artifacts"][0]["type"] == "ndvi_scouting_zones"
    assert final["artifacts"][0]["class_counts"] == {
        "0": 0,
        "1": 2,
        "2": 1,
        "3": 1,
        "4": 1,
        "5": 1,
    }


def test_raster_worker_cancellation_removes_partial_output(monkeypatch, tmp_path):
    worker = _load_worker()
    monkeypatch.setattr(worker, "DATA_ROOT", tmp_path.resolve())

    source = tmp_path / "jobs" / "source-job" / "project" / "odm_orthophoto.tif"
    _write_multiband(source)

    updates = []
    monkeypatch.setattr(
        worker,
        "update_job",
        lambda job_id, **kwargs: updates.append((job_id, kwargs)),
    )
    monkeypatch.setattr(worker, "cancellation_requested", lambda job_id: True)

    job_id = "cancelled-job"
    worker.handle(_index_payload(job_id))

    final = updates[-1][1]
    assert final["status"] == "cancelled"
    output = tmp_path / "jobs" / job_id / "derived" / "ndvi.tif"
    assert not output.exists()
    provenance = tmp_path / "jobs" / job_id / "raster-processing-provenance.json"
    assert not provenance.exists()


def test_raster_worker_rejects_output_outside_own_job(monkeypatch, tmp_path):
    worker = _load_worker()
    monkeypatch.setattr(worker, "DATA_ROOT", tmp_path.resolve())

    source = tmp_path / "jobs" / "source-job" / "project" / "odm_orthophoto.tif"
    _write_multiband(source)

    payload = _index_payload("raster-job")
    payload["options"]["output_relative_path"] = "jobs/other-job/derived/ndvi.tif"

    with pytest.raises(ValueError, match="belong to its processing job"):
        worker.handle(payload)
