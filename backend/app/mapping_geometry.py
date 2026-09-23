from __future__ import annotations

from datetime import datetime, timezone
from math import cos, isfinite, radians, sin, sqrt
from statistics import median
from typing import Any

from .photogrammetry import fuse_photogrammetry_metadata


_FULL_FRAME_DIAGONAL_MM = sqrt(36.0 ** 2 + 24.0 ** 2)
_EARTH_RADIUS_M = 6_371_008.8
_NADIR_TOLERANCE_DEG = 20.0


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


def _positive(value: Any) -> float | None:
    parsed = _number(value)
    if parsed is None or parsed <= 0.0:
        return None
    return parsed


def _positive_int(value: Any) -> int | None:
    parsed = _positive(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def _capture_time_ms(metadata: dict[str, Any], canonical: dict[str, Any]) -> int | None:
    exposure = canonical["time"]["utc_at_exposure_ms"]
    if isinstance(exposure, int):
        return exposure

    value = canonical["time"]["capture_time"] or metadata.get("capture_time")
    if not value:
        return None
    text = str(value).strip()
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


def _range(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "min": round(min(values), 6) if values else None,
        "max": round(max(values), 6) if values else None,
        "median": round(median(values), 6) if values else None,
    }


def estimate_capture_geometry(
    metadata: dict[str, Any] | None,
    fh2_media: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate nadir camera footprint and GSD from file-contained geometry.

    The result deliberately uses canonical relative height as relative-to-takeoff
    height, not terrain AGL. It is therefore an estimated capture geometry,
    never a terrain-accurate footprint.
    """

    data = _mapping(metadata)
    image = _mapping(data.get("image"))
    canonical = fuse_photogrammetry_metadata(data, fh2_media)
    orientation = canonical["orientation"]

    width = _positive_int(image.get("width"))
    height = _positive_int(image.get("height"))
    focal_mm = _positive(image.get("focal_length"))
    focal_35mm = _positive(image.get("focal_length_35mm"))
    relative_height_m = _positive(canonical["height"]["relative_m"])
    gimbal_pitch = _number(orientation["gimbal_pitch_deg"])

    reasons: list[str] = []
    if width is None or height is None:
        reasons.append("missing_image_dimensions")
    if focal_mm is None:
        reasons.append("missing_focal_length")
    if focal_35mm is None:
        reasons.append("missing_focal_length_35mm")
    if canonical["height"]["relative_m"] is None:
        reasons.append("missing_relative_altitude")
    elif relative_height_m is None:
        reasons.append("nonpositive_relative_altitude")
    if gimbal_pitch is None:
        reasons.append("missing_gimbal_pitch")
    elif abs(gimbal_pitch + 90.0) > _NADIR_TOLERANCE_DEG:
        reasons.append("oblique_gimbal")

    if reasons:
        return {
            "status": "unavailable",
            "method": "exif_35mm_equivalent",
            "height_reference": "relative_takeoff",
            "confidence": "estimated",
            "reasons": reasons,
        }

    assert width is not None
    assert height is not None
    assert focal_mm is not None
    assert focal_35mm is not None
    assert relative_height_m is not None

    crop_factor = focal_35mm / focal_mm
    sensor_diagonal_mm = _FULL_FRAME_DIAGONAL_MM / crop_factor
    image_diagonal_px = sqrt(float(width * width + height * height))
    sensor_width_mm = sensor_diagonal_mm * width / image_diagonal_px
    sensor_height_mm = sensor_diagonal_mm * height / image_diagonal_px

    footprint_width_m = relative_height_m * sensor_width_mm / focal_mm
    footprint_height_m = relative_height_m * sensor_height_mm / focal_mm
    gsd_x_cm_px = footprint_width_m / width * 100.0
    gsd_y_cm_px = footprint_height_m / height * 100.0
    gsd_cm_px = (gsd_x_cm_px + gsd_y_cm_px) / 2.0

    return {
        "status": "available",
        "method": "exif_35mm_equivalent",
        "height_reference": "relative_takeoff",
        "confidence": "estimated",
        "reasons": [],
        "image_width_px": width,
        "image_height_px": height,
        "focal_length_mm": round(focal_mm, 6),
        "focal_length_35mm": round(focal_35mm, 6),
        "relative_height_m": round(relative_height_m, 6),
        "gimbal_pitch_deg": round(float(gimbal_pitch), 6),
        "sensor_width_mm": round(sensor_width_mm, 6),
        "sensor_height_mm": round(sensor_height_mm, 6),
        "footprint_width_m": round(footprint_width_m, 6),
        "footprint_height_m": round(footprint_height_m, 6),
        "gsd_x_cm_px": round(gsd_x_cm_px, 6),
        "gsd_y_cm_px": round(gsd_y_cm_px, 6),
        "gsd_cm_px": round(gsd_cm_px, 6),
    }


def _local_displacement_m(
    left: tuple[float, float],
    right: tuple[float, float],
) -> tuple[float, float]:
    lat1, lon1 = map(radians, left)
    lat2, lon2 = map(radians, right)
    mean_lat = (lat1 + lat2) / 2.0
    north_m = (lat2 - lat1) * _EARTH_RADIUS_M
    east_m = (lon2 - lon1) * _EARTH_RADIUS_M * cos(mean_lat)
    return north_m, east_m


def _pair_overlap(
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, Any] | None:
    left_position = left.get("position")
    right_position = right.get("position")
    if left_position is None or right_position is None:
        return None

    heading = left.get("heading_deg")
    if heading is None:
        return None

    north_m, east_m = _local_displacement_m(left_position, right_position)
    heading_rad = radians(float(heading))
    along_m = north_m * cos(heading_rad) + east_m * sin(heading_rad)
    cross_m = -north_m * sin(heading_rad) + east_m * cos(heading_rad)

    footprint_height_m = (
        left["geometry"]["footprint_height_m"]
        + right["geometry"]["footprint_height_m"]
    ) / 2.0
    footprint_width_m = (
        left["geometry"]["footprint_width_m"]
        + right["geometry"]["footprint_width_m"]
    ) / 2.0

    forward_overlap = max(
        0.0,
        min(100.0, (1.0 - abs(along_m) / footprint_height_m) * 100.0),
    )
    side_overlap = max(
        0.0,
        min(100.0, (1.0 - abs(cross_m) / footprint_width_m) * 100.0),
    )

    return {
        "from": left["relative_path"],
        "to": right["relative_path"],
        "delta_time_ms": right["capture_time_ms"] - left["capture_time_ms"],
        "heading_deg": round(float(heading), 6),
        "heading_source": left["heading_source"],
        "north_m": round(north_m, 6),
        "east_m": round(east_m, 6),
        "along_track_m": round(along_m, 6),
        "cross_track_m": round(cross_m, 6),
        "forward_overlap_percent": round(forward_overlap, 3),
        "side_overlap_percent": round(side_overlap, 3),
    }


def evaluate_mapping_geometry(files: list[dict[str, Any]]) -> dict[str, Any]:
    captures: list[dict[str, Any]] = []
    available: list[dict[str, Any]] = []
    unavailable_reason_counts: dict[str, int] = {}

    for item in files:
        metadata = _mapping(item.get("metadata"))
        fh2_media = _mapping(item.get("fh2_media"))
        canonical = fuse_photogrammetry_metadata(
            metadata,
            fh2_media or None,
        )
        geometry = estimate_capture_geometry(
            metadata,
            fh2_media or None,
        )
        capture: dict[str, Any] = {
            "relative_path": item["relative_path"],
            "geometry": geometry,
        }

        if geometry["status"] != "available":
            for reason in geometry["reasons"]:
                unavailable_reason_counts[reason] = (
                    unavailable_reason_counts.get(reason, 0) + 1
                )
            captures.append(capture)
            continue

        latitude = canonical["position"]["latitude_deg"]
        longitude = canonical["position"]["longitude_deg"]
        if isinstance(latitude, (int, float)) and isinstance(
            longitude,
            (int, float),
        ):
            capture["position"] = (float(latitude), float(longitude))

        orientation = canonical["orientation"]
        gimbal_yaw = orientation["gimbal_yaw_deg"]
        aircraft_yaw = orientation["aircraft_yaw_deg"]
        if isinstance(gimbal_yaw, (int, float)):
            capture["heading_deg"] = float(gimbal_yaw)
            capture["heading_source"] = "gimbal_yaw"
        elif isinstance(aircraft_yaw, (int, float)):
            capture["heading_deg"] = float(aircraft_yaw)
            capture["heading_source"] = "aircraft_yaw"

        capture_time_ms = _capture_time_ms(metadata, canonical)
        if capture_time_ms is not None:
            capture["capture_time_ms"] = capture_time_ms

        captures.append(capture)
        available.append(capture)

    gsd_values = [
        float(item["geometry"]["gsd_cm_px"])
        for item in available
    ]
    footprint_widths = [
        float(item["geometry"]["footprint_width_m"])
        for item in available
    ]
    footprint_heights = [
        float(item["geometry"]["footprint_height_m"])
        for item in available
    ]

    sequential = [
        item
        for item in available
        if item.get("position") is not None
        and item.get("heading_deg") is not None
        and item.get("capture_time_ms") is not None
    ]
    sequential.sort(key=lambda item: item["capture_time_ms"])

    pairs: list[dict[str, Any]] = []
    for left, right in zip(sequential, sequential[1:]):
        pair = _pair_overlap(left, right)
        if pair is not None:
            pairs.append(pair)

    forward = [float(pair["forward_overlap_percent"]) for pair in pairs]
    side = [float(pair["side_overlap_percent"]) for pair in pairs]

    overlap_reasons: list[str] = []
    if len(available) < 2:
        overlap_reasons.append("insufficient_geometry")
    if len(sequential) < 2:
        if sum(1 for item in available if item.get("position") is not None) < 2:
            overlap_reasons.append("missing_gps")
        if sum(1 for item in available if item.get("heading_deg") is not None) < 2:
            overlap_reasons.append("missing_heading")
        if sum(1 for item in available if item.get("capture_time_ms") is not None) < 2:
            overlap_reasons.append("missing_capture_time")
    if not pairs and not overlap_reasons:
        overlap_reasons.append("no_sequential_pairs")

    return {
        "status": "available" if available else "unavailable",
        "method": "exif_35mm_equivalent",
        "height_reference": "relative_takeoff",
        "confidence": "estimated",
        "eligible_images": len(files),
        "available_images": len(available),
        "unavailable_images": len(files) - len(available),
        "unavailable_reasons": unavailable_reason_counts,
        "gsd_cm_px": _range(gsd_values),
        "footprint_width_m": _range(footprint_widths),
        "footprint_height_m": _range(footprint_heights),
        "overlap": {
            "status": "available" if pairs else "unavailable",
            "pair_count": len(pairs),
            "reasons": overlap_reasons,
            "forward_percent": _range(forward),
            "side_percent": _range(side),
            "pairs": pairs,
        },
        "captures": captures,
        "note": (
            "Relative height is relative to takeoff, not terrain AGL; "
            "GSD, footprint and overlap are estimates."
        ),
    }
