from __future__ import annotations

from app.qa import dataset_qa


def _mapping_file(
    index: int,
    *,
    latitude: float | None,
    longitude: float | None,
    camera_model: str | None = "Mavic 3 Enterprise",
    focal_length: float | None = 12.0,
    gimbal_pitch: float | None = -90.0,
    relative_altitude: float | None = 80.0,
    absolute_altitude: float | None = 180.0,
    capture_time: str | None = None,
) -> dict:
    camera = {"make": "DJI"}
    if camera_model is not None:
        camera["model"] = camera_model

    image: dict[str, float] = {}
    if focal_length is not None:
        image["focal_length"] = focal_length

    gps: dict[str, float] = {}
    if latitude is not None:
        gps["latitude"] = latitude
    if longitude is not None:
        gps["longitude"] = longitude

    dji: dict[str, float | int | bool | str] = {
        "rtk_flag": 50,
        "rtk_fixed": True,
        "flight_yaw": 0.0,
        "flight_pitch": 0.0,
        "flight_roll": 0.0,
        "gimbal_yaw": 0.0,
        "gimbal_roll": 0.0,
        "product_name": "Mavic 3 Enterprise",
    }
    if gimbal_pitch is not None:
        dji["gimbal_pitch"] = gimbal_pitch
    if relative_altitude is not None:
        dji["relative_altitude"] = relative_altitude
    if absolute_altitude is not None:
        dji["absolute_altitude"] = absolute_altitude

    metadata = {
        "camera": camera,
        "image": image,
        "gps": gps,
        "dji": dji,
    }
    if capture_time is not None:
        metadata["capture_time"] = capture_time

    return {
        "relative_path": f"M3E/DJI_{index:04d}_D.JPG",
        "metadata": metadata,
        "scan_error": None,
    }


def test_mapping_readiness_checks_pass_for_consistent_dataset() -> None:
    files = [
        _mapping_file(
            1,
            latitude=49.1000,
            longitude=8.5000,
            relative_altitude=80.0,
            absolute_altitude=180.0,
            capture_time="2026-09-23T12:00:00",
        ),
        _mapping_file(
            2,
            latitude=49.1001,
            longitude=8.5001,
            relative_altitude=81.0,
            absolute_altitude=181.0,
            capture_time="2026-09-23T12:00:01",
        ),
        _mapping_file(
            3,
            latitude=49.1002,
            longitude=8.5002,
            relative_altitude=80.5,
            absolute_altitude=180.5,
            capture_time="2026-09-23T12:00:02",
        ),
    ]

    mapping = dataset_qa(files)["mapping"]

    assert mapping["ready"] is True
    assert mapping["status"] == "ready"
    assert mapping["reasons"] == []

    checks = mapping["checks"]
    assert checks["gps_distribution"]["status"] == "pass"
    assert checks["gps_distribution"]["unique_positions"] == 3
    assert checks["camera_consistency"]["status"] == "pass"
    assert checks["focal_length_consistency"]["status"] == "pass"
    assert checks["gimbal_nadir"]["status"] == "pass"
    assert checks["capture_time"]["status"] == "pass"
    assert checks["relative_altitude"]["status"] == "pass"
    assert checks["absolute_altitude"]["status"] == "pass"
    assert checks["altitude_offset_consistency"]["status"] == "pass"


def test_mapping_readiness_warns_on_degenerate_and_mixed_dataset() -> None:
    files = [
        _mapping_file(
            1,
            latitude=49.1,
            longitude=8.5,
            camera_model="Mavic 3 Enterprise",
            focal_length=12.0,
            gimbal_pitch=-45.0,
            relative_altitude=50.0,
            absolute_altitude=150.0,
            capture_time="2026-09-23T12:00:00",
        ),
        _mapping_file(
            2,
            latitude=49.1,
            longitude=8.5,
            camera_model="Mavic 3 Enterprise",
            focal_length=24.0,
            gimbal_pitch=-45.0,
            relative_altitude=100.0,
            absolute_altitude=300.0,
            capture_time="2026-09-23T12:00:00",
        ),
        _mapping_file(
            3,
            latitude=49.1,
            longitude=8.5,
            camera_model="Mavic 3 Thermal",
            focal_length=24.0,
            gimbal_pitch=-45.0,
            relative_altitude=150.0,
            absolute_altitude=450.0,
            capture_time="2026-09-23T12:00:00",
        ),
    ]

    mapping = dataset_qa(files)["mapping"]

    assert mapping["ready"] is True
    assert mapping["status"] == "warning"

    checks = mapping["checks"]
    assert checks["gps_distribution"]["status"] == "warning"
    assert checks["camera_consistency"]["status"] == "warning"
    assert checks["focal_length_consistency"]["status"] == "warning"
    assert checks["gimbal_nadir"]["status"] == "warning"
    assert checks["capture_time"]["status"] == "warning"
    assert checks["relative_altitude"]["status"] == "warning"
    assert checks["absolute_altitude"]["status"] == "warning"
    assert checks["altitude_offset_consistency"]["status"] == "warning"

    reason_codes = {item["code"] for item in mapping["reasons"]}
    assert {
        "MAPPING_GPS_DEGENERATE",
        "MAPPING_MIXED_CAMERAS",
        "MAPPING_FOCAL_LENGTH_VARIATION",
        "MAPPING_NON_NADIR",
        "MAPPING_CAPTURE_TIME_INCONSISTENT",
        "MAPPING_RELATIVE_ALTITUDE_VARIATION",
        "MAPPING_ABSOLUTE_ALTITUDE_VARIATION",
        "MAPPING_ALTITUDE_OFFSET_INCONSISTENT",
    }.issubset(reason_codes)


def test_mapping_readiness_reports_unknown_without_inventing_metrics() -> None:
    files = [
        _mapping_file(
            1,
            latitude=None,
            longitude=None,
            camera_model=None,
            focal_length=None,
            gimbal_pitch=None,
            relative_altitude=None,
            absolute_altitude=None,
            capture_time=None,
        ),
        _mapping_file(
            2,
            latitude=None,
            longitude=None,
            camera_model=None,
            focal_length=None,
            gimbal_pitch=None,
            relative_altitude=None,
            absolute_altitude=None,
            capture_time=None,
        ),
    ]

    mapping = dataset_qa(files)["mapping"]

    assert mapping["ready"] is True
    assert mapping["status"] == "warning"
    assert mapping["missing_gps"] == 2

    checks = mapping["checks"]
    assert checks["gps_distribution"]["status"] == "unknown"
    assert checks["camera_consistency"]["status"] == "unknown"
    assert checks["focal_length_consistency"]["status"] == "unknown"
    assert checks["gimbal_nadir"]["status"] == "unknown"
    assert checks["capture_time"]["status"] == "unknown"
    assert checks["relative_altitude"]["status"] == "unknown"
    assert checks["absolute_altitude"]["status"] == "unknown"
    assert checks["altitude_offset_consistency"]["status"] == "unknown"

    assert mapping["reasons"][0]["code"] == "MAPPING_GPS_INCOMPLETE"
