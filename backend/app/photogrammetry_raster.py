from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping

import rasterio


def _metric_projected(crs) -> bool:
    if crs is None or not crs.is_projected:
        return False
    units = [axis.unit_name for axis in crs.axis_info[:2]]
    return bool(units) and all(unit in {"metre", "meter"} for unit in units)


def inspect_raster(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    issues: list[dict[str, Any]] = []

    with rasterio.open(source) as dataset:
        crs = dataset.crs
        transform = dataset.transform
        bounds = dataset.bounds
        xres = abs(float(transform.a))
        yres = abs(float(transform.e))

        if crs is None:
            issues.append({"code": "RASTER_CRS_MISSING", "severity": "error"})
        elif not crs.is_projected:
            issues.append({"code": "RASTER_CRS_NOT_PROJECTED", "severity": "warning"})
        elif not _metric_projected(crs):
            issues.append({"code": "RASTER_CRS_NOT_METRIC", "severity": "warning"})

        if not all(isfinite(v) for v in (bounds.left, bounds.bottom, bounds.right, bounds.top)):
            issues.append({"code": "RASTER_BOUNDS_INVALID", "severity": "error"})

        if xres <= 0 or yres <= 0:
            issues.append({"code": "RASTER_RESOLUTION_INVALID", "severity": "error"})

        if transform.b != 0 or transform.d != 0:
            issues.append({"code": "RASTER_ROTATED_OR_SHEARED", "severity": "warning"})

        status = "blocked" if any(i["severity"] == "error" for i in issues) else (
            "warning" if issues else "ready"
        )

        return {
            "status": status,
            "path": str(source),
            "driver": dataset.driver,
            "width": dataset.width,
            "height": dataset.height,
            "band_count": dataset.count,
            "dtypes": list(dataset.dtypes),
            "nodata": dataset.nodata,
            "crs": None if crs is None else {
                "identifier": crs.to_string(),
                "wkt": crs.to_wkt(),
                "projected": crs.is_projected,
                "metric": _metric_projected(crs),
            },
            "transform": {
                "a": transform.a, "b": transform.b, "c": transform.c,
                "d": transform.d, "e": transform.e, "f": transform.f,
            },
            "bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
            "resolution": {"x": xres, "y": yres},
            "issues": issues,
        }


def _intersects(a: list[float], b: list[float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def evaluate_raster_set(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = list(items)
    issues: list[dict[str, Any]] = []

    valid = [item for item in records if item.get("crs") and item.get("bounds")]
    identifiers = {
        str(item["crs"]["identifier"])
        for item in valid
        if isinstance(item.get("crs"), Mapping) and item["crs"].get("identifier")
    }
    if len(identifiers) > 1:
        issues.append({
            "code": "RASTER_SET_CRS_MISMATCH",
            "severity": "error",
            "crs": sorted(identifiers),
        })

    if len(valid) >= 2 and len(identifiers) == 1:
        anchor = valid[0]
        for other in valid[1:]:
            if not _intersects(list(anchor["bounds"]), list(other["bounds"])):
                issues.append({
                    "code": "RASTER_SET_BOUNDS_DISJOINT",
                    "severity": "error",
                    "left": anchor.get("kind") or anchor.get("path"),
                    "right": other.get("kind") or other.get("path"),
                })

    blocked_inputs = [item for item in records if item.get("status") == "blocked"]
    if blocked_inputs:
        issues.append({
            "code": "RASTER_SET_CONTAINS_BLOCKED_INPUT",
            "severity": "error",
            "count": len(blocked_inputs),
        })

    status = "blocked" if any(i["severity"] == "error" for i in issues) else (
        "warning" if any(item.get("status") == "warning" for item in records) else "ready"
    )

    return {
        "status": status,
        "count": len(records),
        "crs_identifiers": sorted(identifiers),
        "issues": issues,
    }
