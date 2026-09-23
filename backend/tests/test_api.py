from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.config import DATA_ROOT
from app.main import JobCreate, _canonical_workflow
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
    assert rejected[0]["reason"] == "Datei ist ein Duplikat"
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


def test_job_readiness_ignores_thermal_images(client):
    dataset = _dataset(client)
    for index in range(3):
        response = client.post(
            f"/api/v1/datasets/{dataset['id']}/files",
            files=[
                (
                    "files",
                    (f"DJI_000{index}_T.JPG", f"thermal-{index}".encode(), "image/jpeg"),
                )
            ],
            data={
                "relative_paths": json.dumps(
                    [f"M3T/DJI_000{index}_T.JPG"]
                )
            },
        )
        assert response.status_code == 200

    qa = client.get(f"/api/v1/datasets/{dataset['id']}/qa")
    assert qa.status_code == 200
    assert qa.json()["engine_inputs"]["thermal"] == 3
    assert qa.json()["engine_inputs"]["rgb_wide"] == 0
    assert qa.json()["readiness"]["odm"]["ready"] is False

    job = client.post(
        "/api/v1/jobs",
        json={
            "dataset_id": dataset["id"],
            "engine": "odm",
            "profile": "preview",
        },
    )
    assert job.status_code == 409
    assert job.json()["detail"]["eligible_images"] == 0


def test_job_readiness_counts_dng_rgb_inputs(client):
    dataset = _dataset(client)
    for index in range(3):
        response = client.post(
            f"/api/v1/datasets/{dataset['id']}/files",
            files=[
                (
                    "files",
                    (f"DJI_100{index}_D.DNG", f"dng-{index}".encode(), "image/dng"),
                )
            ],
        )
        assert response.status_code == 200

    qa = client.get(f"/api/v1/datasets/{dataset['id']}/qa")
    assert qa.status_code == 200
    body = qa.json()
    assert body["engine_inputs"]["rgb_wide"] == 3
    assert body["readiness"]["micmac"]["ready"] is True
    assert body["readiness"]["gsplat"]["ready"] is True


def test_m3m_multispectral_readiness_requires_complete_groups(client):
    dataset = _dataset(client)
    suffixes = [
        ("D.JPG", "image/jpeg"),
        ("MS_G.TIF", "image/tiff"),
        ("MS_R.TIF", "image/tiff"),
        ("MS_RE.TIF", "image/tiff"),
        ("MS_NIR.TIF", "image/tiff"),
    ]

    for capture in ("DJI_2001", "DJI_2002"):
        for index, (suffix, media_type) in enumerate(suffixes):
            name = f"{capture}_{suffix}"
            response = client.post(
                f"/api/v1/datasets/{dataset['id']}/files",
                files=[
                    (
                        "files",
                        (
                            name,
                            f"{capture}-{index}".encode(),
                            media_type,
                        ),
                    )
                ],
                data={"relative_paths": json.dumps([f"M3M/{name}"])},
            )
            assert response.status_code == 200

    qa = client.get(f"/api/v1/datasets/{dataset['id']}/qa")
    assert qa.status_code == 200
    body = qa.json()
    assert body["multispectral"]["complete_groups"] == 2
    assert body["readiness"]["odm_multispectral"]["ready"] is True
    assert body["readiness"]["odm_multispectral"]["eligible_images"] == 10


