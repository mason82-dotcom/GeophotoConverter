from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from app.photogrammetry_gcp import (
    build_micmac_gcp_bundle,
    build_odm_gcp_list,
    colmap_direct_gcp_capability,
    normalize_gcp_project,
    residual_report,
)


def _point(point_id: str, role: str, x: float, *, obs: int = 3) -> dict:
    return {
        "id": point_id,
        "role": role,
        "x_m": x,
        "y_m": 5_430_000.0 + x,
        "z_m": 120.0,
        "sigma_x_m": 0.02,
        "sigma_y_m": 0.02,
        "sigma_z_m": 0.03,
        "observations": [
            {
                "image_name": f"IMG_{index:04d}.JPG",
                "pixel_x": 1000.0 + index * 10 + x,
                "pixel_y": 800.0 + index * 5 + x,
            }
            for index in range(obs)
        ],
    }


def _ready_project() -> dict:
    points = [
        _point("GCP-01", "control", 500_000.0),
        _point("GCP-02", "control", 500_020.0),
        _point("GCP-03", "control", 500_040.0),
        _point("GCP-04", "control", 500_060.0),
        _point("GCP-05", "control", 500_080.0),
        _point("CHK-01", "checkpoint", 500_100.0),
        _point("CHK-02", "checkpoint", 500_120.0),
    ]
    project = normalize_gcp_project(points, "EPSG:32632")
    assert project["status"] == "ready"
    return project


def test_normalize_gcp_project_separates_control_and_checkpoint() -> None:
    project = _ready_project()

    assert project["crs"]["identifier"] == "EPSG:32632"
    assert project["summary"] == {
        "point_count": 7,
        "control_points": 5,
        "checkpoints": 2,
        "observation_count": 21,
    }
    assert project["issues"] == []


def test_geographic_crs_is_blocked() -> None:
    project = normalize_gcp_project(
        [_point("GCP-01", "control", 8.5)],
        "EPSG:4326",
    )

    assert project["status"] == "blocked"
    assert project["issues"][0]["code"] == "invalid_project_crs"


def test_duplicate_id_and_duplicate_image_observation_are_blocked() -> None:
    first = _point("GCP-01", "control", 500_000.0)
    first["observations"].append(dict(first["observations"][0]))
    duplicate = _point("GCP-01", "control", 500_020.0)

    project = normalize_gcp_project(
        [
            first,
            duplicate,
            _point("GCP-02", "control", 500_040.0),
            _point("GCP-03", "control", 500_060.0),
        ],
        "EPSG:32632",
    )

    codes = {item["code"] for item in project["issues"]}
    assert project["status"] == "blocked"
    assert "duplicate_image_observation" in codes
    assert "duplicate_point_id" in codes


def test_low_observation_count_blocks_point() -> None:
    points = [
        _point("GCP-01", "control", 500_000.0, obs=1),
        _point("GCP-02", "control", 500_020.0),
        _point("GCP-03", "control", 500_040.0),
        _point("GCP-04", "control", 500_060.0),
        _point("GCP-05", "control", 500_080.0),
    ]
    project = normalize_gcp_project(points, "EPSG:32632")

    assert project["status"] == "blocked"
    assert any(
        item["code"] == "insufficient_point_observations"
        and item["point_id"] == "GCP-01"
        for item in project["issues"]
    )


def test_odm_export_uses_controls_only_by_default() -> None:
    project = _ready_project()
    text = build_odm_gcp_list(project)
    lines = text.strip().splitlines()

    assert lines[0] == "EPSG:32632"
    assert len(lines) == 1 + 5 * 3
    assert any("GCP-01" in line for line in lines[1:])
    assert all("CHK-" not in line for line in lines[1:])


def test_micmac_bundle_keeps_checkpoints_out_of_adjustment() -> None:
    project = _ready_project()
    bundle = build_micmac_gcp_bundle(project)

    assert "GCP-01" in bundle["ground_points_text"]
    assert "CHK-01" not in bundle["ground_points_text"]
    assert bundle["gcpconvert_command"] == [
        "mm3d",
        "GCPConvert",
        "#F=N_X_Y_Z",
        "ground_points.txt",
        "Out=ground_points.xml",
    ]

    root = ET.fromstring(bundle["measurements_xml"])
    point_names = [
        node.text
        for node in root.findall(".//NamePt")
    ]
    assert "GCP-01" in point_names
    assert "CHK-01" not in point_names


def test_colmap_direct_ground_points_are_explicitly_unsupported() -> None:
    capability = colmap_direct_gcp_capability()

    assert capability["status"] == "unsupported"
    assert capability["reason"] == "no_direct_ground_point_constraint_adapter"
    assert "camera-center" in capability["note"]


def test_residual_report_separates_control_and_checkpoint_rmse() -> None:
    project = _ready_project()
    estimates = {
        point["id"]: {
            "x_m": point["x_m"] + (0.10 if point["role"] == "control" else 0.30),
            "y_m": point["y_m"],
            "z_m": point["z_m"] + (0.20 if point["role"] == "control" else 0.40),
        }
        for point in project["points"]
    }

    report = residual_report(project, estimates)

    assert report["control"]["count"] == 5
    assert report["checkpoint"]["count"] == 2
    assert report["control"]["rmse_x_m"] == pytest.approx(0.10)
    assert report["control"]["rmse_z_m"] == pytest.approx(0.20)
    assert report["checkpoint"]["rmse_x_m"] == pytest.approx(0.30)
    assert report["checkpoint"]["rmse_z_m"] == pytest.approx(0.40)
    assert report["missing_estimates"] == []


def test_residual_report_tracks_missing_estimates() -> None:
    project = _ready_project()
    report = residual_report(
        project,
        {
            "GCP-01": {
                "x_m": project["points"][0]["x_m"],
                "y_m": project["points"][0]["y_m"],
                "z_m": project["points"][0]["z_m"],
            }
        },
    )

    assert report["control"]["count"] == 1
    assert "CHK-01" in report["missing_estimates"]
