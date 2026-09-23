from __future__ import annotations

from copy import deepcopy

import pytest

from app.mapping_geometry import (
    estimate_capture_geometry,
    evaluate_mapping_geometry,
)
from app.mapping_readiness import evaluate_mapping_readiness


def _metadata(
    *,
    latitude: float = 49.0,
    longitude: float = 8.0,
    capture_time: str = "2026-09-23T12:00:00Z",
    focal_length: float | None = 10.0,
    focal_length_35mm: float | None = 20.0,
    gimbal_pitch: float | None = -90.0,
    gimbal_yaw: float | None = 0.0,
    flight_yaw: float | None = 0.0,
    relative_altitude: float | None = 100.0,
) -> dict:
    image = {
        "width": 4000,
        "height": 3000,
    }
    if focal_length is not None:
        image["focal_length"] = focal_length
    if focal_length_35mm is not None:
        image["focal_length_35mm"] = focal_length_35mm

    dji: dict[str, float] = {
        "flight_pitch": 0.0,
        "flight_roll": 0.0,
        "gimbal_roll": 0.0,
    }
    if flight_yaw is not None:
        dji["flight_yaw"] = flight_yaw
    if gimbal_pitch is not None:
        dji["gimbal_pitch"] = gimbal_pitch
    if gimbal_yaw is not None:
        dji["gimbal_yaw"] = gimbal_yaw
    if relative_altitude is not None:
        dji["relative_altitude"] = relative_altitude

    return {
        "capture_time": capture_time,
        "image": image,
        "gps": {
            "latitude": latitude,
            "longitude": longitude,
        },
        "dji": dji,
    }


def test_capture_geometry_estimates_sensor_footprint_and_gsd() -> None:
    geometry = estimate_capture_geometry(_metadata())

    assert geometry["status"] == "available"
    assert geometry["method"] == "exif_35mm_equivalent"
    assert geometry["height_reference"] == "relative_takeoff"
    assert geometry["confidence"] == "estimated"

    assert geometry["sensor_width_mm"] == pytest.approx(17.306646, abs=1e-6)
    assert geometry["sensor_height_mm"] == pytest.approx(12.979984, abs=1e-6)
    assert geometry["footprint_width_m"] == pytest.approx(173.066461, abs=1e-5)
    assert geometry["footprint_height_m"] == pytest.approx(129.799846, abs=1e-5)
    assert geometry["gsd_x_cm_px"] == pytest.approx(4.326662, abs=1e-6)
    assert geometry["gsd_y_cm_px"] == pytest.approx(4.326662, abs=1e-6)
    assert geometry["gsd_cm_px"] == pytest.approx(4.326662, abs=1e-6)


def test_capture_geometry_is_unavailable_without_35mm_equivalent() -> None:
    geometry = estimate_capture_geometry(
        _metadata(focal_length_35mm=None)
    )

    assert geometry["status"] == "unavailable"
    assert "missing_focal_length_35mm" in geometry["reasons"]


def test_capture_geometry_is_unavailable_for_oblique_image() -> None:
    geometry = estimate_capture_geometry(
        _metadata(gimbal_pitch=-55.0)
    )

    assert geometry["status"] == "unavailable"
    assert geometry["reasons"] == ["oblique_gimbal"]


def test_sequential_overlap_decomposes_along_and_cross_track() -> None:
    north_delta_deg = 20.0 / 6_371_008.8 * 180.0 / 3.141592653589793
    files = [
        {
            "relative_path": "M3E/DJI_0001_D.JPG",
            "metadata": _metadata(
                latitude=49.0,
                longitude=8.0,
                capture_time="2026-09-23T12:00:00Z",
                gimbal_yaw=0.0,
            ),
        },
        {
            "relative_path": "M3E/DJI_0002_D.JPG",
            "metadata": _metadata(
                latitude=49.0 + north_delta_deg,
                longitude=8.0,
                capture_time="2026-09-23T12:00:01Z",
                gimbal_yaw=0.0,
            ),
        },
    ]

    result = evaluate_mapping_geometry(files)

    assert result["status"] == "available"
    assert result["available_images"] == 2
    assert result["overlap"]["status"] == "available"
    assert result["overlap"]["pair_count"] == 1

    pair = result["overlap"]["pairs"][0]
    assert pair["north_m"] == pytest.approx(20.0, abs=0.01)
    assert pair["east_m"] == pytest.approx(0.0, abs=0.01)
    assert pair["along_track_m"] == pytest.approx(20.0, abs=0.01)
    assert pair["cross_track_m"] == pytest.approx(0.0, abs=0.01)
    assert pair["forward_overlap_percent"] == pytest.approx(84.592, abs=0.01)
    assert pair["side_overlap_percent"] == pytest.approx(100.0, abs=0.01)


def test_overlap_is_unavailable_without_required_sequence_context() -> None:
    result = evaluate_mapping_geometry(
        [
            {
                "relative_path": "M3E/DJI_0101_D.JPG",
                "metadata": _metadata(
                    capture_time="",
                    gimbal_yaw=None,
                    flight_yaw=None,
                ),
            },
            {
                "relative_path": "M3E/DJI_0102_D.JPG",
                "metadata": _metadata(
                    capture_time="",
                    gimbal_yaw=None,
                ),
            },
        ]
    )

    assert result["available_images"] == 2
    assert result["overlap"]["status"] == "unavailable"
    assert "missing_heading" in result["overlap"]["reasons"]
    assert "missing_capture_time" in result["overlap"]["reasons"]


def test_geometry_does_not_mutate_metadata() -> None:
    metadata = _metadata()
    before = deepcopy(metadata)

    estimate_capture_geometry(metadata)

    assert metadata == before



def test_mapping_readiness_exposes_geometry_diagnostics() -> None:
    files = [
        {
            "relative_path": "M3E/DJI_0201_D.JPG",
            "metadata": _metadata(),
            "scan_error": None,
        },
        {
            "relative_path": "M3E/DJI_0202_D.JPG",
            "metadata": _metadata(
                latitude=49.0001,
                capture_time="2026-09-23T12:00:01Z",
            ),
            "scan_error": None,
        },
    ]

    result = evaluate_mapping_readiness(files)

    assert result["ready"] is True
    assert result["geometry"]["status"] == "available"
    assert result["geometry"]["available_images"] == 2
    assert result["geometry"]["overlap"]["pair_count"] == 1
