from __future__ import annotations

from collections import defaultdict, deque
from math import isfinite
from statistics import median
from typing import Any, Iterable, Mapping


PYCOLMAP_VERSION = "4.2.0"

DEFAULT_THRESHOLDS = {
    "min_registration_ratio": 0.90,
    "max_mean_reprojection_error_px": 2.0,
    "max_p95_reprojection_error_px": 4.0,
    "min_mean_track_length": 3.0,
    "min_connected_image_ratio": 0.95,
}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _iter_mapping_values(value: Any) -> list[Any]:
    if value is None:
        return []
    values = getattr(value, "values", None)
    if callable(values):
        return list(values())
    if isinstance(value, Mapping):
        return list(value.values())
    try:
        return list(value)
    except TypeError:
        return []


def _track_elements(point: Any) -> list[Any]:
    track = getattr(point, "track", None)
    if track is None:
        return []
    elements = getattr(track, "elements", None)
    if elements is not None:
        try:
            return list(elements)
        except TypeError:
            pass
    try:
        return list(track)
    except TypeError:
        return []


def _track_length(point: Any) -> int:
    track = getattr(point, "track", None)
    if track is None:
        return 0

    length = getattr(track, "length", None)
    if callable(length):
        try:
            return max(0, int(length()))
        except (TypeError, ValueError):
            pass
    elif length is not None:
        try:
            return max(0, int(length))
        except (TypeError, ValueError):
            pass

    return len(_track_elements(point))


