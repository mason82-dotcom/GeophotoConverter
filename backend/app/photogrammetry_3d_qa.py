from __future__ import annotations

from math import isfinite, sqrt
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping


OPEN3D_VERSION = "0.20.0"

DEFAULT_THRESHOLDS = {
    "min_fitness": 0.50,
    "max_inlier_rmse_m": 0.10,
    "max_symmetric_p95_m": 0.20,
    "max_outlier_ratio": 0.10,
}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _positive(value: Any, label: str) -> float:
    parsed = _finite(value)
    if parsed is None or parsed <= 0.0:
        raise ValueError(f"{label} must be a positive finite number.")
    return parsed


def _absolute_path(value: str | Path, label: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path.")
    return str(path)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize_distances(values: Iterable[Any]) -> dict[str, Any]:
    parsed = [
        value
        for raw in values
        if (value := _finite(raw)) is not None and value >= 0.0
    ]
    if not parsed:
        return {
            "count": 0,
            "mean_m": None,
            "median_m": None,
            "rmse_m": None,
            "p95_m": None,
            "max_m": None,
        }

    return {
        "count": len(parsed),
        "mean_m": sum(parsed) / len(parsed),
        "median_m": median(parsed),
        "rmse_m": sqrt(sum(value * value for value in parsed) / len(parsed)),
        "p95_m": _percentile(parsed, 0.95),
        "max_m": max(parsed),
    }


def build_open3d_plan(
    *,
    source_path: str | Path,
    target_path: str | Path,
    voxel_size_m: float = 0.05,
    normal_radius_m: float = 0.15,
    normal_max_nn: int = 30,
    outlier_nb_neighbors: int = 20,
    outlier_std_ratio: float = 2.0,
    max_correspondence_distance_m: float = 0.20,
    icp_method: str = "point_to_plane",
) -> dict[str, Any]:
    if icp_method not in {"point_to_point", "point_to_plane"}:
        raise ValueError("icp_method must be point_to_point or point_to_plane.")
    if normal_max_nn < 3:
        raise ValueError("normal_max_nn must be >= 3.")
    if outlier_nb_neighbors < 2:
        raise ValueError("outlier_nb_neighbors must be >= 2.")

    source = _absolute_path(source_path, "source_path")
    target = _absolute_path(target_path, "target_path")
    voxel = _positive(voxel_size_m, "voxel_size_m")
    normal_radius = _positive(normal_radius_m, "normal_radius_m")
    std_ratio = _positive(outlier_std_ratio, "outlier_std_ratio")
    max_corr = _positive(
        max_correspondence_distance_m,
        "max_correspondence_distance_m",
    )

    stages = [
        {
            "name": "read_point_clouds",
            "operation": "open3d.io.read_point_cloud",
        },
        {
            "name": "voxel_downsample",
            "operation": "voxel_down_sample",
            "voxel_size_m": voxel,
        },
        {
            "name": "statistical_outlier_removal",
            "operation": "remove_statistical_outlier",
            "nb_neighbors": int(outlier_nb_neighbors),
            "std_ratio": std_ratio,
        },
    ]
    if icp_method == "point_to_plane":
        stages.append(
            {
                "name": "estimate_normals",
                "operation": "estimate_normals",
                "radius_m": normal_radius,
                "max_nn": int(normal_max_nn),
            }
        )
    stages.extend(
        [
            {
                "name": "initial_registration_evaluation",
                "operation": "evaluate_registration",
                "max_correspondence_distance_m": max_corr,
            },
            {
                "name": "icp",
                "operation": "registration_icp",
                "method": icp_method,
                "max_correspondence_distance_m": max_corr,
            },
            {
                "name": "source_to_target_distance",
                "operation": "compute_point_cloud_distance",
            },
            {
                "name": "target_to_source_distance",
                "operation": "compute_point_cloud_distance",
            },
        ]
    )

    return {
        "backend": "open3d",
        "version": OPEN3D_VERSION,
        "source_path": source,
        "target_path": target,
        "icp_method": icp_method,
        "stages": stages,
    }


def normalize_registration_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    fitness = _finite(result.get("fitness"))
    rmse = _finite(result.get("inlier_rmse"))
    transformation = result.get("transformation")

    matrix: list[list[float]] | None = None
    if isinstance(transformation, (list, tuple)) and len(transformation) == 4:
        rows: list[list[float]] = []
        valid = True
        for row in transformation:
            if not isinstance(row, (list, tuple)) or len(row) != 4:
                valid = False
                break
            parsed_row = [_finite(value) for value in row]
            if any(value is None for value in parsed_row):
                valid = False
                break
            rows.append([float(value) for value in parsed_row if value is not None])
        if valid:
            matrix = rows

    correspondence_count = result.get("correspondence_count")
    try:
        count = int(correspondence_count) if correspondence_count is not None else None
    except (TypeError, ValueError):
        count = None

    return {
        "fitness": fitness,
        "inlier_rmse_m": rmse,
        "transformation": matrix,
        "correspondence_count": count,
    }


def evaluate_3d_comparison(
    *,
    registration: Mapping[str, Any],
    source_to_target_distances: Iterable[Any],
    target_to_source_distances: Iterable[Any],
    source_point_count: int,
    target_point_count: int,
    source_inlier_count: int | None = None,
    target_inlier_count: int | None = None,
    thresholds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    config = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        for key, value in thresholds.items():
            parsed = _finite(value)
            if key in config and parsed is not None:
                config[key] = parsed

    normalized_registration = normalize_registration_result(registration)
    source_stats = summarize_distances(source_to_target_distances)
    target_stats = summarize_distances(target_to_source_distances)

    issues: list[dict[str, Any]] = []
    if source_point_count <= 0:
        issues.append({"code": "QA3D_SOURCE_EMPTY", "severity": "error"})
    if target_point_count <= 0:
        issues.append({"code": "QA3D_TARGET_EMPTY", "severity": "error"})

    fitness = normalized_registration["fitness"]
    if fitness is None:
        issues.append(
            {"code": "QA3D_REGISTRATION_FITNESS_MISSING", "severity": "warning"}
        )
    elif fitness < config["min_fitness"]:
        issues.append(
            {
                "code": "QA3D_LOW_REGISTRATION_FITNESS",
                "severity": "warning",
                "value": fitness,
                "threshold": config["min_fitness"],
            }
        )

    inlier_rmse = normalized_registration["inlier_rmse_m"]
    if (
        inlier_rmse is not None
        and inlier_rmse > config["max_inlier_rmse_m"]
    ):
        issues.append(
            {
                "code": "QA3D_HIGH_INLIER_RMSE",
                "severity": "warning",
                "value_m": inlier_rmse,
                "threshold_m": config["max_inlier_rmse_m"],
            }
        )

    p95_values = [
        value
        for value in (source_stats["p95_m"], target_stats["p95_m"])
        if value is not None
    ]
    symmetric_p95 = max(p95_values) if p95_values else None
    if (
        symmetric_p95 is not None
        and symmetric_p95 > config["max_symmetric_p95_m"]
    ):
        issues.append(
            {
                "code": "QA3D_HIGH_SYMMETRIC_P95_DISTANCE",
                "severity": "warning",
                "value_m": symmetric_p95,
                "threshold_m": config["max_symmetric_p95_m"],
            }
        )

    def outlier_ratio(total: int, inliers: int | None) -> float | None:
        if total <= 0 or inliers is None:
            return None
        bounded = max(0, min(total, int(inliers)))
        return 1.0 - bounded / total

    source_outliers = outlier_ratio(source_point_count, source_inlier_count)
    target_outliers = outlier_ratio(target_point_count, target_inlier_count)
    for side, ratio in (
        ("source", source_outliers),
        ("target", target_outliers),
    ):
        if ratio is not None and ratio > config["max_outlier_ratio"]:
            issues.append(
                {
                    "code": "QA3D_HIGH_OUTLIER_RATIO",
                    "severity": "warning",
                    "side": side,
                    "value": ratio,
                    "threshold": config["max_outlier_ratio"],
                }
            )

    status = (
        "blocked"
        if any(issue["severity"] == "error" for issue in issues)
        else "warning"
        if issues
        else "ready"
    )

    return {
        "status": status,
        "open3d_contract_version": OPEN3D_VERSION,
        "registration": normalized_registration,
        "distance": {
            "source_to_target": source_stats,
            "target_to_source": target_stats,
            "symmetric_p95_m": symmetric_p95,
        },
        "outliers": {
            "source_ratio": source_outliers,
            "target_ratio": target_outliers,
        },
        "thresholds": config,
        "issues": issues,
    }
