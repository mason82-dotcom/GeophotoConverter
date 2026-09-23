from __future__ import annotations

from app.mapping_readiness import evaluate_mapping_readiness


def _mapping_file(
    path: str,
    *,
    latitude: object = 49.1,
    longitude: object = 8.5,
    model: str = "M3E",
    width: int = 5280,
    height: int = 3956,
    focal_length: float = 12.3,
    absolute_altitude: float = 220.0,
    relative_altitude: float = 80.0,
    gimbal_pitch: float = -90.0,
    capture_time: str = "2026:09:23 12:00:00",
    rtk_flag: int | None = 50,
    scan_error: str | None = None,
) -> dict:
    return {
        "relative_path": path,
        "metadata": {
            "capture_time": capture_time,
            "camera": {"make": "DJI", "model": model},
            "image": {
                "width": width,
                "height": height,
                "focal_length": focal_length,
            },
            "gps": {
                "latitude": latitude,
                "longitude": longitude,
                "altitude": absolute_altitude,
            },
            "dji": {
                "absolute_altitude": absolute_altitude,
                "relative_altitude": relative_altitude,
                "flight_yaw": 0.0,
                "flight_pitch": 0.0,
                "flight_roll": 0.0,
                "gimbal_yaw": 0.0,
                "gimbal_pitch": gimbal_pitch,
                "gimbal_roll": 0.0,
                "rtk_flag": rtk_flag,
                "rtk_fixed": rtk_flag == 50 if rtk_flag is not None else None,
            },
        },
        "scan_error": scan_error,
    }


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["issues"]}


def test_clean_mapping_metadata_is_ready():
    files = [
        _mapping_file(
            "DJI_0001.JPG",
            latitude=49.1,
            longitude=8.5,
            capture_time="2026:09:23 12:00:00",
        ),
        _mapping_file(
            "DJI_0002.JPG",
            latitude=49.1002,
            longitude=8.5002,
            capture_time="2026:09:23 12:00:01",
        ),
    ]

    result = evaluate_mapping_readiness(files)

    assert result["ready"] is True
    assert result["status"] == "ready"
    assert result["reason"] is None
    assert result["geotagged_images"] == 2
    assert result["unique_positions"] == 2
    assert result["position_extent_m"] > 0.5
    assert result["rtk_fixed_images"] == 2
    assert result["orientation_metadata_images"] == 2
    assert result["orientation"]["near_nadir_images"] == 2
    assert result["issues"] == []


def test_too_few_images_is_hard_block():
    result = evaluate_mapping_readiness([_mapping_file("DJI_0001.JPG")])

    assert result["ready"] is False
    assert result["status"] == "blocked"
    assert "MAPPING_TOO_FEW_IMAGES" in _codes(result)


def test_missing_invalid_and_degenerate_gps_are_distinguished():
    files = [
        _mapping_file("DJI_1001.JPG", latitude=49.1, longitude=8.5),
        _mapping_file("DJI_1002.JPG", latitude=49.1, longitude=8.5),
        _mapping_file("DJI_1003.JPG", latitude=None, longitude=None),
        _mapping_file("DJI_1004.JPG", latitude=999, longitude=8.5),
    ]

    result = evaluate_mapping_readiness(files)

    assert result["ready"] is True
    assert result["status"] == "warning"
    assert result["missing_gps"] == 1
    assert result["invalid_gps"] == 1
    assert result["geotagged_images"] == 2
    assert result["unique_positions"] == 1
    assert result["duplicate_position_images"] == 1
    assert result["position_extent_m"] == 0.0

    codes = _codes(result)
    assert "MAPPING_MISSING_GPS" in codes
    assert "MAPPING_INVALID_GPS" in codes
    assert "MAPPING_DUPLICATE_POSITIONS" in codes
    assert "MAPPING_SPATIAL_DEGENERATE" in codes


