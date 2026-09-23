from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite, sqrt
from statistics import median
from typing import Any, Iterable, Mapping


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_epoch_pair(
    reference: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    reference_id = _text(reference.get("id"))
    comparison_id = _text(comparison.get("id"))
    if reference_id is None or comparison_id is None:
        issues.append({"code": "EPOCH_ID_MISSING", "severity": "error"})
    elif reference_id == comparison_id:
        issues.append({"code": "EPOCH_IDS_IDENTICAL", "severity": "error"})

    reference_time = _time(reference.get("captured_at"))
    comparison_time = _time(comparison.get("captured_at"))
    if reference_time is None or comparison_time is None:
        issues.append({"code": "EPOCH_TIME_INVALID", "severity": "error"})
    elif comparison_time <= reference_time:
        issues.append(
            {
                "code": "EPOCH_ORDER_INVALID",
                "severity": "error",
                "detail": "comparison must be later than reference",
            }
        )

    reference_crs = reference.get("crs")
    comparison_crs = comparison.get("crs")
    reference_crs_map = (
        reference_crs if isinstance(reference_crs, Mapping) else {}
    )
    comparison_crs_map = (
        comparison_crs if isinstance(comparison_crs, Mapping) else {}
    )

    ref_identifier = _text(reference_crs_map.get("identifier"))
    cmp_identifier = _text(comparison_crs_map.get("identifier"))
    ref_metric = bool(reference_crs_map.get("metric"))
    cmp_metric = bool(comparison_crs_map.get("metric"))
    ref_projected = bool(reference_crs_map.get("projected"))
    cmp_projected = bool(comparison_crs_map.get("projected"))

    if not ref_identifier or not cmp_identifier:
        issues.append({"code": "EPOCH_CRS_MISSING", "severity": "error"})
    elif ref_identifier != cmp_identifier:
        issues.append(
            {
                "code": "EPOCH_CRS_MISMATCH",
                "severity": "error",
                "reference_crs": ref_identifier,
                "comparison_crs": cmp_identifier,
            }
        )

    if not (ref_metric and cmp_metric and ref_projected and cmp_projected):
        issues.append(
            {
                "code": "EPOCH_CRS_NOT_METRIC_PROJECTED",
                "severity": "error",
            }
        )

    status = (
        "blocked"
        if any(issue["severity"] == "error" for issue in issues)
        else "ready"
    )

    return {
        "status": status,
        "reference_id": reference_id,
        "comparison_id": comparison_id,
        "reference_time": (
            reference_time.isoformat() if reference_time else None
        ),
        "comparison_time": (
            comparison_time.isoformat() if comparison_time else None
        ),
        "crs_identifier": (
            ref_identifier
            if ref_identifier and ref_identifier == cmp_identifier
            else None
        ),
        "issues": issues,
    }


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "mean_m": None,
            "median_m": None,
            "rmse_m": None,
            "min_m": None,
            "max_m": None,
        }
    return {
        "count": len(values),
        "mean_m": sum(values) / len(values),
        "median_m": median(values),
        "rmse_m": sqrt(sum(value * value for value in values) / len(values)),
        "min_m": min(values),
        "max_m": max(values),
    }


def change_mask(
    signed_changes_m: Iterable[Any],
    *,
    threshold_m: float,
) -> list[int | None]:
    threshold = _finite(threshold_m)
    if threshold is None or threshold < 0.0:
        raise ValueError("threshold_m must be finite and >= 0.")

    result: list[int | None] = []
    for raw in signed_changes_m:
        value = _finite(raw)
        if value is None:
            result.append(None)
        elif value > threshold:
            result.append(1)
        elif value < -threshold:
            result.append(-1)
        else:
            result.append(0)
    return result


def summarize_raster_change(
    signed_deltas_m: Iterable[Any],
    *,
    cell_area_m2: float,
    threshold_m: float,
) -> dict[str, Any]:
    area = _finite(cell_area_m2)
    threshold = _finite(threshold_m)
    if area is None or area <= 0.0:
        raise ValueError("cell_area_m2 must be positive.")
    if threshold is None or threshold < 0.0:
        raise ValueError("threshold_m must be finite and >= 0.")

    raw_values = list(signed_deltas_m)
    mask = change_mask(raw_values, threshold_m=threshold)
    values = [
        value
        for raw in raw_values
        if (value := _finite(raw)) is not None
    ]

    positive = [value for value in values if value > threshold]
    negative = [value for value in values if value < -threshold]
    stable = [
        value
        for value in values
        if -threshold <= value <= threshold
    ]

    fill_volume = sum(value * area for value in positive)
    cut_volume = sum(-value * area for value in negative)
    changed_count = len(positive) + len(negative)

    return {
        "threshold_m": threshold,
        "cell_area_m2": area,
        "valid_cell_count": len(values),
        "changed_cell_count": changed_count,
        "stable_cell_count": len(stable),
        "changed_area_m2": changed_count * area,
        "fill_volume_m3": fill_volume,
        "cut_volume_m3": cut_volume,
        "net_volume_m3": fill_volume - cut_volume,
        "positive": _summary(positive),
        "negative": _summary(negative),
        "all_valid": _summary(values),
        "mask": mask,
    }


def summarize_cloud_change(
    signed_distances_m: Iterable[Any],
    *,
    threshold_m: float,
) -> dict[str, Any]:
    threshold = _finite(threshold_m)
    if threshold is None or threshold < 0.0:
        raise ValueError("threshold_m must be finite and >= 0.")

    raw_values = list(signed_distances_m)
    mask = change_mask(raw_values, threshold_m=threshold)
    values = [
        value
        for raw in raw_values
        if (value := _finite(raw)) is not None
    ]
    positive = [value for value in values if value > threshold]
    negative = [value for value in values if value < -threshold]
    stable = [
        value
        for value in values
        if -threshold <= value <= threshold
    ]

    return {
        "threshold_m": threshold,
        "valid_point_count": len(values),
        "changed_point_count": len(positive) + len(negative),
        "stable_point_count": len(stable),
        "positive": _summary(positive),
        "negative": _summary(negative),
        "all_valid": _summary(values),
        "mask": mask,
    }


def build_epoch_report(
    *,
    reference: Mapping[str, Any],
    comparison: Mapping[str, Any],
    raster_change: Mapping[str, Any] | None = None,
    cloud_change: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pair = validate_epoch_pair(reference, comparison)
    issues = list(pair["issues"])

    if raster_change is None and cloud_change is None:
        issues.append(
            {
                "code": "EPOCH_CHANGE_PRODUCT_MISSING",
                "severity": "warning",
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
        "pair": pair,
        "raster_change": dict(raster_change) if raster_change else None,
        "cloud_change": dict(cloud_change) if cloud_change else None,
        "provenance": dict(provenance or {}),
        "issues": issues,
    }
