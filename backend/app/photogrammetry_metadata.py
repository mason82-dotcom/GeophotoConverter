from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable


SCHEMA_VERSION = 1

CANONICAL_FIELDS = (
    "capture.utc_at_exposure",
    "capture.date_time_original",
    "capture.image_source",
    "capture.surveying_mode",
    "position.latitude_deg",
    "position.longitude_deg",
    "position.gps_altitude_m",
    "position.absolute_altitude_m",
    "position.relative_height_m",
    "pose.aircraft_yaw_deg",
    "pose.aircraft_pitch_deg",
    "pose.aircraft_roll_deg",
    "pose.gimbal_yaw_deg",
    "pose.gimbal_pitch_deg",
    "pose.gimbal_roll_deg",
    "gnss.gps_status",
    "gnss.rtk_flag_raw",
    "camera_geometry.image_width_px",
    "camera_geometry.image_height_px",
    "camera_geometry.focal_length_mm",
    "camera_geometry.focal_length_35mm_eq",
    "camera_geometry.sensor_width_mm",
    "camera_geometry.sensor_height_mm",
    "camera_geometry.pixel_pitch_um",
)

_DJI_PRIMARY_FIELDS = {
    "capture.utc_at_exposure",
    "capture.image_source",
    "capture.surveying_mode",
    "position.absolute_altitude_m",
    "position.relative_height_m",
    "pose.aircraft_yaw_deg",
    "pose.aircraft_pitch_deg",
    "pose.aircraft_roll_deg",
    "pose.gimbal_yaw_deg",
    "pose.gimbal_pitch_deg",
    "pose.gimbal_roll_deg",
    "gnss.gps_status",
    "gnss.rtk_flag_raw",
}

_EXIF_PRIMARY_FIELDS = {
    "capture.date_time_original",
    "position.latitude_deg",
    "position.longitude_deg",
    "position.gps_altitude_m",
    "camera_geometry.image_width_px",
    "camera_geometry.image_height_px",
    "camera_geometry.focal_length_mm",
    "camera_geometry.focal_length_35mm_eq",
    "camera_geometry.sensor_width_mm",
    "camera_geometry.sensor_height_mm",
    "camera_geometry.pixel_pitch_um",
}

_ANGLE_FIELDS = {
    "pose.aircraft_yaw_deg",
    "pose.aircraft_pitch_deg",
    "pose.aircraft_roll_deg",
    "pose.gimbal_yaw_deg",
    "pose.gimbal_pitch_deg",
    "pose.gimbal_roll_deg",
}

_FLOAT_FIELDS = {
    "position.latitude_deg",
    "position.longitude_deg",
    "position.gps_altitude_m",
    "position.absolute_altitude_m",
    "position.relative_height_m",
    *_ANGLE_FIELDS,
    "camera_geometry.focal_length_mm",
    "camera_geometry.focal_length_35mm_eq",
    "camera_geometry.sensor_width_mm",
    "camera_geometry.sensor_height_mm",
    "camera_geometry.pixel_pitch_um",
}

_INT_FIELDS = {
    "capture.surveying_mode",
    "gnss.rtk_flag_raw",
    "camera_geometry.image_width_px",
    "camera_geometry.image_height_px",
}

_TOLERANCE = {
    "position.latitude_deg": 1e-7,
    "position.longitude_deg": 1e-7,
    "position.gps_altitude_m": 0.10,
    "position.absolute_altitude_m": 0.10,
    "position.relative_height_m": 0.10,
    "pose.aircraft_yaw_deg": 0.10,
    "pose.aircraft_pitch_deg": 0.10,
    "pose.aircraft_roll_deg": 0.10,
    "pose.gimbal_yaw_deg": 0.10,
    "pose.gimbal_pitch_deg": 0.10,
    "pose.gimbal_roll_deg": 0.10,
    "camera_geometry.focal_length_mm": 0.01,
    "camera_geometry.focal_length_35mm_eq": 0.01,
    "camera_geometry.sensor_width_mm": 0.01,
    "camera_geometry.sensor_height_mm": 0.01,
    "camera_geometry.pixel_pitch_um": 0.001,
}

