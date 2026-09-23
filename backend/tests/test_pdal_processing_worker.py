from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_worker():
    repo_root = Path(__file__).resolve().parents[2]
    workers_root = repo_root / "workers"
    sys.path.insert(0, str(workers_root))
    try:
        spec = importlib.util.spec_from_file_location(
            "geophoto_pdal_processing_worker_test",
            workers_root / "pdal" / "worker.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def _contract(job_id: str) -> dict:
    source = "jobs/source-job/results/cloud.laz"
    output = f"jobs/{job_id}/derived/reprojected.laz"
    return {
        "schema_version": 1,
        "operation": "horizontal_reprojection",
        "pdal_version_contract": "2.10.2",
        "source": {
            "relative_path": source,
            "reader": "readers.las",
            "crs": "EPSG:32632",
        },
        "output": {
            "relative_path": output,
            "writer": "writers.las",
            "crs": "EPSG:32633",
            "format": "laz",
        },
        "coordinate_scale_m": 0.001,
        "vertical_transform": False,
        "vertical_reference": {
            "status": "unchanged_unspecified",
            "note": "horizontal only",
        },
        "pipeline": {
            "pipeline": [
                {
                    "type": "readers.las",
                    "filename": f"/data/{source}",
                },
                {
                    "type": "filters.reprojection",
                    "in_srs": "EPSG:32632",
                    "out_srs": "EPSG:32633",
                },
                {
                    "type": "writers.las",
                    "filename": f"/data/{output}",
                    "a_srs": "EPSG:32633",
                    "compression": True,
                    "forward": "header,vlr",
                    "extra_dims": "all",
                    "scale_x": 0.001,
                    "scale_y": 0.001,
                    "scale_z": 0.001,
                    "offset_x": "auto",
                    "offset_y": "auto",
                    "offset_z": "auto",
                },
            ]
        },
    }


def _payload(job_id: str) -> dict:
    contract = _contract(job_id)
    return {
        "job_id": job_id,
        "dataset_id": "dataset-1",
        "engine": "pdal-processing",
        "profile": "derived",
        "workflow": "pointcloud_reprojection",
        "options": {
            "operation": "horizontal_reprojection",
            "source_job_id": "source-job",
            "source_artifact_index": 2,
            "contract": contract,
            "provenance": {
                "schema_version": 1,
                "operation": "horizontal_reprojection",
                "source_job_id": "source-job",
                "source_artifact_index": 2,
                "source_sha256": None,
                "source_relative_path": contract["source"]["relative_path"],
                "output_relative_path": contract["output"]["relative_path"],
                "source_crs": "EPSG:32632",
                "target_crs": "EPSG:32633",
                "coordinate_scale_m": 0.001,
                "vertical_reference": contract["vertical_reference"],
                "pipeline": contract["pipeline"],
                "software": {
                    "engine": "pdal",
                    "version_contract": "2.10.2",
                },
            },
        },
    }


def _summary(points: int, *, target: bool) -> dict:
    return {
        "summary": {
            "num_points": points,
            "bounds": {
                "minx": 400000.0 if target else 100.0,
                "miny": 5400000.0 if target else 200.0,
                "minz": 50.0,
                "maxx": 400010.0 if target else 107.0,
                "maxy": 5400010.0 if target else 214.0,
                "maxz": 57.0,
            },
            "srs": {
                "wkt": (
                    'PROJCRS["WGS 84 / UTM zone 33N",ID["EPSG",32633]]'
                    if target
                    else 'PROJCRS["WGS 84 / UTM zone 32N",ID["EPSG",32632]]'
                )
            },
        }
    }


def test_processing_worker_creates_derived_artifacts_and_provenance(
    monkeypatch,
    tmp_path,
):
    worker = _load_worker()
    monkeypatch.setattr(worker, "DATA_ROOT", tmp_path.resolve())

    source = tmp_path / "jobs" / "source-job" / "results" / "cloud.laz"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-point-cloud")

    updates = []
    monkeypatch.setattr(
        worker,
        "update_job",
        lambda job_id, **kwargs: updates.append((job_id, kwargs)),
    )

    def fake_run(job_id, command, *, cwd, log_path, **kwargs):
        assert command[0] == "timeout"
        assert "pdal" in command
        output = tmp_path / "jobs" / job_id / "derived" / "reprojected.laz"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"reprojected-point-cloud")
        return 0

    monkeypatch.setattr(worker, "run_process", fake_run)
    monkeypatch.setattr(
        worker,
        "_pdal_summary",
        lambda path: _summary(8, target=path.name == "reprojected.laz"),
    )

    job_id = "derived-job"
    worker.handle(_payload(job_id))

    final = updates[-1][1]
    assert final["status"] == "completed"
    assert final["progress"] == 100
    artifacts = final["artifacts"]
    assert [item["type"] for item in artifacts] == [
        "point_cloud_laz",
        "pointcloud_reprojection_pipeline",
        "pointcloud_reprojection_provenance",
    ]
    assert artifacts[0]["derived_from"] == {
        "job_id": "source-job",
        "artifact_index": 2,
    }
    assert len(artifacts[0]["sha256"]) == 64

    provenance_path = (
        tmp_path / "jobs" / job_id / "reprojection-provenance.json"
    )
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["source_job_id"] == "source-job"
    assert provenance["source_artifact_index"] == 2
    assert len(provenance["source_sha256"]) == 64
    assert len(provenance["output_sha256"]) == 64
    assert provenance["qa"]["point_count_preserved"] is True
    assert provenance["qa"]["target_srs_verified"] is True
    assert provenance["qa"]["source"]["point_count"] == 8
    assert provenance["qa"]["output"]["point_count"] == 8


