from __future__ import annotations

from math import isfinite
from typing import Any, Iterable, Mapping

from pyproj import CRS, Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info


WGS84_2D = CRS.from_epsg(4326)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _position(item: Mapping[str, Any]) -> tuple[float, float] | None:
    position = item.get("position")
    source: Mapping[str, Any]
    if isinstance(position, Mapping):
        source = position
    else:
        source = item

    latitude = _finite_number(source.get("latitude_deg"))
    longitude = _finite_number(source.get("longitude_deg"))
    if latitude is None or longitude is None:
        return None
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        return None
    return latitude, longitude


def _valid_positions(
    items: Iterable[Mapping[str, Any]],
) -> list[tuple[float, float]]:
    return [
        position
        for item in items
        if (position := _position(item)) is not None
    ]


def suggest_projected_crs(
    items: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Suggest one WGS84 UTM CRS that contains the complete dataset.

    The function is intentionally conservative. It never chooses an arbitrary
    UTM zone when the dataset crosses zone boundaries or the antimeridian.
    """

    positions = _valid_positions(items)
    if not positions:
        return {
            "status": "blocked",
            "reason": "no_valid_wgs84_positions",
            "crs": None,
            "candidate_crs": [],
            "bounds_wgs84": None,
        }

    latitudes = [latitude for latitude, _ in positions]
    longitudes = [longitude for _, longitude in positions]
    west = min(longitudes)
    east = max(longitudes)
    south = min(latitudes)
    north = max(latitudes)

    if east - west > 180.0:
        return {
            "status": "blocked",
            "reason": "antimeridian_dataset_not_supported",
            "crs": None,
            "candidate_crs": [],
            "bounds_wgs84": [west, south, east, north],
        }

    if south < -80.0 or north > 84.0:
        return {
            "status": "blocked",
            "reason": "outside_utm_latitude_range",
            "crs": None,
            "candidate_crs": [],
            "bounds_wgs84": [west, south, east, north],
        }

    area = AreaOfInterest(
        west_lon_degree=west,
        south_lat_degree=south,
        east_lon_degree=east,
        north_lat_degree=north,
    )
    contained = query_utm_crs_info(
        datum_name="WGS 84",
        area_of_interest=area,
        contains=True,
    )
    candidates = [
        f"{info.auth_name}:{info.code}"
        for info in query_utm_crs_info(
            datum_name="WGS 84",
            area_of_interest=area,
            contains=False,
        )
    ]

    unique_contained = {
        (info.auth_name, str(info.code), info.name)
        for info in contained
    }
    if len(unique_contained) != 1:
        return {
            "status": "blocked",
            "reason": (
                "projected_crs_ambiguous"
                if unique_contained
                else "no_single_utm_crs_contains_dataset"
            ),
            "crs": None,
            "candidate_crs": sorted(set(candidates)),
            "bounds_wgs84": [west, south, east, north],
        }

    authority, code, name = next(iter(unique_contained))
    crs = CRS.from_authority(authority, code)
    return {
        "status": "ready",
        "reason": None,
        "crs": {
            "authority": authority,
            "code": code,
            "identifier": f"{authority}:{code}",
            "name": name,
            "is_projected": crs.is_projected,
            "axis_units": [axis.unit_name for axis in crs.axis_info],
        },
        "candidate_crs": sorted(set(candidates)),
        "bounds_wgs84": [west, south, east, north],
    }


def _metric_projected_crs(value: Any) -> CRS:
    crs = CRS.from_user_input(value)
    if not crs.is_projected:
        raise ValueError("Target CRS must be projected.")
    if not crs.axis_info:
        raise ValueError("Target CRS has no axis information.")
    for axis in crs.axis_info[:2]:
        if axis.unit_name not in {"metre", "meter"}:
            raise ValueError("Target CRS must use metre axes.")
    return crs


def project_wgs84_positions(
    items: Iterable[Mapping[str, Any]],
    target_crs: Any,
) -> list[dict[str, float]]:
    """Project valid WGS84 positions to a metric projected CRS.

    Height is deliberately not transformed or attached here. Horizontal CRS
    transformation and vertical reference semantics remain separate.
    """

    positions = _valid_positions(items)
    crs = _metric_projected_crs(target_crs)
    transformer = Transformer.from_crs(
        WGS84_2D,
        crs,
        always_xy=True,
        allow_ballpark=False,
        only_best=True,
    )

    result: list[dict[str, float]] = []
    for latitude, longitude in positions:
        x, y = transformer.transform(longitude, latitude)
        if not isfinite(x) or not isfinite(y):
            raise ValueError("Coordinate transformation produced non-finite output.")
        result.append(
            {
                "latitude_deg": latitude,
                "longitude_deg": longitude,
                "x_m": float(x),
                "y_m": float(y),
            }
        )
    return result


def absolute_georeference_height(
    photogrammetry_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Return only a semantically explicit absolute height candidate.

    Generic EXIF GPS altitude and DJI RelativeAltitude are intentionally never
    promoted to absolute Z.
    """

    height = photogrammetry_metadata.get("height")
    source = height if isinstance(height, Mapping) else {}
    ellipsoid = _finite_number(source.get("ellipsoid_m"))
    if ellipsoid is None:
        return {
            "status": "unavailable",
            "value_m": None,
            "reference": None,
            "source_field": None,
            "reason": "ellipsoid_height_missing",
        }

    return {
        "status": "ready",
        "value_m": ellipsoid,
        "reference": "wgs84_ellipsoidal",
        "source_field": "height.ellipsoid_m",
        "reason": None,
    }


def relative_geometry_height(
    photogrammetry_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Return positive takeoff-relative height for footprint/GSD estimation."""

    height = photogrammetry_metadata.get("height")
    source = height if isinstance(height, Mapping) else {}
    relative = _finite_number(source.get("relative_m"))
    if relative is None:
        return {
            "status": "unavailable",
            "value_m": None,
            "reference": None,
            "source_field": None,
            "reason": "relative_height_missing",
        }
    if relative <= 0.0:
        return {
            "status": "unavailable",
            "value_m": None,
            "reference": None,
            "source_field": None,
            "reason": "relative_height_not_positive",
        }

    return {
        "status": "ready",
        "value_m": relative,
        "reference": "relative_takeoff",
        "source_field": "height.relative_m",
        "reason": None,
    }
