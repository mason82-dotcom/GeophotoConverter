from __future__ import annotations

from math import hypot, isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping

import rasterio


def _metric_projected(crs) -> bool:
    if crs is None or not crs.is_projected:
        return False
    try:
        _, factor = crs.linear_units_factor
    except Exception:
        return False
    return isfinite(float(factor)) and abs(float(factor) - 1.0) <= 1e-12


def _crs_identifier(crs) -> str:
    authority = crs.to_authority()
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.to_string()


def inspect_raster(path: str | Path) -> dict[str, Any]:
    """Inspect one geospatial raster without modifying it."""

    source = Path(path)
    issues: list[dict[str, Any]] = []

    with rasterio.open(source) as dataset:
        crs = dataset.crs
        transform = dataset.transform
        bounds = dataset.bounds
        xres = hypot(float(transform.a), float(transform.d))
        yres = hypot(float(transform.b), float(transform.e))

        if crs is None:
            issues.append({"code": "RASTER_CRS_MISSING", "severity": "error"})
        elif not crs.is_projected:
            issues.append({"code": "RASTER_CRS_NOT_PROJECTED", "severity": "warning"})
        elif not _metric_projected(crs):
            issues.append({"code": "RASTER_CRS_NOT_METRIC", "severity": "warning"})

        bound_values = (bounds.left, bounds.bottom, bounds.right, bounds.top)
        if (
            not all(isfinite(float(value)) for value in bound_values)
            or bounds.left >= bounds.right
            or bounds.bottom >= bounds.top
        ):
            issues.append({"code": "RASTER_BOUNDS_INVALID", "severity": "error"})

        if not isfinite(xres) or not isfinite(yres) or xres <= 0.0 or yres <= 0.0:
            issues.append({"code": "RASTER_RESOLUTION_INVALID", "severity": "error"})

        if abs(float(transform.b)) > 1e-12 or abs(float(transform.d)) > 1e-12:
            issues.append({"code": "RASTER_ROTATED_OR_SHEARED", "severity": "warning"})

        status = (
            "blocked"
            if any(issue["severity"] == "error" for issue in issues)
            else "warning"
            if issues
            else "ready"
        )

        return {
            "status": status,
            "path": str(source),
            "driver": dataset.driver,
            "width": int(dataset.width),
            "height": int(dataset.height),
            "band_count": int(dataset.count),
            "dtypes": list(dataset.dtypes),
            "nodata": dataset.nodata,
            "crs": None
            if crs is None
            else {
                "identifier": _crs_identifier(crs),
                "wkt": crs.to_wkt(),
                "projected": bool(crs.is_projected),
                "metric": _metric_projected(crs),
                "linear_units": crs.linear_units if crs.is_projected else None,
            },
            "transform": {
                "a": float(transform.a),
                "b": float(transform.b),
                "c": float(transform.c),
                "d": float(transform.d),
                "e": float(transform.e),
                "f": float(transform.f),
            },
            "bounds": [
                float(bounds.left),
                float(bounds.bottom),
                float(bounds.right),
                float(bounds.top),
            ],
            "resolution": {"x": float(xres), "y": float(yres)},
            "issues": issues,
        }


def _intersects(a: list[float], b: list[float]) -> bool:
    return not (
        a[2] <= b[0]
        or b[2] <= a[0]
        or a[3] <= b[1]
        or b[3] <= a[1]
    )


def evaluate_raster_set(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate cross-product consistency for already inspected rasters."""

    records = list(items)
    issues: list[dict[str, Any]] = []

    valid = [
        item
        for item in records
        if isinstance(item.get("crs"), Mapping) and item.get("bounds")
    ]
    identifiers = {
        str(item["crs"]["identifier"])
        for item in valid
        if item["crs"].get("identifier")
    }

    if len(identifiers) > 1:
        issues.append(
            {
                "code": "RASTER_SET_CRS_MISMATCH",
                "severity": "error",
                "crs": sorted(identifiers),
            }
        )

    if len(valid) >= 2 and len(identifiers) == 1:
        anchor = valid[0]
        for other in valid[1:]:
            if not _intersects(list(anchor["bounds"]), list(other["bounds"])):
                issues.append(
                    {
                        "code": "RASTER_SET_BOUNDS_DISJOINT",
                        "severity": "error",
                        "left": anchor.get("kind") or anchor.get("path"),
                        "right": other.get("kind") or other.get("path"),
                    }
                )

    blocked_inputs = [item for item in records if item.get("status") == "blocked"]
    if blocked_inputs:
        issues.append(
            {
                "code": "RASTER_SET_CONTAINS_BLOCKED_INPUT",
                "severity": "error",
                "count": len(blocked_inputs),
            }
        )

    status = (
        "blocked"
        if any(issue["severity"] == "error" for issue in issues)
        else "warning"
        if any(item.get("status") == "warning" for item in records)
        else "ready"
    )

    return {
        "status": status,
        "count": len(records),
        "crs_identifiers": sorted(identifiers),
        "issues": issues,
    }