_CRITICAL_CONFLICT_FIELDS = {
    "position.latitude_deg",
    "position.longitude_deg",
}


@dataclass(frozen=True)
class MetadataCandidate:
    field: str
    value: Any
    source_kind: str
    source_key: str
    source_id: str | None = None


def candidate(
    field: str,
    value: Any,
    *,
    source_kind: str,
    source_key: str,
    source_id: str | None = None,
) -> MetadataCandidate:
    return MetadataCandidate(
        field=field,
        value=value,
        source_kind=source_kind,
        source_key=source_key,
        source_id=source_id,
    )


def _source_order(field: str) -> tuple[str, ...]:
    # Deliberately field-specific: GeoPhotoConverter has no global source priority.
    if field in _DJI_PRIMARY_FIELDS:
        return ("file_dji_xmp", "fh2_dji_media", "file_exif", "derived")
    if field in _EXIF_PRIMARY_FIELDS:
        return ("file_exif", "file_dji_xmp", "fh2_dji_media", "derived")
    return ("file_dji_xmp", "file_exif", "fh2_dji_media", "derived")


def _rank(field: str, source_kind: str) -> int:
    order = _source_order(field)
    try:
        return order.index(source_kind)
    except ValueError:
        return len(order)


def _normalize_angle(value: float) -> float:
    normalized = ((value + 180.0) % 360.0) - 180.0
    return 0.0 if normalized == -0.0 else normalized


def _normalize_value(field: str, value: Any) -> tuple[Any, str | None]:
    if value in ("", None):
        return None, "missing"

    try:
        if field in _INT_FIELDS:
            normalized: Any = int(float(value))
        elif field in _FLOAT_FIELDS:
            normalized = float(value)
            if not isfinite(normalized):
                return None, "not_finite"
        else:
            normalized = str(value).strip()
            if not normalized:
                return None, "missing"
    except (TypeError, ValueError):
        return None, "invalid_type"

    if field in _ANGLE_FIELDS:
        normalized = _normalize_angle(float(normalized))

    if field == "position.latitude_deg" and not -90.0 <= normalized <= 90.0:
        return None, "latitude_out_of_range"
    if field == "position.longitude_deg" and not -180.0 <= normalized <= 180.0:
        return None, "longitude_out_of_range"
    if field in {"camera_geometry.image_width_px", "camera_geometry.image_height_px"} and normalized <= 0:
        return None, "non_positive_dimension"
    if field in {
        "camera_geometry.focal_length_mm",
        "camera_geometry.focal_length_35mm_eq",
        "camera_geometry.sensor_width_mm",
        "camera_geometry.sensor_height_mm",
        "camera_geometry.pixel_pitch_um",
    } and normalized <= 0:
        return None, "non_positive_geometry"

    return normalized, None


def _equivalent(field: str, first: Any, second: Any) -> bool:
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        tolerance = _TOLERANCE.get(field, 0.0)
        return abs(float(first) - float(second)) <= tolerance
    return first == second


def _set_path(target: dict[str, Any], field: str, value: Any) -> None:
    section, key = field.split(".", 1)
    target[section][key] = value


def _provenance(candidate: MetadataCandidate, normalized_value: Any, valid: bool) -> dict[str, Any]:
    return {
        "source_kind": candidate.source_kind,
        "source_key": candidate.source_key,
        "source_id": candidate.source_id,
        "raw_value": candidate.value,
        "normalized_value": normalized_value,
        "valid": valid,
    }


def _derive_gnss(result: dict[str, Any]) -> None:
    gnss = result["gnss"]
    flag = gnss["rtk_flag_raw"]
    gps_status = gnss["gps_status"]

    fixed: bool | None = None
    classification = "unknown"

    if flag == 50:
        fixed = True
        classification = "rtk_fixed"
    elif isinstance(flag, int) and 32 <= flag <= 49:
        fixed = False
        classification = "rtk_unknown_quality"
    elif flag == 16:
        fixed = False
        classification = "gnss_non_rtk"
    elif flag == 0:
        fixed = False
        classification = "unknown"
    elif flag is not None:
        fixed = False
        classification = "rtk_unknown_quality"
    elif gps_status:
        text = str(gps_status).upper()
        classification = "rtk_unknown_quality" if "RTK" in text else "gnss_non_rtk"

    gnss["rtk_fixed"] = fixed
    gnss["classification"] = classification


