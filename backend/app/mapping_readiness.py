from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import asin, cos, isfinite, radians, sin, sqrt
from statistics import median
from typing import Any

from .photogrammetry import fuse_photogrammetry_metadata


_EARTH_RADIUS_M = 6_371_008.8
_POSITION_ROUND_DIGITS = 7
_SPATIAL_DEGENERATE_M = 0.5
_FOCAL_SPREAD_WARNING_PCT = 2.0
_HEIGHT_OFFSET_SPREAD_WARNING_M = 2.0
_NADIR_WARNING_DEG = 20.0
_NADIR_STRONG_WARNING_DEG = 45.0


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


def _positive_int(value: Any) -> int | None:
    parsed = _number(value)
    if parsed is None or not parsed.is_integer() or parsed <= 0:
        return None
    return int(parsed)


def _capture_time_ms(value: Any) -> int | None:
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


def _distance_m(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    lat1, lon1 = map(radians, left)
    lat2, lon2 = map(radians, right)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = (
        sin(dlat / 2.0) ** 2
        + cos(lat1) * cos(lat2) * sin(dlon / 2.0) ** 2
    )
    return 2.0 * _EARTH_RADIUS_M * asin(min(1.0, sqrt(value)))


def _position_extent_m(
    positions: list[tuple[float, float]],
) -> float | None:
    if len(positions) < 2:
        return None
    min_lat = min(position[0] for position in positions)
    max_lat = max(position[0] for position in positions)
    min_lon = min(position[1] for position in positions)
    max_lon = max(position[1] for position in positions)
    return _distance_m((min_lat, min_lon), (max_lat, max_lon))


def _range(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def _issue(
    issues: list[dict[str, Any]],
    code: str,
    severity: str,
    count: int,
    message: str,
    **details: Any,
) -> None:
    item: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "count": count,
        "message": message,
    }
    item.update(details)
    issues.append(item)


def evaluate_mapping_readiness(
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate RGB/WIDE mapping metadata without changing engine job gates."""

    eligible_images = len(files)
    valid_positions: list[tuple[float, float]] = []
    missing_gps = 0
    invalid_gps = 0
    rtk_metadata_images = 0
    rtk_fixed_images = 0
    orientation_metadata_images = 0
    metadata_errors = 0

    camera_models: Counter[str] = Counter()
    dimensions: Counter[str] = Counter()
    focal_lengths: list[float] = []
    takeoff_offsets: list[float] = []
    nonpositive_relative_altitudes = 0

    gimbal_pitch_images = 0
    near_nadir_images = 0
    oblique_images = 0
    strongly_oblique_images = 0
    nadir_deviations: list[float] = []

    capture_times_ms: list[int] = []

    for item in files:
        metadata = _mapping(item.get("metadata"))
        gps = _mapping(metadata.get("gps"))
        camera = _mapping(metadata.get("camera"))
        image = _mapping(metadata.get("image"))
        canonical = fuse_photogrammetry_metadata(metadata)

        raw_latitude = gps.get("latitude")
        raw_longitude = gps.get("longitude")
        latitude = canonical["position"]["latitude_deg"]
        longitude = canonical["position"]["longitude_deg"]

        if raw_latitude in (None, "") or raw_longitude in (None, ""):
            missing_gps += 1
        elif latitude is None or longitude is None:
            invalid_gps += 1
        else:
            valid_positions.append((float(latitude), float(longitude)))

        model = camera.get("model")
        if isinstance(model, str) and model.strip():
            camera_models[model.strip()] += 1

        width = _positive_int(image.get("width"))
        height = _positive_int(image.get("height"))
        if width is not None and height is not None:
            dimensions[f"{width}x{height}"] += 1

        focal_length = _number(image.get("focal_length"))
        if focal_length is not None and focal_length > 0:
            focal_lengths.append(focal_length)

        ellipsoid_m = canonical["height"]["ellipsoid_m"]
        relative_m = canonical["height"]["relative_m"]
        if isinstance(ellipsoid_m, (int, float)) and isinstance(
            relative_m,
            (int, float),
        ):
            takeoff_offsets.append(float(ellipsoid_m) - float(relative_m))
        if isinstance(relative_m, (int, float)) and float(relative_m) <= 0.0:
            nonpositive_relative_altitudes += 1

        orientation = canonical["orientation"]
        orientation_values = (
            orientation["aircraft_yaw_deg"],
            orientation["aircraft_pitch_deg"],
            orientation["aircraft_roll_deg"],
            orientation["gimbal_yaw_deg"],
            orientation["gimbal_pitch_deg"],
            orientation["gimbal_roll_deg"],
        )
        if all(value is not None for value in orientation_values):
            orientation_metadata_images += 1

        gimbal_pitch = orientation["gimbal_pitch_deg"]
        if isinstance(gimbal_pitch, (int, float)):
            gimbal_pitch_images += 1
            deviation = abs(float(gimbal_pitch) + 90.0)
            nadir_deviations.append(deviation)
            if deviation <= _NADIR_WARNING_DEG:
                near_nadir_images += 1
            else:
                oblique_images += 1
                if deviation > _NADIR_STRONG_WARNING_DEG:
                    strongly_oblique_images += 1

        rtk = canonical["rtk"]
        if rtk["raw_flag"] is not None or rtk["fixed"] is not None:
            rtk_metadata_images += 1
        if rtk["fixed"] is True:
            rtk_fixed_images += 1

        exposure_ms = canonical["time"]["utc_at_exposure_ms"]
        if isinstance(exposure_ms, int):
            capture_times_ms.append(exposure_ms)
        else:
            fallback_ms = _capture_time_ms(canonical["time"]["capture_time"])
            if fallback_ms is not None:
                capture_times_ms.append(fallback_ms)

        if item.get("scan_error"):
            metadata_errors += 1

    position_keys = [
        (
            round(latitude, _POSITION_ROUND_DIGITS),
            round(longitude, _POSITION_ROUND_DIGITS),
        )
        for latitude, longitude in valid_positions
    ]
    unique_positions = len(set(position_keys))
    duplicate_position_images = max(len(position_keys) - unique_positions, 0)
    position_extent_m = _position_extent_m(valid_positions)

    focal_spread_pct: float | None = None
    if len(focal_lengths) >= 2:
        center = median(focal_lengths)
        if center > 0:
            focal_spread_pct = (
                (max(focal_lengths) - min(focal_lengths)) / center * 100.0
            )

    takeoff_offset_spread_m: float | None = None
    if len(takeoff_offsets) >= 2:
        takeoff_offset_spread_m = max(takeoff_offsets) - min(takeoff_offsets)

    duplicate_capture_times = max(
        len(capture_times_ms) - len(set(capture_times_ms)),
        0,
    )
    capture_span_seconds: float | None = None
    if len(capture_times_ms) >= 2:
        capture_span_seconds = (
            max(capture_times_ms) - min(capture_times_ms)
        ) / 1000.0

    issues: list[dict[str, Any]] = []

    if eligible_images < 2:
        _issue(
            issues,
            "MAPPING_TOO_FEW_IMAGES",
            "error",
            eligible_images,
            "Mindestens zwei RGB/WIDE-Bilder sind erforderlich.",
            minimum_images=2,
        )
    if missing_gps:
        _issue(
            issues,
            "MAPPING_MISSING_GPS",
            "warning",
            missing_gps,
            f"{missing_gps} Mapping-Bild(er) ohne vollständige GPS-Koordinaten.",
        )
    if invalid_gps:
        _issue(
            issues,
            "MAPPING_INVALID_GPS",
            "warning",
            invalid_gps,
            f"{invalid_gps} Mapping-Bild(er) mit ungültigen GPS-Koordinaten.",
        )
    if duplicate_position_images:
        _issue(
            issues,
            "MAPPING_DUPLICATE_POSITIONS",
            "warning",
            duplicate_position_images,
            (
                f"{duplicate_position_images} Mapping-Bild(er) teilen eine bereits "
                "vorhandene GPS-Position."
            ),
            unique_positions=unique_positions,
        )
    if (
        len(valid_positions) >= 2
        and position_extent_m is not None
        and position_extent_m < _SPATIAL_DEGENERATE_M
    ):
        _issue(
            issues,
            "MAPPING_SPATIAL_DEGENERATE",
            "warning",
            len(valid_positions),
            (
                "Die gültigen GPS-Positionen liegen räumlich nahezu am selben Ort; "
                "eine belastbare Aufnahmebaseline ist aus den Metadaten nicht erkennbar."
            ),
            position_extent_m=round(position_extent_m, 3),
        )
    if len(camera_models) > 1:
        _issue(
            issues,
            "MAPPING_MIXED_CAMERAS",
            "warning",
            len(camera_models),
            f"{len(camera_models)} unterschiedliche Kameramodelle im Mapping-Datensatz.",
            camera_models=dict(camera_models),
        )
    if len(dimensions) > 1:
        _issue(
            issues,
            "MAPPING_MIXED_IMAGE_DIMENSIONS",
            "warning",
            len(dimensions),
            (
                f"{len(dimensions)} unterschiedliche Bildabmessungen im "
                "Mapping-Datensatz."
            ),
            dimensions=dict(dimensions),
        )
    if (
        focal_spread_pct is not None
        and focal_spread_pct > _FOCAL_SPREAD_WARNING_PCT
    ):
        _issue(
            issues,
            "MAPPING_FOCAL_LENGTH_VARIATION",
            "warning",
            len(focal_lengths),
            (
                "Die Brennweite variiert innerhalb des Mapping-Datensatzes um "
                f"{focal_spread_pct:.2f}%."
            ),
            spread_percent=round(focal_spread_pct, 3),
        )
    if (
        takeoff_offset_spread_m is not None
        and takeoff_offset_spread_m > _HEIGHT_OFFSET_SPREAD_WARNING_M
    ):
        _issue(
            issues,
            "MAPPING_HEIGHT_OFFSET_VARIATION",
            "warning",
            len(takeoff_offsets),
            (
                "Absolute und relative Höhe ergeben keinen ausreichend konstanten "
                "Takeoff-Höhenoffset."
            ),
            spread_m=round(takeoff_offset_spread_m, 3),
        )
    if nonpositive_relative_altitudes:
        _issue(
            issues,
            "MAPPING_NONPOSITIVE_RELATIVE_ALTITUDE",
            "warning",
            nonpositive_relative_altitudes,
            (
                f"{nonpositive_relative_altitudes} Mapping-Bild(er) mit "
                "relativer Höhe <= 0 m."
            ),
        )
    if oblique_images:
        _issue(
            issues,
            "MAPPING_OBLIQUE_GIMBAL",
            "warning",
            oblique_images,
            (
                f"{oblique_images} Mapping-Bild(er) weichen um mehr als "
                f"{_NADIR_WARNING_DEG:.0f}° von Nadir ab."
            ),
            strongly_oblique_images=strongly_oblique_images,
        )
    if orientation_metadata_images < eligible_images:
        missing_orientation = eligible_images - orientation_metadata_images
        _issue(
            issues,
            "MAPPING_INCOMPLETE_ORIENTATION",
            "info",
            missing_orientation,
            (
                f"{missing_orientation} Mapping-Bild(er) ohne vollständige "
                "Aircraft-/Gimbal-Lage."
            ),
        )
    missing_capture_time = eligible_images - len(capture_times_ms)
    if missing_capture_time:
        _issue(
            issues,
            "MAPPING_MISSING_CAPTURE_TIME",
            "info",
            missing_capture_time,
            f"{missing_capture_time} Mapping-Bild(er) ohne auswertbaren Aufnahmezeitpunkt.",
        )
    if duplicate_capture_times:
        _issue(
            issues,
            "MAPPING_DUPLICATE_CAPTURE_TIME",
            "warning",
            duplicate_capture_times,
            (
                f"{duplicate_capture_times} Mapping-Bild(er) teilen einen bereits "
                "vorhandenen Aufnahmezeitpunkt."
            ),
        )
    if rtk_metadata_images == 0 and eligible_images:
        _issue(
            issues,
            "MAPPING_RTK_UNAVAILABLE",
            "info",
            eligible_images,
            "Keine RTK-Statusmetadaten im Mapping-Datensatz verfügbar.",
        )
    if metadata_errors:
        _issue(
            issues,
            "MAPPING_METADATA_ERRORS",
            "warning",
            metadata_errors,
            f"{metadata_errors} Mapping-Bild(er) mit Scan-/Metadatenfehlern.",
        )

    hard_ready = eligible_images >= 2
    warning_issues = [
        issue
        for issue in issues
        if issue["severity"] in {"warning", "error"}
    ]
    status = (
        "blocked"
        if not hard_ready
        else "warning"
        if warning_issues
        else "ready"
    )
    primary_issue = next(
        (
            issue
            for issue in issues
            if issue["severity"] in {"error", "warning"}
        ),
        None,
    )

    return {
        "status": status,
        "ready": hard_ready,
        "minimum_images": 2,
        "eligible_images": eligible_images,
        "geotagged_images": len(valid_positions),
        "geotagged_percent": (
            round(len(valid_positions) * 100 / eligible_images, 1)
            if eligible_images
            else 0.0
        ),
        "missing_gps": missing_gps,
        "invalid_gps": invalid_gps,
        "unique_positions": unique_positions,
        "duplicate_position_images": duplicate_position_images,
        "position_extent_m": (
            round(position_extent_m, 3)
            if position_extent_m is not None
            else None
        ),
        "rtk_metadata_images": rtk_metadata_images,
        "rtk_fixed_images": rtk_fixed_images,
        "orientation_metadata_images": orientation_metadata_images,
        "metadata_errors": metadata_errors,
        "camera": {
            "models": dict(camera_models),
            "model_count": len(camera_models),
            "dimensions": dict(dimensions),
            "dimension_variants": len(dimensions),
            "focal_length_mm": {
                **_range(focal_lengths),
                "spread_percent": (
                    round(focal_spread_pct, 3)
                    if focal_spread_pct is not None
                    else None
                ),
            },
        },
        "altitude_consistency": {
            "paired_absolute_relative": len(takeoff_offsets),
            "takeoff_offset_m": _range(takeoff_offsets),
            "takeoff_offset_spread_m": (
                round(takeoff_offset_spread_m, 3)
                if takeoff_offset_spread_m is not None
                else None
            ),
            "nonpositive_relative_altitudes": nonpositive_relative_altitudes,
        },
        "orientation": {
            "gimbal_pitch_images": gimbal_pitch_images,
            "near_nadir_images": near_nadir_images,
            "oblique_images": oblique_images,
            "strongly_oblique_images": strongly_oblique_images,
            "max_nadir_deviation_deg": (
                round(max(nadir_deviations), 3)
                if nadir_deviations
                else None
            ),
        },
        "capture_time": {
            "count": len(capture_times_ms),
            "missing": missing_capture_time,
            "duplicate_count": duplicate_capture_times,
            "span_seconds": (
                round(capture_span_seconds, 3)
                if capture_span_seconds is not None
                else None
            ),
        },
        "issues": issues,
        "reason": primary_issue["message"] if primary_issue else None,
    }
