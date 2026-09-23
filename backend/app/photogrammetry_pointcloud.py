from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from pyproj import CRS
from pyproj.exceptions import CRSError


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


def _int_number(value: Any) -> int | None:
    parsed = _number(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def _normalize_srs(value: Any) -> dict[str, Any] | None:
    if value in (None, ""):
        return None

    raw: dict[str, Any]
    if isinstance(value, Mapping):
        raw = dict(value)
        candidate = (
            raw.get("compoundwkt")
            or raw.get("wkt")
            or raw.get("horizontal")
            or raw.get("proj4")
        )
    else:
        raw = {"text": str(value)}
        candidate = str(value)

    crs = None
    if candidate not in (None, ""):
        try:
            crs = CRS.from_user_input(candidate)
        except (CRSError, ValueError):
            crs = None

    units = raw.get("units")
    units_map = units if isinstance(units, Mapping) else {}

    if crs is None:
        return {
            "identifier": None,
            "epsg": None,
            "name": None,
            "projected": None,
            "geographic": None,
            "horizontal_units": units_map.get("horizontal"),
            "vertical_units": units_map.get("vertical"),
            "wkt": raw.get("compoundwkt") or raw.get("wkt"),
            "proj4": raw.get("proj4"),
            "raw": raw,
        }

    authority = crs.to_authority()
    axis_units = [
        axis.unit_name
        for axis in crs.axis_info
        if getattr(axis, "unit_name", None)
    ]
    return {
        "identifier": (
            f"{authority[0]}:{authority[1]}"
            if authority
            else crs.to_string()
        ),
        "epsg": crs.to_epsg(),
        "name": crs.name,
        "projected": bool(crs.is_projected),
        "geographic": bool(crs.is_geographic),
        "horizontal_units": (
            axis_units[0]
            if axis_units
            else units_map.get("horizontal")
        ),
        "vertical_units": units_map.get("vertical"),
        "wkt": crs.to_wkt(),
        "proj4": raw.get("proj4"),
        "raw": raw,
    }


def _metric_horizontal_srs(srs: Mapping[str, Any] | None) -> bool:
    if not srs or srs.get("projected") is not True:
        return False
    unit = str(srs.get("horizontal_units") or "").strip().lower()
    return unit in {"metre", "meter", "metres", "meters", "m"}


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

    count = _int_number(source.get("num_points"))
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

    raw_srs = (
        source.get("srs")
        or source.get("spatialreference")
        or metadata_map.get("srs")
        or metadata_map.get("spatialreference")
    )
    srs = _normalize_srs(raw_srs)

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
        issues.append(
            {"code": "POINTCLOUD_XY_EXTENT_DEGENERATE", "severity": "error"}
        )

    if srs is None:
        issues.append({"code": "POINTCLOUD_CRS_MISSING", "severity": "warning"})
    elif srs.get("projected") is None:
        issues.append(
            {"code": "POINTCLOUD_CRS_UNRESOLVED", "severity": "warning"}
        )
    elif srs.get("projected") is False:
        issues.append(
            {"code": "POINTCLOUD_CRS_NOT_PROJECTED", "severity": "warning"}
        )

    status = (
        "blocked"
        if any(issue["severity"] == "error" for issue in issues)
        else "warning"
        if issues
        else "ready"
    )

    density_xy = None
    density_unit = None
    if count and bounds_valid:
        area = (
            (parsed_bounds["maxx"] - parsed_bounds["minx"])
            * (parsed_bounds["maxy"] - parsed_bounds["miny"])
        )
        if area > 0:
            density_xy = count / area
            density_unit = (
                "points_per_square_metre"
                if _metric_horizontal_srs(srs)
                else "points_per_square_crs_unit"
            )

    return {
        "status": status,
        "point_count": count,
        "bounds": parsed_bounds if bounds_valid else None,
        "dimensions": dimensions,
        "srs": srs,
        "density_xy": density_xy,
        "density_unit": density_unit,
        "reader": payload.get("reader"),
        "pdal_version": payload.get("pdal_version"),
        "issues": issues,
    }


def _normalize_counts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        record = dict(item)
        count = _int_number(record.get("count"))
        if count is not None:
            record["count"] = count
        numeric = _number(record.get("value"))
        if numeric is not None:
            record["value"] = int(numeric) if numeric.is_integer() else numeric
        result.append(record)
    return result


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
        for key in ("minimum", "maximum", "average", "stddev", "variance"):
            value = _number(item.get(key))
            if value is not None:
                record[key] = value
        count = _int_number(item.get("count"))
        if count is not None:
            record["count"] = count
        counts = _normalize_counts(item.get("counts"))
        if counts:
            record["counts"] = counts
        by_name[name] = record

    issues: list[dict[str, Any]] = []
    for required in ("X", "Y", "Z"):
        record = by_name.get(required)
        if record is None:
            issues.append(
                {
                    "code": "POINTCLOUD_STATS_DIMENSION_MISSING",
                    "severity": "warning",
                    "dimension": required,
                }
            )
            continue

        minimum = _number(record.get("minimum"))
        maximum = _number(record.get("maximum"))
        if minimum is None or maximum is None or maximum < minimum:
            issues.append(
                {
                    "code": "POINTCLOUD_STATS_DIMENSION_INVALID",
                    "severity": "warning",
                    "dimension": required,
                }
            )

    z = by_name.get("Z", {})
    z_min = _number(z.get("minimum"))
    z_max = _number(z.get("maximum"))
    z_range = None
    if z_min is not None and z_max is not None and z_max >= z_min:
        z_range = z_max - z_min

    return {
        "status": "warning" if issues else "ready",
        "dimensions": by_name,
        "z_range": z_range,
        "classification_counts": by_name.get("Classification", {}).get(
            "counts", []
        ),
        "issues": issues,
    }
