from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import cos, hypot, isfinite, radians, sin, sqrt
from statistics import median
from typing import Any

from .photogrammetry import fuse_photogrammetry_metadata


_FULL_FRAME_DIAGONAL_MM = sqrt(36.0**2 + 24.0**2)
_EARTH_RADIUS_M = 6_371_008.8
_MAX_NADIR_DEVIATION_DEG = 20.0
_MAX_PAIR_RESULTS = 500


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _positive_number(value: Any) -> float | None:
    parsed = _number(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _positive_int(value: Any) -> int | None:
    parsed = _positive_number(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def _time_ms(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = _number(value)
        return int(round(parsed)) if parsed is not None else None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    if (
        len(text) >= 19
        and text[4:5] == ":"
        and text[7:8] == ":"
        and text[10:11] in {" ", "T"}
    ):
        text = f"{text[:4]}-{text[5:7]}-{text[8:]}"

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return int(round(parsed.timestamp() * 1000.0))


def _capture_time_ms(canonical: dict[str, Any]) -> int | None:
    exposure = canonical["time"]["utc_at_exposure_ms"]
    if isinstance(exposure, int):
        return exposure
    return _time_ms(canonical["time"]["capture_time"])


def _clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, value))


def estimate_capture_geometry(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Estimate nadir footprint/GSD only from explicit image metadata.

    RelativeAltitude is treated as height above the DJI takeoff reference, not
    terrain AGL. Results are estimates and must not be interpreted as surveyed
    ground geometry.
    """

    metadata = _mapping(metadata)
    image = _mapping(metadata.get("image"))
    canonical = fuse_photogrammetry_metadata(metadata)

    width_px = _positive_int(image.get("width"))
    height_px = _positive_int(image.get("height"))
    focal_length_mm = _positive_number(image.get("focal_length"))
    focal_length_35mm = _positive_number(image.get("focal_length_35mm"))
    relative_height_m = _positive_number(canonical["height"]["relative_m"])
    gimbal_pitch = canonical["orientation"]["gimbal_pitch_deg"]

    reasons: list[str] = []
    if width_px is None or height_px is None:
        reasons.append("missing_image_dimensions")
    if focal_length_mm is None:
        reasons.append("missing_focal_length")
    if focal_length_35mm is None:
        reasons.append("missing_35mm_equivalent")
    if relative_height_m is None:
        reasons.append("missing_positive_relative_altitude")
    if not isinstance(gimbal_pitch, (int, float)):
        reasons.append("missing_gimbal_pitch")
    else:
        nadir_deviation = abs(float(gimbal_pitch) + 90.0)
        if nadir_deviation > _MAX_NADIR_DEVIATION_DEG:
            reasons.append("gimbal_not_nadir")

    if reasons:
        return {
            "status": "unavailable",
            "reasons": reasons,
            "method": None,
            "confidence": None,
            "height_reference": "relative_takeoff",
        }

    assert width_px is not None
    assert height_px is not None
    assert focal_length_mm is not None
    assert focal_length_35mm is not None
    assert relative_height_m is not None
    assert isinstance(gimbal_pitch, (int, float))

    crop_factor = focal_length_35mm / focal_length_mm
    if crop_factor <= 0:
        return {
            "status": "unavailable",
            "reasons": ["invalid_crop_factor"],
            "method": None,
            "confidence": None,
            "height_reference": "relative_takeoff",
        }

    sensor_diagonal_mm = _FULL_FRAME_DIAGONAL_MM / crop_factor
    aspect_ratio = width_px / height_px
    sensor_height_mm = sensor_diagonal_mm / sqrt(aspect_ratio**2 + 1.0)
    sensor_width_mm = sensor_height_mm * aspect_ratio

    footprint_width_m = relative_height_m * sensor_width_mm / focal_length_mm
    footprint_height_m = relative_height_m * sensor_height_mm / focal_length_mm
    gsd_x_cm_px = footprint_width_m / width_px * 100.0
    gsd_y_cm_px = footprint_height_m / height_px * 100.0
    gsd_cm_px = (gsd_x_cm_px + gsd_y_cm_px) / 2.0

    orientation = canonical["orientation"]
    heading = orientation["gimbal_yaw_deg"]
    heading_source = "gimbal_yaw"
    if not isinstance(heading, (int, float)):
        heading = orientation["aircraft_yaw_deg"]
        heading_source = "aircraft_yaw"
    if not isinstance(heading, (int, float)):
        heading = None
        heading_source = None

    return {
        "status": "available",
        "reasons": [],
        "method": "exif_35mm_equivalent",
        "confidence": "estimated",
        "height_reference": "relative_takeoff",
        "caveat": (
            "RelativeAltitude bezieht sich auf den DJI-Startreferenzpunkt und "
            "ist nicht automatisch Terrain-AGL."
        ),
        "image": {
            "width_px": width_px,
            "height_px": height_px,
            "aspect_ratio": round(aspect_ratio, 6),
        },
        "lens": {
            "focal_length_mm": round(focal_length_mm, 6),
            "focal_length_35mm": round(focal_length_35mm, 6),
            "crop_factor": round(crop_factor, 6),
        },
        "sensor_estimate": {
            "width_mm": round(sensor_width_mm, 6),
            "height_mm": round(sensor_height_mm, 6),
            "diagonal_mm": round(sensor_diagonal_mm, 6),
        },
        "relative_height_m": round(relative_height_m, 6),
        "nadir_deviation_deg": round(abs(float(gimbal_pitch) + 90.0), 6),
        "footprint": {
            "width_m": round(footprint_width_m, 6),
            "height_m": round(footprint_height_m, 6),
        },
        "gsd": {
            "x_cm_px": round(gsd_x_cm_px, 6),
            "y_cm_px": round(gsd_y_cm_px, 6),
            "mean_cm_px": round(gsd_cm_px, 6),
        },
        "heading_deg": round(float(heading), 6) if heading is not None else None,
        "heading_source": heading_source,
    }


def _local_displacement_m(
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    lat1, lon1 = map(radians, start)
    lat2, lon2 = map(radians, end)
    mean_lat = (lat1 + lat2) / 2.0
    north_m = (lat2 - lat1) * _EARTH_RADIUS_M
    east_m = (lon2 - lon1) * _EARTH_RADIUS_M * cos(mean_lat)
    return north_m, east_m


def _pair_overlap(
    start: dict[str, Any],
    end: dict[str, Any],
) -> dict[str, Any] | None:
    if end["time_ms"] <= start["time_ms"]:
        return None

    north_m, east_m = _local_displacement_m(
        start["position"],
        end["position"],
    )
    heading_rad = radians(start["geometry"]["heading_deg"])
    along_m = north_m * cos(heading_rad) + east_m * sin(heading_rad)
    cross_m = -north_m * sin(heading_rad) + east_m * cos(heading_rad)

    along_footprint_m = (
        start["geometry"]["footprint"]["height_m"]
        + end["geometry"]["footprint"]["height_m"]
    ) / 2.0
    cross_footprint_m = (
        start["geometry"]["footprint"]["width_m"]
        + end["geometry"]["footprint"]["width_m"]
    ) / 2.0

    forward_overlap = _clamp_percent(
        (1.0 - abs(along_m) / along_footprint_m) * 100.0
    )
    side_overlap = _clamp_percent(
        (1.0 - abs(cross_m) / cross_footprint_m) * 100.0
    )

    return {
        "from": start["relative_path"],
        "to": end["relative_path"],
        "delta_time_s": round((end["time_ms"] - start["time_ms"]) / 1000.0, 3),
        "distance_m": round(hypot(north_m, east_m), 3),
        "along_track_m": round(along_m, 3),
        "cross_track_m": round(cross_m, 3),
        "heading_deg": start["geometry"]["heading_deg"],
        "heading_source": start["geometry"]["heading_source"],
        "forward_overlap_percent": round(forward_overlap, 2),
        "side_overlap_percent": round(side_overlap, 2),
    }


def evaluate_mapping_geometry(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate footprint/GSD and sequential overlap diagnostics."""

    available: list[dict[str, Any]] = []
    unavailable_reasons: Counter[str] = Counter()
    gsd_values: list[float] = []
    footprint_widths: list[float] = []
    footprint_heights: list[float] = []

    for item in files:
        metadata = _mapping(item.get("metadata"))
        canonical = fuse_photogrammetry_metadata(metadata)
        geometry = estimate_capture_geometry(metadata)
        if geometry["status"] != "available":
            unavailable_reasons.update(geometry["reasons"])
            continue

        gsd_values.append(geometry["gsd"]["mean_cm_px"])
        footprint_widths.append(geometry["footprint"]["width_m"])
        footprint_heights.append(geometry["footprint"]["height_m"])

        latitude = canonical["position"]["latitude_deg"]
        longitude = canonical["position"]["longitude_deg"]
        time_ms = _capture_time_ms(canonical)
        if (
            isinstance(latitude, (int, float))
            and isinstance(longitude, (int, float))
            and isinstance(time_ms, int)
            and geometry["heading_deg"] is not None
        ):
            available.append(
                {
                    "relative_path": item["relative_path"],
                    "position": (float(latitude), float(longitude)),
                    "time_ms": time_ms,
                    "geometry": geometry,
                }
            )

    available.sort(key=lambda item: (item["time_ms"], item["relative_path"]))

    pairs: list[dict[str, Any]] = []
    skipped_nonincreasing_time_pairs = 0
    for start, end in zip(available, available[1:]):
        pair = _pair_overlap(start, end)
        if pair is None:
            skipped_nonincreasing_time_pairs += 1
            continue
        pairs.append(pair)

    forward_values = [item["forward_overlap_percent"] for item in pairs]
    side_values = [item["side_overlap_percent"] for item in pairs]
    pair_results_truncated = len(pairs) > _MAX_PAIR_RESULTS
    returned_pairs = pairs[:_MAX_PAIR_RESULTS]

    geometry_available = len(gsd_values)
    total = len(files)
    status = (
        "unavailable"
        if geometry_available == 0
        else "partial"
        if geometry_available < total
        else "available"
    )

    overlap_status = (
        "available"
        if pairs
        else "unavailable"
    )
    overlap_reasons: list[str] = []
    if not pairs:
        if len(available) < 2:
            overlap_reasons.append(
                "need_two_images_with_geometry_gps_time_and_heading"
            )
        if skipped_nonincreasing_time_pairs:
            overlap_reasons.append("non_increasing_capture_time")

    return {
        "status": status,
        "method": "exif_35mm_equivalent",
        "confidence": "estimated" if geometry_available else None,
        "height_reference": "relative_takeoff",
        "input_images": total,
        "geometry_available_images": geometry_available,
        "geometry_unavailable_images": total - geometry_available,
        "unavailable_reasons": dict(unavailable_reasons),
        "gsd_cm_px": {
            "count": len(gsd_values),
            "min": round(min(gsd_values), 6) if gsd_values else None,
            "max": round(max(gsd_values), 6) if gsd_values else None,
            "median": round(median(gsd_values), 6) if gsd_values else None,
        },
        "footprint_width_m": {
            "count": len(footprint_widths),
            "min": round(min(footprint_widths), 6) if footprint_widths else None,
            "max": round(max(footprint_widths), 6) if footprint_widths else None,
            "median": round(median(footprint_widths), 6) if footprint_widths else None,
        },
        "footprint_height_m": {
            "count": len(footprint_heights),
            "min": round(min(footprint_heights), 6) if footprint_heights else None,
            "max": round(max(footprint_heights), 6) if footprint_heights else None,
            "median": round(median(footprint_heights), 6) if footprint_heights else None,
        },
        "overlap": {
            "status": overlap_status,
            "reasons": overlap_reasons,
            "candidate_images": len(available),
            "evaluated_pairs": len(pairs),
            "skipped_nonincreasing_time_pairs": skipped_nonincreasing_time_pairs,
            "forward_percent": {
                "min": min(forward_values) if forward_values else None,
                "max": max(forward_values) if forward_values else None,
                "median": median(forward_values) if forward_values else None,
            },
            "side_percent": {
                "min": min(side_values) if side_values else None,
                "max": max(side_values) if side_values else None,
                "median": median(side_values) if side_values else None,
            },
            "pair_results_truncated": pair_results_truncated,
            "pairs": returned_pairs,
        },
    }