def test_camera_focal_and_dimension_variation_are_reported():
    files = [
        _mapping_file(
            "DJI_2001.JPG",
            latitude=49.1,
            longitude=8.5,
            model="M3E",
            width=5280,
            height=3956,
            focal_length=12.0,
        ),
        _mapping_file(
            "DJI_2002.JPG",
            latitude=49.1002,
            longitude=8.5002,
            model="M3T",
            width=4000,
            height=3000,
            focal_length=24.0,
        ),
    ]

    result = evaluate_mapping_readiness(files)

    codes = _codes(result)
    assert "MAPPING_MIXED_CAMERAS" in codes
    assert "MAPPING_MIXED_IMAGE_DIMENSIONS" in codes
    assert "MAPPING_FOCAL_LENGTH_VARIATION" in codes
    assert result["camera"]["model_count"] == 2
    assert result["camera"]["dimension_variants"] == 2
    assert result["camera"]["focal_length_mm"]["spread_percent"] > 2.0


def test_height_and_oblique_geometry_warnings_are_reported():
    files = [
        _mapping_file(
            "DJI_3001.JPG",
            latitude=49.1,
            longitude=8.5,
            absolute_altitude=220.0,
            relative_altitude=80.0,
            gimbal_pitch=-90.0,
        ),
        _mapping_file(
            "DJI_3002.JPG",
            latitude=49.1002,
            longitude=8.5002,
            absolute_altitude=240.0,
            relative_altitude=80.0,
            gimbal_pitch=-40.0,
        ),
        _mapping_file(
            "DJI_3003.JPG",
            latitude=49.1004,
            longitude=8.5004,
            absolute_altitude=221.0,
            relative_altitude=-1.0,
            gimbal_pitch=-70.0,
        ),
    ]

    result = evaluate_mapping_readiness(files)

    codes = _codes(result)
    assert "MAPPING_HEIGHT_OFFSET_VARIATION" in codes
    assert "MAPPING_NONPOSITIVE_RELATIVE_ALTITUDE" in codes
    assert "MAPPING_OBLIQUE_GIMBAL" in codes
    assert result["altitude_consistency"]["takeoff_offset_spread_m"] > 2.0
    assert result["altitude_consistency"]["nonpositive_relative_altitudes"] == 1
    assert result["orientation"]["oblique_images"] == 1
    assert result["orientation"]["strongly_oblique_images"] == 1


def test_optional_metadata_absence_is_info_only():
    first = _mapping_file(
        "DJI_4001.JPG",
        latitude=49.1,
        longitude=8.5,
        rtk_flag=None,
    )
    second = _mapping_file(
        "DJI_4002.JPG",
        latitude=49.1002,
        longitude=8.5002,
        rtk_flag=None,
    )
    for item in (first, second):
        item["metadata"]["capture_time"] = None
        item["metadata"]["dji"].update(
            {
                "flight_yaw": None,
                "flight_pitch": None,
                "flight_roll": None,
                "gimbal_yaw": None,
                "gimbal_pitch": None,
                "gimbal_roll": None,
            }
        )

    result = evaluate_mapping_readiness([first, second])

    assert result["ready"] is True
    assert result["status"] == "ready"
    assert result["reason"] is None
    issues = {item["code"]: item for item in result["issues"]}
    assert issues["MAPPING_RTK_UNAVAILABLE"]["severity"] == "info"
    assert issues["MAPPING_INCOMPLETE_ORIENTATION"]["severity"] == "info"
    assert issues["MAPPING_MISSING_CAPTURE_TIME"]["severity"] == "info"


def test_duplicate_capture_times_and_metadata_errors_warn():
    files = [
        _mapping_file(
            "DJI_5001.JPG",
            latitude=49.1,
            longitude=8.5,
            capture_time="2026:09:23 12:00:00",
        ),
        _mapping_file(
            "DJI_5002.JPG",
            latitude=49.1002,
            longitude=8.5002,
            capture_time="2026:09:23 12:00:00",
            scan_error="metadata decode failed",
        ),
    ]

    result = evaluate_mapping_readiness(files)

    assert result["capture_time"]["duplicate_count"] == 1
    assert result["metadata_errors"] == 1
    codes = _codes(result)
    assert "MAPPING_DUPLICATE_CAPTURE_TIME" in codes
    assert "MAPPING_METADATA_ERRORS" in codes
    assert result["status"] == "warning"
