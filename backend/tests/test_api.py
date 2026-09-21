from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image

from app.config import DATA_ROOT
from app.storage import store


def _dataset(client, name: str = "Test Survey") -> dict:
    response = client.post("/api/v1/datasets", json={"name": name})
    assert response.status_code == 201
    return response.json()


def test_upload_is_hashed_and_duplicate_is_rejected(client):
    dataset = _dataset(client)
    payload = b"not-a-real-jpeg-but-valid-for-upload-path-testing"

    first = client.post(
        f"/api/v1/datasets/{dataset['id']}/files",
        files=[("files", ("DJI_0001.JPG", payload, "image/jpeg"))],
        data={"relative_paths": json.dumps(["flight-a/DJI_0001.JPG"])},
    )
    assert first.status_code == 200
    body = first.json()
    assert len(body["accepted"]) == 1
    assert body["accepted"][0]["sha256"] == hashlib.sha256(payload).hexdigest()

    second = client.post(
        f"/api/v1/datasets/{dataset['id']}/files",
        files=[("files", ("copy.JPG", payload, "image/jpeg"))],
    )
    assert second.status_code == 200
    rejected = second.json()["rejected"]
    assert rejected[0]["reason"] == "Doppelte Datei"
    assert rejected[0]["duplicate_of"] == "flight-a/DJI_0001.JPG"


def test_dataset_geojson_uses_scanned_gps(client):
    dataset = _dataset(client)
    upload = client.post(
        f"/api/v1/datasets/{dataset['id']}/files",
        files=[("files", ("DJI_0002.JPG", b"image", "image/jpeg"))],
    )
    file_id = upload.json()["accepted"][0]["id"]
    store.update_file_scan(
        file_id,
        {
            "capture_time": "2026:09:21 12:00:00",
            "camera": {"make": "DJI", "model": "M3E"},
            "gps": {"latitude": 49.123, "longitude": 8.456, "altitude": 120.5},
            "dji": {"gimbal_yaw": 12.3},
        },
        None,
    )

    response = client.get(f"/api/v1/datasets/{dataset['id']}/geojson")
    assert response.status_code == 200
    feature = response.json()["features"][0]
    assert feature["geometry"]["coordinates"] == [8.456, 49.123]
    assert feature["properties"]["altitude"] == 120.5


def test_job_logs_and_artifact_download(client):
    dataset = store.create_dataset("Results", None)
    job = store.create_job(dataset["id"], "odm", "preview")

    job_root = DATA_ROOT / "jobs" / job["id"]
    artifact = job_root / "project" / "result.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("artifact-data", encoding="utf-8")
    (job_root / "worker.log").write_text("one\ntwo\nthree\n", encoding="utf-8")

    store.update_job(
        job["id"],
        status="completed",
        progress=100,
        artifacts=[
            {
                "type": "test",
                "name": "result.txt",
                "relative_path": f"jobs/{job['id']}/project/result.txt",
                "size_bytes": artifact.stat().st_size,
            }
        ],
    )

    job_response = client.get(f"/api/v1/jobs/{job['id']}")
    assert job_response.status_code == 200
    download_url = job_response.json()["artifacts"][0]["download_url"]

    logs = client.get(f"/api/v1/jobs/{job['id']}/logs", params={"tail": 2})
    assert logs.status_code == 200
    assert logs.json()["lines"] == ["two", "three"]

    downloaded = client.get(download_url)
    assert downloaded.status_code == 200
    assert downloaded.content == b"artifact-data"


def test_unsafe_relative_path_falls_back_to_filename(client):
    dataset = _dataset(client)
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/files",
        files=[("files", ("safe.JPG", b"image", "image/jpeg"))],
        data={"relative_paths": json.dumps(["../outside.JPG"])},
    )
    assert response.status_code == 200
    accepted = response.json()["accepted"][0]
    assert accepted["relative_path"] == "safe.JPG"


def test_dataset_qa_classifies_multispectral_and_platform(client):
    dataset = _dataset(client)
    first = client.post(
        f"/api/v1/datasets/{dataset['id']}/files",
        files=[("files", ("DJI_0001_MS_NIR.TIF", b"nir", "image/tiff"))],
        data={"relative_paths": json.dumps(["M3M/DJI_0001_MS_NIR.TIF"])},
    )
    second = client.post(
        f"/api/v1/datasets/{dataset['id']}/files",
        files=[("files", ("DJI_0001_D.JPG", b"rgb", "image/jpeg"))],
        data={"relative_paths": json.dumps(["M3M/DJI_0001_D.JPG"])},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    for response in (first, second):
        file_id = response.json()["accepted"][0]["id"]
        store.update_file_scan(
            file_id,
            {
                "capture_time": "2026-09-21T12:00:00+00:00",
                "camera": {"make": "DJI", "model": "Mavic 3 Multispectral"},
                "gps": {"latitude": 49.0, "longitude": 8.0, "altitude": 130.0},
                "dji": {
                    "relative_altitude": 75.0,
                    "product_name": "Mavic 3 Multispectral",
                },
            },
            None,
        )

    qa = client.get(f"/api/v1/datasets/{dataset['id']}/qa")
    assert qa.status_code == 200
    body = qa.json()
    assert body["platforms"]["M3M"] == 2
    assert body["media_kinds"]["MS_NIR"] == 1
    assert body["media_kinds"]["RGB"] == 1
    assert body["geotagged_percent"] == 100.0
    assert body["altitude"]["relative_takeoff_m"]["min"] == 75.0

    detail = client.get(f"/api/v1/datasets/{dataset['id']}")
    assert detail.status_code == 200
    classifications = {
        item["relative_path"]: item["classification"]
        for item in detail.json()["files"]
    }
    assert classifications["M3M/DJI_0001_MS_NIR.TIF"]["platform"] == "M3M"


def test_dataset_detail_exposes_qa_summary_fields(client):
    dataset = _dataset(client)
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/files",
        files=[("files", ("DJI_0100.JPG", b"rgb", "image/jpeg"))],
    )
    file_id = response.json()["accepted"][0]["id"]
    store.update_file_scan(
        file_id,
        {
            "camera": {"make": "DJI", "model": "Mavic 3 Enterprise"},
            "gps": {"latitude": 49.0, "longitude": 8.0, "altitude": 110.0},
            "dji": {"product_name": "Mavic 3 Enterprise"},
        },
        None,
    )

    detail = client.get(f"/api/v1/datasets/{dataset['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["platform"] == "M3E"
    assert body["duplicate_count"] == 0
    assert body["processing_readiness"] == "Not ready"


def test_dataset_file_preview_returns_browser_jpeg(client):
    dataset = _dataset(client)
    source = io.BytesIO()
    Image.new("RGB", (64, 32), (40, 80, 120)).save(source, format="JPEG")

    upload = client.post(
        f"/api/v1/datasets/{dataset['id']}/files",
        files=[("files", ("DJI_0200.JPG", source.getvalue(), "image/jpeg"))],
    )
    file_id = upload.json()["accepted"][0]["id"]

    preview = client.get(
        f"/api/v1/datasets/{dataset['id']}/files/{file_id}/preview",
        params={"size": 128},
    )
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/jpeg")
    rendered = Image.open(io.BytesIO(preview.content))
    assert rendered.width <= 128
    assert rendered.height <= 128
