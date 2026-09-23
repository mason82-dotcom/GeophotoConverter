from __future__ import annotations

import app.main as main_module

from app.storage import store


def _dataset(client) -> dict:
    response = client.post(
        "/api/v1/datasets",
        json={"name": "FH2 Mapping"},
    )
    assert response.status_code == 201
    return response.json()


def _upload(client, dataset_id: str, name: str, payload: bytes) -> str:
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/files",
        files=[("files", (name, payload, "image/jpeg"))],
    )
    assert response.status_code == 200
    return response.json()["accepted"][0]["id"]


def _fh2_media(
    capture_uuid: str,
    latitude: float,
    longitude: float,
    *,
    rtk_fixed: bool = True,
) -> dict:
    return {
        "captureUuid": capture_uuid,
        "asset": {
            "capture": {
                "capturedAt": 1790164800123,
                "latitudeDeg": latitude,
                "longitudeDeg": longitude,
                "ellipsoidHeightM": 220.0,
                "relativeHeightM": 80.0,
                "aircraftYawDeg": 0.0,
                "aircraftPitchDeg": 0.0,
                "aircraftRollDeg": 0.0,
                "gimbalYawDeg": 0.0,
                "gimbalPitchDeg": -90.0,
                "gimbalRollDeg": 0.0,
                "rtkFixed": rtk_fixed,
            }
        },
        "sourceKeys": {
            "GpsLatitude": "XMP-drone-dji:GpsLatitude",
            "GpsLongitude": "XMP-drone-dji:GpsLongitude",
            "AbsoluteAltitude": "XMP-drone-dji:AbsoluteAltitude",
            "RelativeAltitude": "XMP-drone-dji:RelativeAltitude",
            "FlightYawDegree": "XMP-drone-dji:FlightYawDegree",
            "GimbalPitchDegree": "XMP-drone-dji:GimbalPitchDegree",
            "UTCAtExposure": "XMP-drone-dji:UTCAtExposure",
            "RtkFlag": "XMP-drone-dji:RtkFlag",
            "CaptureUUID": "XMP-drone-dji:CaptureUUID",
        },
    }


