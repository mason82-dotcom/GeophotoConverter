from __future__ import annotations

import sqlite3

import pytest

from app.storage import store


def _source_job() -> dict:
    dataset = store.create_dataset("Artifact Processing", None)
    job = store.create_job(
        dataset["id"],
        "odm",
        "standard",
        "mapping",
    )
    store.update_job(
        job["id"],
        status="completed",
        progress=100,
        artifacts=[
            {
                "type": "point_cloud_laz",
                "name": "odm_georeferenced_model.laz",
                "relative_path": "jobs/source/odm/odm_georeferenced_model.laz",
                "size_bytes": 1234,
            }
        ],
    )
    result = store.get_job(job["id"])
    assert result is not None
    return result


def test_artifact_job_roundtrip_decodes_json_fields():
    source = _source_job()

    derived = store.create_artifact_job(
        source["id"],
        0,
        "pdal",
        "reproject",
        options={"target_crs": "EPSG:32632"},
        provenance={
            "source_crs": "EPSG:4326",
            "software": {"engine": "pdal", "version_contract": "2.10.2"},
        },
    )

    assert derived["source_job_id"] == source["id"]
    assert derived["source_artifact_index"] == 0
    assert derived["processor"] == "pdal"
    assert derived["operation"] == "reproject"
    assert derived["status"] == "prepared"
    assert derived["progress"] == 0.0
    assert derived["options"] == {"target_crs": "EPSG:32632"}
    assert derived["provenance"]["source_crs"] == "EPSG:4326"


def test_artifact_job_update_preserves_and_replaces_structured_state():
    source = _source_job()
    derived = store.create_artifact_job(
        source["id"],
        0,
        "pdal",
        "reproject",
        options={"target_crs": "EPSG:32632"},
        provenance={"step": "planned"},
    )

    store.update_artifact_job(
        derived["id"],
        status="completed",
        progress=100,
        phase="completed",
        message="Reprojection abgeschlossen.",
        artifacts=[
            {
                "type": "point_cloud_laz",
                "name": "reprojected.laz",
                "relative_path": "artifact-jobs/result/reprojected.laz",
                "size_bytes": 4321,
            }
        ],
        provenance={"step": "completed", "target_crs": "EPSG:32632"},
    )

    updated = store.get_artifact_job(derived["id"])
    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["progress"] == 100.0
    assert updated["phase"] == "completed"
    assert updated["artifacts"][0]["name"] == "reprojected.laz"
    assert updated["provenance"] == {
        "step": "completed",
        "target_crs": "EPSG:32632",
    }


def test_artifact_job_progress_is_clamped():
    source = _source_job()
    derived = store.create_artifact_job(
        source["id"],
        0,
        "pdal",
        "reproject",
    )

    store.update_artifact_job(derived["id"], progress=125)
    assert store.get_artifact_job(derived["id"])["progress"] == 100.0

    store.update_artifact_job(derived["id"], progress=-5)
    assert store.get_artifact_job(derived["id"])["progress"] == 0.0


def test_artifact_jobs_can_be_filtered_by_source_job():
    first = _source_job()
    second = _source_job()

    a = store.create_artifact_job(first["id"], 0, "pdal", "reproject")
    store.create_artifact_job(second["id"], 0, "pdal", "reproject")

    listed = store.list_artifact_jobs(source_job_id=first["id"])
    assert [item["id"] for item in listed] == [a["id"]]


def test_artifact_jobs_cascade_with_source_job():
    source = _source_job()
    derived = store.create_artifact_job(
        source["id"],
        0,
        "pdal",
        "reproject",
    )

    with store.connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id=?", (source["id"],))

    assert store.get_artifact_job(derived["id"]) is None


def test_artifact_job_rejects_invalid_source_reference_and_index():
    source = _source_job()

    with pytest.raises(ValueError, match="non-negative"):
        store.create_artifact_job(
            source["id"],
            -1,
            "pdal",
            "reproject",
        )

    with pytest.raises(sqlite3.IntegrityError):
        store.create_artifact_job(
            "missing-source-job",
            0,
            "pdal",
            "reproject",
        )


@pytest.mark.parametrize(
    ("processor", "operation"),
    [
        ("", "reproject"),
        ("pdal", ""),
    ],
)
def test_artifact_job_requires_processor_and_operation(processor, operation):
    source = _source_job()
    with pytest.raises(ValueError):
        store.create_artifact_job(
            source["id"],
            0,
            processor,
            operation,
        )
