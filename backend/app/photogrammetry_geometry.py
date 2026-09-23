from __future__ import annotations

from math import cos, isfinite, radians, sin, sqrt
from typing import Any, Mapping

from .photogrammetry_geo import project_wgs84_positions, relative_geometry_height


_FULL_FRAME_DIAGONAL_MM = sqrt(36.0 ** 2 + 24.0 ** 2)
_NADIR_LIMIT_DEG = 20.0


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
    return parsed if parsed is not None and parsed > 0.0 else None


def estimate_nadir_geometry(
    file_metadata: Mapping[str, Any],
    photogrammetry: Mapping[str, Any],
) -> dict[str, Any]:
    image = file_metadata.get("image")
    image_data = image if isinstance(image, Mapping) else {}
    orientation = photogrammetry.get("orientation")
    orientation_data = orientation if isinstance(orientation, Mapping) else {}

    width = _positive(image_data.get("width"))
    height = _positive(image_data.get("height"))
    focal_mm = _positive(image_data.get("focal_length"))
    focal_35mm = _positive(image_data.get("focal_length_35mm"))

    missing = []
    if width is None:
        missing.append("image.width")
    if height is None:
        missing.append("image.height")
    if focal_mm is None:
        missing.append("image.focal_length")
    if focal_35mm is None:
        missing.append("image.focal_length_35mm")
    if missing:
        return {
            "status": "unavailable",
            "reason": "camera_geometry_missing",
            "missing": missing,
        }

    relative = relative_geometry_height(photogrammetry)
    if relative["status"] != "ready":
        return {
            "status": "unavailable",
            "reason": relative["reason"],
            "missing": [],
        }

    gimbal_pitch = _number(orientation_data.get("gimbal_pitch_deg"))
    if gimbal_pitch is None:
        return {
            "status": "unavailable",
            "reason": "gimbal_pitch_missing",
            "missing": ["orientation.gimbal_pitch_deg"],
        }
    nadir_deviation = abs(gimbal_pitch + 90.0)
    if nadir_deviation > _NADIR_LIMIT_DEG:
        return {
            "status": "unavailable",
            "reason": "gimbal_not_nadir",
            "nadir_deviation_deg": nadir_deviation,
            "limit_deg": _NADIR_LIMIT_DEG,
            "missing": [],
        }

    crop_factor = focal_35mm / focal_mm
    sensor_diagonal_mm = _FULL_FRAME_DIAGONAL_MM / crop_factor
    aspect = width / height
    sensor_height_mm = sensor_diagonal_mm / sqrt(aspect * aspect + 1.0)
    sensor_width_mm = sensor_height_mm * aspect

    flight_height_m = float(relative["value_m"])
    footprint_width_m = flight_height_m * sensor_width_mm / focal_mm
    footprint_height_m = flight_height_m * sensor_height_mm / focal_mm

    return {
        "status": "ready",
        "method": "exif_35mm_equivalent",
        "confidence": "estimated",
        "height_reference": "relative_takeoff",
        "height_m": flight_height_m,
        "nadir_deviation_deg": nadir_deviation,
        "sensor": {
            "width_mm": sensor_width_mm,
            "height_mm": sensor_height_mm,
            "diagonal_mm": sensor_diagonal_mm,
            "crop_factor": crop_factor,
        },
        "footprint": {
            "width_m": footprint_width_m,
            "height_m": footprint_height_m,
        },
        "gsd": {
            "x_cm_per_px": footprint_width_m / width * 100.0,
            "y_cm_per_px": footprint_height_m / height * 100.0,
        },
    }


def estimate_pair_overlap(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    target_crs: Any,
) -> dict[str, Any]:
    left_position = left.get("position")
    right_position = right.get("position")
    left_orientation = left.get("orientation")
    left_geometry = left.get("geometry")

    if not isinstance(left_position, Mapping) or not isinstance(right_position, Mapping):
        return {"status": "unavailable", "reason": "position_missing"}
    if not isinstance(left_orientation, Mapping):
        return {"status": "unavailable", "reason": "heading_missing"}
    if not isinstance(left_geometry, Mapping) or left_geometry.get("status") != "ready":
        return {"status": "unavailable", "reason": "left_geometry_unavailable"}

    heading = _number(
        left_orientation.get("gimbal_yaw_deg")
        if left_orientation.get("gimbal_yaw_deg") is not None
        else left_orientation.get("aircraft_yaw_deg")
    )
    if heading is None:
        return {"status": "unavailable", "reason": "heading_missing"}

    projected = project_wgs84_positions(
        [
            {"position": left_position},
            {"position": right_position},
        ],
        target_crs,
    )
    if len(projected) != 2:
        return {"status": "unavailable", "reason": "position_invalid"}

    east = projected[1]["x_m"] - projected[0]["x_m"]
    north = projected[1]["y_m"] - projected[0]["y_m"]
    angle = radians(heading)

    along_m = east * sin(angle) + north * cos(angle)
    cross_m = east * cos(angle) - north * sin(angle)

    footprint = left_geometry.get("footprint")
    if not isinstance(footprint, Mapping):
        return {"status": "unavailable", "reason": "footprint_missing"}
    along_size = _positive(footprint.get("height_m"))
    cross_size = _positive(footprint.get("width_m"))
    if along_size is None or cross_size is None:
        return {"status": "unavailable", "reason": "footprint_invalid"}

    forward = 1.0 - abs(along_m) / along_size
    side = 1.0 - abs(cross_m) / cross_size

    return {
        "status": "ready",
        "confidence": "estimated",
        "heading_source": (
            "gimbal_yaw_deg"
            if left_orientation.get("gimbal_yaw_deg") is not None
            else "aircraft_yaw_deg"
        ),
        "along_track_m": along_m,
        "cross_track_m": cross_m,
        "forward_overlap": max(0.0, min(1.0, forward)),
        "side_overlap": max(0.0, min(1.0, side)),
    }
