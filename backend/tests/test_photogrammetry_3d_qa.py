from __future__ import annotations

import pytest

from app.photogrammetry_3d_qa import (
    OPEN3D_VERSION,
    build_open3d_plan,
    evaluate_3d_comparison,
    normalize_registration_result,
    summarize_distances,
)


def test_open3d_plan_point_to_plane_includes_normals() -> None:
    plan = build_open3d_plan(
        source_path="/data/source.laz",
        target_path="/data/target.laz",
        icp_method="point_to_plane",
    )

    names = [stage["name"] for stage in plan["stages"]]
    assert plan["version"] == "0.20.0"
    assert "estimate_normals" in names
    assert names[-1] == "target_to_source_distance"


def test_point_to_point_plan_does_not_require_normals() -> None:
    plan = build_open3d_plan(
        source_path="/data/source.ply",
        target_path="/data/target.ply",
        icp_method="point_to_point",
    )

    names = [stage["name"] for stage in plan["stages"]]
    assert "estimate_normals" not in names


def test_relative_paths_are_rejected() -> None:
    with pytest.raises(ValueError, match="absolute"):
        build_open3d_plan(
            source_path="source.ply",
            target_path="/data/target.ply",
        )


def test_distance_summary_reports_rmse_and_p95() -> None:
    stats = summarize_distances([0.0, 0.1, 0.2, 0.3, 0.4])

    assert stats["count"] == 5
    assert stats["mean_m"] == pytest.approx(0.2)
    assert stats["median_m"] == pytest.approx(0.2)
    assert stats["rmse_m"] == pytest.approx((0.3 / 5) ** 0.5)
    assert stats["p95_m"] == pytest.approx(0.38)
    assert stats["max_m"] == pytest.approx(0.4)


def test_registration_result_is_normalized() -> None:
    result = normalize_registration_result(
        {
            "fitness": 0.8,
            "inlier_rmse": 0.03,
            "transformation": [
                [1, 0, 0, 1],
                [0, 1, 0, 2],
                [0, 0, 1, 3],
                [0, 0, 0, 1],
            ],
            "correspondence_count": 100,
        }
    )

    assert result["fitness"] == pytest.approx(0.8)
    assert result["inlier_rmse_m"] == pytest.approx(0.03)
    assert result["transformation"][0][3] == pytest.approx(1.0)
    assert result["correspondence_count"] == 100


def test_good_comparison_is_ready() -> None:
    result = evaluate_3d_comparison(
        registration={
            "fitness": 0.9,
            "inlier_rmse": 0.03,
            "transformation": [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
        },
        source_to_target_distances=[0.01, 0.02, 0.03, 0.04],
        target_to_source_distances=[0.01, 0.02, 0.03, 0.04],
        source_point_count=100,
        target_point_count=100,
        source_inlier_count=95,
        target_inlier_count=95,
    )

    assert result["status"] == "ready"
    assert result["issues"] == []


def test_bad_metrics_generate_warnings_not_fake_block() -> None:
    result = evaluate_3d_comparison(
        registration={"fitness": 0.2, "inlier_rmse": 0.4},
        source_to_target_distances=[0.1, 0.4, 0.5],
        target_to_source_distances=[0.2, 0.3, 0.6],
        source_point_count=100,
        target_point_count=100,
        source_inlier_count=70,
        target_inlier_count=80,
    )

    codes = {item["code"] for item in result["issues"]}
    assert result["status"] == "warning"
    assert "QA3D_LOW_REGISTRATION_FITNESS" in codes
    assert "QA3D_HIGH_INLIER_RMSE" in codes
    assert "QA3D_HIGH_SYMMETRIC_P95_DISTANCE" in codes
    assert "QA3D_HIGH_OUTLIER_RATIO" in codes


def test_empty_cloud_blocks() -> None:
    result = evaluate_3d_comparison(
        registration={"fitness": None, "inlier_rmse": None},
        source_to_target_distances=[],
        target_to_source_distances=[],
        source_point_count=0,
        target_point_count=10,
    )

    assert result["status"] == "blocked"
    assert any(
        issue["code"] == "QA3D_SOURCE_EMPTY"
        for issue in result["issues"]
    )


def test_thresholds_are_explicitly_overridable() -> None:
    result = evaluate_3d_comparison(
        registration={"fitness": 0.4, "inlier_rmse": 0.15},
        source_to_target_distances=[0.1, 0.15],
        target_to_source_distances=[0.1, 0.15],
        source_point_count=10,
        target_point_count=10,
        source_inlier_count=9,
        target_inlier_count=9,
        thresholds={
            "min_fitness": 0.3,
            "max_inlier_rmse_m": 0.2,
            "max_symmetric_p95_m": 0.2,
            "max_outlier_ratio": 0.2,
        },
    )

    assert result["status"] == "ready"


def test_version_contract_is_pinned() -> None:
    assert OPEN3D_VERSION == "0.20.0"
