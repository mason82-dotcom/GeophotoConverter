from __future__ import annotations

import pytest

from app.photogrammetry_geo import (
    absolute_georeference_height,
    project_wgs84_positions,
    relative_geometry_height,
    suggest_projected_crs,
)


def test_suggest_projected_crs_selects_single_wgs84_utm_zone() -> None:
    result = suggest_projected_crs(
        [
            {"position": {"latitude_deg": 49.24, "longitude_deg": 8.48}},
            {"position": {"latitude_deg": 49.27, "longitude_deg": 8.55}},
        ]
    )

    assert result["status"] == "ready"
    assert result["crs"]["identifier"] == "EPSG:32632"
    assert result["crs"]["is_projected"] is True
    assert result["crs"]["axis_units"][:2] == ["metre", "metre"]


def test_suggest_projected_crs_blocks_dataset_crossing_utm_zones() -> None:
    result = suggest_projected_crs(
        [
            {"position": {"latitude_deg": 49.0, "longitude_deg": 5.9}},
            {"position": {"latitude_deg": 49.0, "longitude_deg": 6.1}},
        ]
    )

    assert result["status"] == "blocked"
    assert result["crs"] is None
    assert result["reason"] in {
        "no_single_utm_crs_contains_dataset",
        "projected_crs_ambiguous",
    }
    assert "EPSG:32631" in result["candidate_crs"]
    assert "EPSG:32632" in result["candidate_crs"]


def test_suggest_projected_crs_blocks_antimeridian_dataset() -> None:
    result = suggest_projected_crs(
        [
            {"position": {"latitude_deg": 10.0, "longitude_deg": 179.9}},
            {"position": {"latitude_deg": 10.0, "longitude_deg": -179.9}},
        ]
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "antimeridian_dataset_not_supported"


def test_suggest_projected_crs_ignores_invalid_positions() -> None:
    result = suggest_projected_crs(
        [
            {"position": {"latitude_deg": 999, "longitude_deg": 8.5}},
            {"position": {"latitude_deg": 49.25, "longitude_deg": 8.5}},
        ]
    )

    assert result["status"] == "ready"
    assert result["crs"]["identifier"] == "EPSG:32632"


def test_project_wgs84_positions_uses_traditional_xy_order() -> None:
    result = project_wgs84_positions(
        [{"position": {"latitude_deg": 0.0, "longitude_deg": 9.0}}],
        "EPSG:32632",
    )

    assert len(result) == 1
    assert result[0]["x_m"] == pytest.approx(500000.0, abs=0.01)
    assert result[0]["y_m"] == pytest.approx(0.0, abs=0.01)


def test_project_wgs84_positions_rejects_geographic_target() -> None:
    with pytest.raises(ValueError, match="projected"):
        project_wgs84_positions(
            [{"position": {"latitude_deg": 49.25, "longitude_deg": 8.5}}],
            "EPSG:4326",
        )


def test_absolute_height_accepts_only_explicit_ellipsoid_height() -> None:
    ready = absolute_georeference_height(
        {
            "height": {
                "ellipsoid_m": 221.4,
                "relative_m": 82.0,
                "gps_altitude_m": 130.0,
            }
        }
    )
    generic_only = absolute_georeference_height(
        {
            "height": {
                "ellipsoid_m": None,
                "relative_m": 82.0,
                "gps_altitude_m": 130.0,
            }
        }
    )

    assert ready == {
        "status": "ready",
        "value_m": 221.4,
        "reference": "wgs84_ellipsoidal",
        "source_field": "height.ellipsoid_m",
        "reason": None,
    }
    assert generic_only["status"] == "unavailable"
    assert generic_only["reason"] == "ellipsoid_height_missing"


def test_relative_height_is_separate_geometry_contract() -> None:
    ready = relative_geometry_height({"height": {"relative_m": 82.0}})
    invalid = relative_geometry_height({"height": {"relative_m": -1.0}})

    assert ready["status"] == "ready"
    assert ready["reference"] == "relative_takeoff"
    assert ready["value_m"] == 82.0
    assert invalid["status"] == "unavailable"
    assert invalid["reason"] == "relative_height_not_positive"