def test_processing_worker_rejects_output_outside_own_job(monkeypatch, tmp_path):
    worker = _load_worker()
    monkeypatch.setattr(worker, "DATA_ROOT", tmp_path.resolve())

    payload = _payload("derived-job")
    payload["options"]["contract"]["output"]["relative_path"] = (
        "jobs/other-job/derived/reprojected.laz"
    )

    with pytest.raises(ValueError, match="belong to its processing job"):
        worker.handle(payload)


def test_processing_worker_blocks_changed_point_count_and_removes_output(
    monkeypatch,
    tmp_path,
):
    worker = _load_worker()
    monkeypatch.setattr(worker, "DATA_ROOT", tmp_path.resolve())

    source = tmp_path / "jobs" / "source-job" / "results" / "cloud.laz"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    monkeypatch.setattr(worker, "update_job", lambda *args, **kwargs: None)

    def fake_run(job_id, command, *, cwd, log_path, **kwargs):
        output = tmp_path / "jobs" / job_id / "derived" / "reprojected.laz"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"output")
        return 0

    monkeypatch.setattr(worker, "run_process", fake_run)

    def fake_summary(path):
        return _summary(7 if path.name == "reprojected.laz" else 8, target=path.name == "reprojected.laz")

    monkeypatch.setattr(worker, "_pdal_summary", fake_summary)

    with pytest.raises(RuntimeError, match="changed point count"):
        worker.handle(_payload("derived-job"))

    output = tmp_path / "jobs" / "derived-job" / "derived" / "reprojected.laz"
    assert not output.exists()


def test_processing_worker_handles_timeout_code_and_removes_partial_output(
    monkeypatch,
    tmp_path,
):
    worker = _load_worker()
    monkeypatch.setattr(worker, "DATA_ROOT", tmp_path.resolve())

    source = tmp_path / "jobs" / "source-job" / "results" / "cloud.laz"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    monkeypatch.setattr(worker, "update_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        worker,
        "_pdal_summary",
        lambda path: _summary(8, target=False),
    )

    def timeout_run(job_id, command, *, cwd, log_path, **kwargs):
        output = tmp_path / "jobs" / job_id / "derived" / "reprojected.laz"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"partial")
        return 124

    monkeypatch.setattr(worker, "run_process", timeout_run)

    with pytest.raises(TimeoutError, match="exceeded"):
        worker.handle(_payload("derived-job"))

    output = tmp_path / "jobs" / "derived-job" / "derived" / "reprojected.laz"
    assert not output.exists()