def _file_metadata(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict:
    return {
        "capture_time": "2026:09:23 12:00:00",
        "camera": {"make": "DJI", "model": "Mavic 3 Enterprise"},
        "image": {"width": 5280, "height": 3956, "focal_length": 12.3},
        "gps": {
            "latitude": latitude,
            "longitude": longitude,
            "altitude": 120.0,
        },
        "dji": {},
    }


def test_fh2_only_position_drives_mapping_qa_and_geojson(client):
    dataset = _dataset(client)
    file_ids = [
        _upload(client, dataset["id"], "DJI_9001.JPG", b"first"),
        _upload(client, dataset["id"], "DJI_9002.JPG", b"second"),
    ]
    for file_id in file_ids:
        store.update_file_scan(file_id, _file_metadata(), None)

    for file_id, capture_uuid, latitude, longitude in (
        (file_ids[0], "capture-a", 49.1000, 8.5000),
        (file_ids[1], "capture-b", 49.1003, 8.5003),
    ):
        response = client.put(
            f"/api/v1/datasets/{dataset['id']}/files/{file_id}/fh2-media",
            json={"media": _fh2_media(capture_uuid, latitude, longitude)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["photogrammetry"]["position"]["latitude_deg"] == latitude
        assert (
            body["photogrammetry"]["provenance"]["position.latitude_deg"]["source"]
            == "fh2_media"
        )

    qa_response = client.get(f"/api/v1/datasets/{dataset['id']}/qa")
    assert qa_response.status_code == 200
    mapping = qa_response.json()["mapping"]

    assert mapping["geotagged_images"] == 2
    assert mapping["missing_gps"] == 0
    assert mapping["invalid_gps"] == 0
    assert mapping["rtk_fixed_images"] == 2
    assert mapping["orientation_metadata_images"] == 2
    assert mapping["photogrammetry"]["fh2_enriched_images"] == 2
    assert mapping["photogrammetry"]["position_sources"] == {"fh2_media": 2}
    assert mapping["photogrammetry"]["ellipsoid_height_images"] == 2
    assert mapping["photogrammetry"]["relative_height_images"] == 2
    assert mapping["photogrammetry"]["capture_uuid_images"] == 2
    assert mapping["photogrammetry"]["fusion_conflict_count"] == 0

    detail = client.get(f"/api/v1/datasets/{dataset['id']}")
    assert detail.status_code == 200
    assert detail.json()["geotagged_count"] == 2
    assert detail.json()["geotagged_percent"] == 100.0

    geojson = client.get(f"/api/v1/datasets/{dataset['id']}/geojson")
    assert geojson.status_code == 200
    features = geojson.json()["features"]
    assert len(features) == 2
    assert features[0]["geometry"]["coordinates"] == [8.5, 49.1]
    assert features[0]["properties"]["capture_uuid"] == "capture-a"
    assert features[0]["properties"]["rtk_fixed"] is True


def test_fh2_file_metadata_conflict_is_visible_and_fh2_wins(client):
    dataset = _dataset(client)
    first = _upload(client, dataset["id"], "DJI_9101.JPG", b"first-conflict")
    second = _upload(client, dataset["id"], "DJI_9102.JPG", b"second-clean")

    store.update_file_scan(
        first,
        _file_metadata(latitude=49.0, longitude=8.5),
        None,
    )
    store.update_file_scan(
        second,
        _file_metadata(latitude=49.2, longitude=8.7),
        None,
    )

    response = client.put(
        f"/api/v1/datasets/{dataset['id']}/files/{first}/fh2-media",
        json={"media": _fh2_media("capture-conflict", 49.1, 8.5)},
    )
    assert response.status_code == 200
    fused = response.json()["photogrammetry"]
    assert fused["position"]["latitude_deg"] == 49.1
    assert any(
        conflict["field"] == "position.latitude_deg"
        and conflict["selected"]["source"] == "fh2_media"
        and conflict["other"]["source"] == "file_metadata"
        for conflict in fused["conflicts"]
    )

    qa = client.get(f"/api/v1/datasets/{dataset['id']}/qa")
    assert qa.status_code == 200
    mapping = qa.json()["mapping"]
    assert mapping["status"] == "warning"
    assert mapping["photogrammetry"]["fusion_conflict_files"] == 1
    assert mapping["photogrammetry"]["fusion_conflict_count"] == 1
    assert mapping["photogrammetry"]["fusion_conflict_fields"] == {
        "position.latitude_deg": 1
    }
    assert any(
        issue["code"] == "MAPPING_METADATA_FUSION_CONFLICT"
        and issue["severity"] == "warning"
        for issue in mapping["issues"]
    )

    geojson = client.get(f"/api/v1/datasets/{dataset['id']}/geojson")
    first_feature = next(
        item
        for item in geojson.json()["features"]
        if item["id"] == first
    )
    assert first_feature["geometry"]["coordinates"] == [8.5, 49.1]


def test_dataset_scan_preserves_fh2_media(client, monkeypatch):
    dataset = _dataset(client)
    file_id = _upload(client, dataset["id"], "DJI_9201.JPG", b"scan-preserve")
    fh2 = _fh2_media("capture-persisted", 49.3, 8.8)

    response = client.put(
        f"/api/v1/datasets/{dataset['id']}/files/{file_id}/fh2-media",
        json={"media": fh2},
    )
    assert response.status_code == 200

    monkeypatch.setattr(
        main_module,
        "read_metadata",
        lambda path: _file_metadata(latitude=49.31, longitude=8.81),
    )

    scan = client.post(f"/api/v1/datasets/{dataset['id']}/scan")
    assert scan.status_code == 200
    assert scan.json()["failed"] == 0

    detail = client.get(f"/api/v1/datasets/{dataset['id']}")
    file_record = detail.json()["files"][0]
    assert file_record["fh2_media"] == fh2
    assert file_record["photogrammetry"]["capture_uuid"] == "capture-persisted"
    assert (
        file_record["photogrammetry"]["provenance"]["position.latitude_deg"]["source"]
        == "fh2_media"
    )


def test_fh2_media_can_be_cleared_without_touching_file_metadata(client):
    dataset = _dataset(client)
    file_id = _upload(client, dataset["id"], "DJI_9301.JPG", b"clear-fh2")
    metadata = _file_metadata(latitude=49.4, longitude=8.9)
    store.update_file_scan(file_id, metadata, None)

    response = client.put(
        f"/api/v1/datasets/{dataset['id']}/files/{file_id}/fh2-media",
        json={"media": _fh2_media("capture-clear", 49.5, 9.0)},
    )
    assert response.status_code == 200

    cleared = client.put(
        f"/api/v1/datasets/{dataset['id']}/files/{file_id}/fh2-media",
        json={"media": None},
    )
    assert cleared.status_code == 200
    body = cleared.json()
    assert "fh2_media" not in body
    assert body["metadata"] == metadata
    assert body["photogrammetry"]["position"] == {
        "latitude_deg": 49.4,
        "longitude_deg": 8.9,
    }