def test_m3m_band_conflict_blocks_multispectral_readiness(client):
    dataset = _dataset(client)
    suffixes = [
        ("D.JPG", "image/jpeg"),
        ("MS_G.TIF", "image/tiff"),
        ("MS_R.TIF", "image/tiff"),
        ("MS_RE.TIF", "image/tiff"),
        ("MS_NIR.TIF", "image/tiff"),
    ]

    for capture in ("DJI_6101", "DJI_6102"):
        for index, (suffix, media_type) in enumerate(suffixes):
            name = f"{capture}_{suffix}"
            response = client.post(
                f"/api/v1/datasets/{dataset['id']}/files",
                files=[
                    (
                        "files",
                        (
                            name,
                            f"{capture}-{index}".encode(),
                            media_type,
                        ),
                    )
                ],
                data={"relative_paths": json.dumps([f"M3M/{name}"])},
            )
            assert response.status_code == 200

    conflict_name = "DJI_6101_MS_G.TIFF"
    conflict_upload = client.post(
        f"/api/v1/datasets/{dataset['id']}/files",
        files=[
            (
                "files",
                (conflict_name, b"conflicting-green-copy", "image/tiff"),
            )
        ],
        data={"relative_paths": json.dumps([f"M3M/{conflict_name}"])},
    )
    assert conflict_upload.status_code == 200
    conflict_file_id = conflict_upload.json()["accepted"][0]["id"]
    store.update_file_scan(
        conflict_file_id,
        {
            "camera": {"make": "DJI", "model": "Mavic 3 Multispectral"},
            "gps": {"latitude": 49.0, "longitude": 8.0},
            "dji": {
                "band_name": "Red",
                "product_name": "Mavic 3 Multispectral",
            },
        },
        None,
    )

    qa = client.get(f"/api/v1/datasets/{dataset['id']}/qa")
    assert qa.status_code == 200
    body = qa.json()
    assert body["multispectral"]["complete_groups"] == 2
    assert body["multispectral"]["conflict_file_count"] == 1
    assert body["multispectral"]["conflict_group_count"] == 1
    assert body["multispectral"]["conflict_groups"] == ["M3M/DJI_6101"]
    assert body["multispectral"]["classification_conflicts"] == {
        "band_metadata_filename_conflict": 1
    }
    assert body["readiness"]["odm_multispectral"]["ready"] is False
    assert body["readiness"]["odm_multispectral"]["classification_conflict_files"] == 1
    assert any(
        warning["code"] == "MULTISPECTRAL_CLASSIFICATION_CONFLICT"
        and warning["severity"] == "error"
        for warning in body["warnings"]
    )

    detail = client.get(f"/api/v1/datasets/{dataset['id']}")
    classifications = {
        item["relative_path"]: item["classification"]
        for item in detail.json()["files"]
    }
    assert classifications[f"M3M/{conflict_name}"]["conflicts"] == [
        "band_metadata_filename_conflict"
    ]


def test_m3m_multispectral_readiness_rejects_incomplete_groups(client):
    dataset = _dataset(client)
    for index, suffix in enumerate(("D.JPG", "MS_G.TIF", "MS_NIR.TIF")):
        name = f"DJI_3001_{suffix}"
        response = client.post(
            f"/api/v1/datasets/{dataset['id']}/files",
            files=[
                (
                    "files",
                    (name, f"incomplete-{index}".encode(), "image/jpeg"),
                )
            ],
            data={"relative_paths": json.dumps([f"M3M/{name}"])},
        )
        assert response.status_code == 200

    qa = client.get(f"/api/v1/datasets/{dataset['id']}/qa")
    assert qa.status_code == 200
    assert qa.json()["multispectral"]["complete_groups"] == 0
    assert qa.json()["readiness"]["odm_multispectral"]["ready"] is False


def test_thermal_readiness_requires_confirmed_wide_thermal_pairs(client):
    dataset = _dataset(client)
    for capture in ("DJI_4001", "DJI_4002"):
        for suffix, payload in (
            ("W.JPG", b"wide"),
            ("T.JPG", b"thermal"),
        ):
            name = f"{capture}_{suffix}"
            response = client.post(
                f"/api/v1/datasets/{dataset['id']}/files",
                files=[("files", (name, payload + capture.encode(), "image/jpeg"))],
                data={"relative_paths": json.dumps([f"M3T/{name}"])},
            )
            assert response.status_code == 200

    qa = client.get(f"/api/v1/datasets/{dataset['id']}/qa")
    assert qa.status_code == 200
    body = qa.json()
    assert body["thermal"]["complete_groups"] == 2
    assert body["thermal"]["platform"] == "M3T"
    assert body["readiness"]["thermal"]["ready"] is True
    assert body["readiness"]["thermal"]["eligible_images"] == 4


def test_thermal_readiness_rejects_unknown_platform(client):
    dataset = _dataset(client)
    for suffix, payload in (("W.JPG", b"wide"), ("T.JPG", b"thermal")):
        name = f"DJI_5001_{suffix}"
        response = client.post(
            f"/api/v1/datasets/{dataset['id']}/files",
            files=[("files", (name, payload, "image/jpeg"))],
        )
        assert response.status_code == 200

    qa = client.get(f"/api/v1/datasets/{dataset['id']}/qa")
    assert qa.status_code == 200
    assert qa.json()["thermal"]["complete_groups"] == 1
    assert qa.json()["thermal"]["platform"] is None
    assert qa.json()["readiness"]["thermal"]["ready"] is False


