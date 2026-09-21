from __future__ import annotations

from pathlib import Path

import pytest

from app import dronedb
from app.config import DATA_ROOT
from app.storage import store


class FakeDroneDBClient:
    calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def authenticate(self):
        self.calls.append(("authenticate",))

    def ensure_organization(self, org_slug):
        self.calls.append(("org", org_slug))

    def ensure_dataset(self, org_slug, ds_slug, name):
        self.calls.append(("dataset", org_slug, ds_slug, name))

    def upload_bytes(self, org_slug, ds_slug, remote_path, filename, payload, content_type):
        self.calls.append(("bytes", remote_path, filename, content_type, len(payload)))

    def upload_file(self, org_slug, ds_slug, remote_path, path):
        self.calls.append(("file", remote_path, Path(path).name))

    def trigger_build(self, org_slug, ds_slug):
        self.calls.append(("build", org_slug, ds_slug))


def _completed_job():
    dataset = store.create_dataset("Survey Result", "result test")
    job = store.create_job(dataset["id"], "odm", "preview", "rgb", {})
    artifact = DATA_ROOT / "jobs" / job["id"] / "project" / "orthophoto.tif"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"geotiff")
    store.update_job(
        job["id"],
        status="completed",
        progress=100,
        artifacts=[
            {
                "type": "orthophoto",
                "name": "orthophoto.tif",
                "relative_path": artifact.relative_to(DATA_ROOT).as_posix(),
                "size_bytes": artifact.stat().st_size,
            }
        ],
    )
    return store.get_job(job["id"])


def test_dronedb_publish_is_persisted_and_idempotent(monkeypatch):
    FakeDroneDBClient.calls = []
    monkeypatch.setattr(dronedb, "DroneDBClient", FakeDroneDBClient)
    job = _completed_job()

    first = dronedb.publish_job(job["id"], "Mapped Site")
    assert first["status"] == "published"
    assert first["dataset_slug"].startswith("mapped-site-")
    assert first["artifact_count"] == 1
    assert ("authenticate",) in FakeDroneDBClient.calls
    assert any(call[0] == "file" for call in FakeDroneDBClient.calls)
    assert any(call[0] == "build" for call in FakeDroneDBClient.calls)

    call_count = len(FakeDroneDBClient.calls)
    second = dronedb.publish_job(job["id"], "Other Name")
    assert second == first
    assert len(FakeDroneDBClient.calls) == call_count
    assert store.get_job(job["id"])["publication"] == first


def test_dronedb_publish_rejects_non_completed_job():
    dataset = store.create_dataset("Queued", None)
    job = store.create_job(dataset["id"], "odm", "preview")
    with pytest.raises(Exception) as exc:
        dronedb.publish_job(job["id"])
    assert getattr(exc.value, "status_code", None) == 409