def build_photogrammetry_metadata(
    candidates: Iterable[MetadataCandidate],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "capture": {
            "utc_at_exposure": None,
            "date_time_original": None,
            "image_source": None,
            "surveying_mode": None,
        },
        "position": {
            "latitude_deg": None,
            "longitude_deg": None,
            "gps_altitude_m": None,
            "absolute_altitude_m": None,
            "relative_height_m": None,
        },
        "pose": {
            "aircraft_yaw_deg": None,
            "aircraft_pitch_deg": None,
            "aircraft_roll_deg": None,
            "gimbal_yaw_deg": None,
            "gimbal_pitch_deg": None,
            "gimbal_roll_deg": None,
        },
        "gnss": {
            "gps_status": None,
            "rtk_flag_raw": None,
            "rtk_fixed": None,
            "classification": "unknown",
        },
        "camera_geometry": {
            "image_width_px": None,
            "image_height_px": None,
            "focal_length_mm": None,
            "focal_length_35mm_eq": None,
            "sensor_width_mm": None,
            "sensor_height_mm": None,
            "pixel_pitch_um": None,
        },
        "source_provenance": {},
        "conflicts": [],
    }

    grouped: dict[str, list[tuple[int, MetadataCandidate, Any, str | None]]] = {}
    for index, item in enumerate(candidates):
        if item.field not in CANONICAL_FIELDS:
            raise ValueError(f"Unbekanntes kanonisches Photogrammetrie-Feld: {item.field}")
        normalized, error = _normalize_value(item.field, item.value)
        grouped.setdefault(item.field, []).append((index, item, normalized, error))

    for field in CANONICAL_FIELDS:
        entries = grouped.get(field, [])
        if not entries:
            continue

        provenance_entries = [
            _provenance(item, normalized, error is None)
            for _, item, normalized, error in entries
        ]
        result["source_provenance"][field] = {
            "selected": None,
            "candidates": provenance_entries,
        }

        for _, item, normalized, error in entries:
            if error not in (None, "missing"):
                result["conflicts"].append(
                    {
                        "field": field,
                        "kind": "invalid_value",
                        "severity": "critical" if field in _CRITICAL_CONFLICT_FIELDS else "warning",
                        "source_kind": item.source_kind,
                        "source_key": item.source_key,
                        "source_id": item.source_id,
                        "raw_value": item.value,
                        "error": error,
                    }
                )

        valid_entries = [entry for entry in entries if entry[3] is None]
        if not valid_entries:
            continue

        valid_entries.sort(key=lambda entry: (_rank(field, entry[1].source_kind), entry[0]))
        _, selected_item, selected_value, _ = valid_entries[0]
        _set_path(result, field, selected_value)
        result["source_provenance"][field]["selected"] = {
            "source_kind": selected_item.source_kind,
            "source_key": selected_item.source_key,
            "source_id": selected_item.source_id,
            "value": selected_value,
        }

        alternatives = []
        for _, item, normalized, _ in valid_entries[1:]:
            if not _equivalent(field, selected_value, normalized):
                alternatives.append(
                    {
                        "source_kind": item.source_kind,
                        "source_key": item.source_key,
                        "source_id": item.source_id,
                        "value": normalized,
                    }
                )

        if alternatives:
            result["conflicts"].append(
                {
                    "field": field,
                    "kind": "value_mismatch",
                    "severity": "critical" if field in _CRITICAL_CONFLICT_FIELDS else "warning",
                    "selected": {
                        "source_kind": selected_item.source_kind,
                        "source_key": selected_item.source_key,
                        "source_id": selected_item.source_id,
                        "value": selected_value,
                    },
                    "alternatives": alternatives,
                }
            )

    _derive_gnss(result)
    return result