def _image_id_from_track_element(element: Any) -> int | None:
    value = getattr(element, "image_id", None)
    if value is None and isinstance(element, Mapping):
        value = element.get("image_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _image_id(image: Any) -> int | None:
    value = getattr(image, "image_id", None)
    if value is None and isinstance(image, Mapping):
        value = image.get("image_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _image_name(image: Any) -> str | None:
    value = getattr(image, "name", None)
    if value is None and isinstance(image, Mapping):
        value = image.get("name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _image_has_pose(image: Any) -> bool:
    value = getattr(image, "has_pose", None)
    if callable(value):
        try:
            return bool(value())
        except TypeError:
            return False
    if value is not None:
        return bool(value)
    if isinstance(image, Mapping):
        return bool(image.get("has_pose", False))
    return False


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


def _connected_components(
    registered_ids: set[int],
    adjacency: Mapping[int, set[int]],
) -> list[list[int]]:
    remaining = set(registered_ids)
    components: list[list[int]] = []
    while remaining:
        seed = min(remaining)
        queue: deque[int] = deque([seed])
        component: list[int] = []
        remaining.remove(seed)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in adjacency.get(current, set()):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    return sorted(components, key=lambda item: (-len(item), item))


def inspect_reconstruction(
    reconstruction: Any,
    *,
    expected_image_names: Iterable[str] | None = None,
    thresholds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Inspect a pycolmap-compatible sparse reconstruction.

    The function intentionally relies only on public Reconstruction/Image/
    Point3D-style attributes and methods, so the API package itself does not
    import pycolmap. A dedicated worker can pass a real pycolmap.Reconstruction.
    """

    config = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        for key, value in thresholds.items():
            parsed = _finite(value)
            if key in config and parsed is not None:
                config[key] = parsed

    try:
        reconstruction.update_point_3d_errors()
    except Exception:
        # Some already-serialized/fake reconstructions may not support updates.
        pass

    images = _iter_mapping_values(getattr(reconstruction, "images", None))
    points = _iter_mapping_values(getattr(reconstruction, "points3D", None))

    registered_images = [image for image in images if _image_has_pose(image)]
    registered_ids = {
        image_id
        for image in registered_images
        if (image_id := _image_id(image)) is not None
    }
    image_names = {
        image_id: name
        for image in images
        if (image_id := _image_id(image)) is not None
        and (name := _image_name(image)) is not None
    }

    expected_names = {
        str(name)
        for name in (expected_image_names or [])
        if isinstance(name, str) and name
    }
    if expected_names:
        expected_count = len(expected_names)
        registered_expected = sum(
            1
            for image in registered_images
            if _image_name(image) in expected_names
        )
    else:
        try:
            expected_count = int(reconstruction.num_images())
        except Exception:
            expected_count = len(images)
        registered_expected = len(registered_images)

    try:
        registered_count = int(reconstruction.num_reg_images())
    except Exception:
        registered_count = len(registered_images)

    try:
        point_count = int(reconstruction.num_points3D())
    except Exception:
        point_count = len(points)

    try:
        observation_count = int(reconstruction.compute_num_observations())
    except Exception:
        observation_count = sum(_track_length(point) for point in points)

    try:
        mean_track_length = float(reconstruction.compute_mean_track_length())
    except Exception:
        tracks = [_track_length(point) for point in points]
        mean_track_length = sum(tracks) / len(tracks) if tracks else 0.0

    try:
        mean_observations_per_registered_image = float(
            reconstruction.compute_mean_observations_per_reg_image()
        )
    except Exception:
        mean_observations_per_registered_image = (
            observation_count / registered_count
            if registered_count > 0
            else 0.0
        )

    try:
        mean_reprojection_error = float(
            reconstruction.compute_mean_reprojection_error()
        )
    except Exception:
        errors = [
            error
            for point in points
            if (error := _finite(getattr(point, "error", None))) is not None
            and error >= 0.0
        ]
        mean_reprojection_error = (
            sum(errors) / len(errors) if errors else 0.0
        )

    point_errors = [
        error
        for point in points
        if (error := _finite(getattr(point, "error", None))) is not None
        and error >= 0.0
    ]
    track_lengths = [_track_length(point) for point in points]

    adjacency: dict[int, set[int]] = defaultdict(set)
    observations_by_image: dict[int, int] = defaultdict(int)
    for point in points:
        track_ids = {
            image_id
            for element in _track_elements(point)
            if (image_id := _image_id_from_track_element(element)) is not None
            and image_id in registered_ids
        }
        for image_id in track_ids:
            observations_by_image[image_id] += 1
            adjacency.setdefault(image_id, set())
        track_list = sorted(track_ids)
        for index, left in enumerate(track_list):
            for right in track_list[index + 1 :]:
                adjacency[left].add(right)
                adjacency[right].add(left)

    for image_id in registered_ids:
        adjacency.setdefault(image_id, set())

    components = _connected_components(registered_ids, adjacency)
    largest_component_size = len(components[0]) if components else 0
    connected_ratio = (
        largest_component_size / registered_count
        if registered_count > 0
        else 0.0
    )

    weak_images = []
    for image_id in sorted(registered_ids):
        degree = len(adjacency.get(image_id, set()))
        observations = observations_by_image.get(image_id, 0)
        if degree <= 1 or observations == 0:
            weak_images.append(
                {
                    "image_id": image_id,
                    "image_name": image_names.get(image_id),
                    "connected_images": degree,
                    "triangulated_observations": observations,
                }
            )

    registration_ratio = (
        registered_expected / expected_count
        if expected_count > 0
        else 0.0
    )

    issues: list[dict[str, Any]] = []
    if registered_count == 0:
        issues.append(
            {
                "code": "SFM_NO_REGISTERED_IMAGES",
                "severity": "error",
            }
        )
    if point_count == 0:
        issues.append(
            {
                "code": "SFM_NO_SPARSE_POINTS",
                "severity": "error",
            }
        )
    if expected_count > 0 and registration_ratio < config["min_registration_ratio"]:
        issues.append(
            {
                "code": "SFM_LOW_REGISTRATION_RATIO",
                "severity": "warning",
                "value": registration_ratio,
                "threshold": config["min_registration_ratio"],
            }
        )
    if (
        point_errors
        and mean_reprojection_error
        > config["max_mean_reprojection_error_px"]
    ):
        issues.append(
            {
                "code": "SFM_HIGH_MEAN_REPROJECTION_ERROR",
                "severity": "warning",
                "value_px": mean_reprojection_error,
                "threshold_px": config["max_mean_reprojection_error_px"],
            }
        )

    p95_error = _percentile(point_errors, 0.95)
    if (
        p95_error is not None
        and p95_error > config["max_p95_reprojection_error_px"]
    ):
        issues.append(
            {
                "code": "SFM_HIGH_P95_REPROJECTION_ERROR",
                "severity": "warning",
                "value_px": p95_error,
                "threshold_px": config["max_p95_reprojection_error_px"],
            }
        )
    if (
        point_count > 0
        and mean_track_length < config["min_mean_track_length"]
    ):
        issues.append(
            {
                "code": "SFM_LOW_MEAN_TRACK_LENGTH",
                "severity": "warning",
                "value": mean_track_length,
                "threshold": config["min_mean_track_length"],
            }
        )
    if (
        registered_count > 1
        and connected_ratio < config["min_connected_image_ratio"]
    ):
        issues.append(
            {
                "code": "SFM_FRAGMENTED_CAMERA_NETWORK",
                "severity": "warning",
                "value": connected_ratio,
                "threshold": config["min_connected_image_ratio"],
                "components": len(components),
            }
        )
    if weak_images:
        issues.append(
            {
                "code": "SFM_WEAK_CAMERA_CONNECTIVITY",
                "severity": "warning",
                "count": len(weak_images),
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
        "pycolmap_contract_version": PYCOLMAP_VERSION,
        "images": {
            "expected": expected_count,
            "registered": registered_count,
            "registered_expected": registered_expected,
            "registration_ratio": registration_ratio,
        },
        "sparse_points": {
            "count": point_count,
            "observations": observation_count,
            "mean_observations_per_registered_image": (
                mean_observations_per_registered_image
            ),
        },
        "reprojection_error_px": {
            "mean": mean_reprojection_error if point_errors else None,
            "median": median(point_errors) if point_errors else None,
            "p95": p95_error,
            "max": max(point_errors) if point_errors else None,
            "sample_count": len(point_errors),
        },
        "track_length": {
            "mean": mean_track_length if track_lengths else None,
            "median": median(track_lengths) if track_lengths else None,
            "p10": _percentile(
                [float(value) for value in track_lengths],
                0.10,
            ),
            "min": min(track_lengths) if track_lengths else None,
            "max": max(track_lengths) if track_lengths else None,
        },
        "connectivity": {
            "component_count": len(components),
            "largest_component_images": largest_component_size,
            "largest_component_ratio": connected_ratio,
            "components": components,
            "weak_image_candidates": weak_images,
        },
        "thresholds": config,
        "issues": issues,
    }
