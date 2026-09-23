from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any, Mapping


PDAL_VERSION = "2.10.2"


def pdal_summary_command(path: str | Path) -> list[str]:
    return ["pdal", "info", "--summary", str(path)]


def pdal_stats_command(path: str | Path) -> list[str]:
    return [
        "pdal",
        "info",
        "--stats",
        "--dimensions=X,Y,Z,Classification",
        "--enumerate=Classification",
        str(path),
    ]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def parse_pdal_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary")
    source = summary if isinstance(summary, Mapping) else {}

    raw_bounds = source.get("bounds")
    bounds = raw_bounds if isinstance(raw_bounds, Mapping) else {}

    parsed_bounds = {
        key: _number(bounds.get(key))
        for key in ("minx", "miny", "minz", "maxx", "maxy", "maxz")
    }
    bounds_valid = all(value is not None for value in parsed_bounds.values())

    raw_count = source.get("num_points")
    try:
        count = int(raw_count) if raw_count is not None else None
    except (TypeError, ValueError):
        count = None
    if count is not None and count < 0:
        count = None

    dimensions_raw = source.get("dimensions")
    if isinstance(dimensions_raw, str):
        dimensions = [
            value.strip()
            for value in dimensions_raw.split(",")
            if value.strip()
        ]
    elif isinstance(dimensions_raw, list):
        dimensions = [str(value) for value in dimensions_raw]
    else:
        dimensions = []

    metadata = source.get("metadata")
    metadata_map = metadata if isinstance(metadata, Mapping) else {}

    srs = (
        source.get("srs")
        or source.get("spatialreference")
        or metadata_map.get("srs")
        or metadata_map.get("spatialreference")
    )
    srs_text = str(srs).strip() if srs not in (None, "") else None

    issues: list[dict[str, Any]] = []
    if count is None:
        issues.append({"code": "POINTCLOUD_COUNT_MISSING", "severity": "error"})
    elif count == 0:
        issues.append({"code": "POINTCLOUD_EMPTY", "severity": "error"})

    if not bounds_valid:
        issues.append({"code": "POINTCLOUD_BOUNDS_INVALID", "severity": "error"})
    elif (
        parsed_bounds["maxx"] <= parsed_bounds["minx"]
        or parsed_bounds["maxy"] <= parsed_bounds["miny"]
    ):
        issues.append({"code": "POINTCLOUD_XY_EXTENT_DEGENERATE", "severity": "error"})

    if not srs_text:
        issues.append({"code": "POINTCLOUD_CRS_MISSING", "severity": "warning"})

    status = "blocked" if any(i["severity"] == "error" for i in issues) else (
        "warning" if issues else "ready"
    )

    density_xy = None
    if count and bounds_valid:
        area = (
            (parsed_bounds["maxx"] - parsed_bounds["minx"])
            * (parsed_bounds["maxy"] - parsed_bounds["miny"])
        )
        if area > 0:
            density_xy = count / area

    return {
        "status": status,
        "point_count": count,
        "bounds": parsed_bounds if bounds_valid else None,
        "dimensions": dimensions,
        "srs": srs_text,
        "density_points_per_square_unit": density_xy,
        "reader": payload.get("reader"),
        "pdal_version": payload.get("pdal_version"),
        "issues": issues,
    }


def parse_pdal_stats(payload: Mapping[str, Any]) -> dict[str, Any]:
    stats = payload.get("stats")
    source = stats if isinstance(stats, Mapping) else {}
    raw = source.get("statistic")
    statistics = raw if isinstance(raw, list) else []

    by_name: dict[str, dict[str, Any]] = {}
    for item in statistics:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        record: dict[str, Any] = {}
        for key in ("minimum", "maximum", "average", "stddev", "variance", "count"):
            value = _number(item.get(key))
            if value is not None:
                record[key] = value
        counts = item.get("counts")
        if isinstance(counts, list):
            record["counts"] = [
                dict(value)
                for value in counts
                if isinstance(value, Mapping)
            ]
        by_name[name] = record

    issues: list[dict[str, Any]] = []
    for required in ("X", "Y", "Z"):
        if required not in by_name:
            issues.append({
                "code": "POINTCLOUD_STATS_DIMENSION_MISSING",
                "severity": "warning",
                "dimension": required,
            })

    z = by_name.get("Z", {})
    z_min = _number(z.get("minimum"))
    z_max = _number(z.get("maximum"))
    z_range = None
    if z_min is not None and z_max is not None:
        z_range = z_max - z_min

    return {
        "status": "warning" if issues else "ready",
        "dimensions": by_name,
        "z_range": z_range,
        "issues": issues,
    }