def test_processing_profile_catalog_exposes_specialized_workflows(client):
    response = client.get("/api/v1/processing/profiles")
    assert response.status_code == 200
    body = response.json()
    engines = {item["key"]: item for item in body["engines"]}

    odm_workflows = {
        item["key"]: item
        for item in engines["odm"]["workflows"]
    }
    assert "mapping" in odm_workflows
    assert odm_workflows["mapping"]["eligible_media_kinds"] == ["RGB", "WIDE"]
    assert odm_workflows["multispectral"]["platforms"] == ["M3M"]
    assert odm_workflows["multispectral"]["radiometric_calibration"] == "camera"

    thermal = engines["thermal"]
    assert thermal["requires_dji_tsdk"] is True
    thermal_workflow = thermal["workflows"][0]
    assert thermal_workflow["temperature_space"] == "sensor_pixel"
    assert thermal_workflow["wide_thermal_coregistered"] is False

    micmac_workflows = {
        item["key"]: item
        for item in engines["micmac"]["workflows"]
    }
    gsplat_workflows = {
        item["key"]: item
        for item in engines["gsplat"]["workflows"]
    }
    assert "mapping" in micmac_workflows
    assert "reconstruction" in gsplat_workflows
    assert engines["gsplat"]["requires_gpu"] is True
    assert engines["telesculptor"]["automated"] is False


def test_processing_catalog_user_text_is_german(client):
    response = client.get("/api/v1/processing/profiles")
    assert response.status_code == 200
    engines = {item["key"]: item for item in response.json()["engines"]}
    odm_workflows = {item["key"]: item for item in engines["odm"]["workflows"]}
    assert "Multispektral" in odm_workflows["multispectral"]["title"]
    assert "Schnelle Prüfung" in odm_workflows["mapping"]["profiles"]["preview"]["purpose"]
    assert "Thermografie" in engines["thermal"]["title"]



def test_legacy_rgb_workflow_is_canonicalized_by_engine():
    assert JobCreate(dataset_id="legacy", engine="gsplat").workflow == "rgb"
    assert _canonical_workflow("odm", "rgb") == "mapping"
    assert _canonical_workflow("micmac", "rgb") == "mapping"
    assert _canonical_workflow("gsplat", "rgb") == "reconstruction"
    assert _canonical_workflow("thermal", "thermal") == "thermal"


def test_mapping_qa_reports_gps_rtk_and_orientation_coverage(client):
    dataset = _dataset(client)
    file_ids = []
    for index in range(2):
        response = client.post(
            f"/api/v1/datasets/{dataset['id']}/files",
            files=[
                (
                    "files",
                    (f"DJI_700{index}.JPG", f"mapping-{index}".encode(), "image/jpeg"),
                )
            ],
        )
        assert response.status_code == 200
        file_ids.append(response.json()["accepted"][0]["id"])

    store.update_file_scan(
        file_ids[0],
        {
            "camera": {"make": "DJI", "model": "M3E"},
            "gps": {"latitude": 49.1, "longitude": 8.5, "altitude": 120.0},
            "dji": {
                "rtk_flag": 50,
                "rtk_fixed": True,
                "flight_yaw": 1.0,
                "flight_pitch": 2.0,
                "flight_roll": 3.0,
                "gimbal_yaw": 4.0,
                "gimbal_pitch": -90.0,
                "gimbal_roll": 0.0,
            },
        },
        None,
    )
    store.update_file_scan(
        file_ids[1],
        {
            "camera": {"make": "DJI", "model": "M3E"},
            "gps": {},
            "dji": {},
        },
        None,
    )

    response = client.get(f"/api/v1/datasets/{dataset['id']}/qa")
    assert response.status_code == 200
    mapping = response.json()["mapping"]
    assert mapping["ready"] is True
    assert mapping["status"] == "warning"
    assert mapping["minimum_images"] == 2
    assert mapping["eligible_images"] == 2
    assert mapping["geotagged_images"] == 1
    assert mapping["geotagged_percent"] == 50.0
    assert mapping["missing_gps"] == 1
    assert mapping["rtk_metadata_images"] == 1
    assert mapping["rtk_fixed_images"] == 1
    assert mapping["orientation_metadata_images"] == 1
