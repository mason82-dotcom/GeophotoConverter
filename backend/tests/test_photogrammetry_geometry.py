from __future__ import annotations

import pytest

from app.metadata import _normalize_metadata
from app.photogrammetry_geometry import (
    estimate_nadir_geometry,
    estimate_pair_overlap,
)


def _metadata():
    return {
        "image": {
            "width": 5280,
            "height": 3956,
            "focal_length": 12.3,
            "focal_length_35mm": 24.0,
        }
    }


def _photogrammetry():
    return {
        "position": {
            "latitude_deg": 49.25,
            "longitude_deg": 8.5,
        },
        "height": {
            "ellipsoid_m": 220.0,
            "relative_m": 80.0,
            "gps_altitude_m": None,
        },
        "orientation": {
            "aircraft_yaw_deg": 0.0,
            "gimbal_yaw_deg": 0.0,
            "gimbal_pitch_deg": -90.0,
        },
    }


def test_metadata_normalizes_35mm_equivalent_focal_length():
    result = _normalize_metadata({
        "File:ImageWidth": 5280,
        "File:ImageHeight": 3956,
        "ExifIFD:FocalLength": 12.3,
        "ExifIFD:FocalLengthIn35mmFormat": 24,
    })

    assert result["image"]["focal_length"] == 12.3
    assert result["image"]["focal_length_35mm"] == 24


def test_nadir_geometry_estimates_sensor_footprint_and_gsd():
    result = estimate_nadir_geometry(_metadata(), _photogrammetry())

    assert result["status"] == "ready"
    assert result["method"] == "exif_35mm_equivalent"
    assert result["confidence"] == "estimated"
    assert result["height_reference"] == "relative_takeoff"
    assert result["sensor"]["width_mm"] > result["sensor"]["height_mm"] > 0
    assert result["footprint"]["width_m"] > result["footprint"]["height_m"] > 0
    assert result["gsd"]["x_cm_per_px"] == pytest.approx(
        result["gsd"]["y_cm_per_px"],
        rel=1e-9,
    )


def test_geometry_is_unavailable_without_35mm_equivalent():
    metadata = _metadata()
    metadata["image"]["focal_length_35mm"] = None

    result = estimate_nadir_geometry(metadata, _photogrammetry())

    assert result["status"] == "unavailable"
    assert result["reason"] == "camera_geometry_missing"
    assert "image.focal_length_35mm" in result["missing"]


def test_geometry_is_unavailable_for_oblique_capture():
    photogrammetry = _photogrammetry()
    photogrammetry["orientation"]["gimbal_pitch_deg"] = -50.0

    result = estimate_nadir_geometry(_metadata(), photogrammetry)

    assert result["status"] == "unavailable"
    assert result["reason"] == "gimbal_not_nadir"
    assert result["nadir_deviation_deg"] == 40.0


def test_relative_height_is_not_replaced_by_absolute_height():
    photogrammetry = _photogrammetry()
    photogrammetry["height"]["relative_m"] = None
    photogrammetry["height"]["ellipsoid_m"] = 300.0

    result = estimate_nadir_geometry(_metadata(), photogrammetry)

    assert result["status"] == "unavailable"
    assert result["reason"] == "relative_height_missing"


def test_pair_overlap_uses_projected_baseline_and_heading():
    left = _photogrammetry()
    left["geometry"] = estimate_nadir_geometry(_metadata(), left)

    right = _photogrammetry()
    right["position"] = {
        "latitude_deg": 49.2501,
        "longitude_deg": 8.5,
    }

    result = estimate_pair_overlap(left, right, "EPSG:32632")

    assert result["status"] == "ready"
    assert result["heading_source"] == "gimbal_yaw_deg"
    assert result["along_track_m"] > 10.0
    assert abs(result["cross_track_m"]) < 1.0
    assert 0.0 < result["forward_overlap"] < 1.0
    assert result["side_overlap"] > 0.95


def test_pair_overlap_without_geometry_is_unavailable():
    left = _photogrammetry()
    right = _photogrammetry()
    right["position"] = {
        "latitude_deg": 49.2501,
        "longitude_deg": 8.5,
    }

    result = estimate_pair_overlap(left, right, "EPSG:32632")

    assert result == {
        "status": "unavailable",
        "reason": "left_geometry_unavailable",
    }
