from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .classifier import classify_media, reconcile_group_platforms


_MULTISPECTRAL_BLOCKING_CONFLICTS = {
    "band_metadata_filename_conflict",
    "band_platform_conflict",
}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    candidates = [text]
    if len(text) >= 19 and text[4:5] == ":" and text[7:8] == ":":
        candidates.insert(0, f"{text[:4]}-{text[5:7]}-{text[8:]}")
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            continue
    return None


def _range(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def _percent(count: int, total: int) -> float:
    return round(count * 100 / total, 1) if total else 0.0


def _span(values: list[float]) -> float | None:
    return max(values) - min(values) if values else None


def dataset_qa(files: list[dict[str, Any]]) -> dict[str, Any]:
    classified = [
        (
            item["relative_path"],
            classify_media(item["relative_path"], item.get("metadata")),
        )
        for item in files
    ]
    reconciled = reconcile_group_platforms(classified)

    platform_counts: Counter[str] = Counter()
    media_counts: Counter[str] = Counter()
    capture_groups: dict[str, set[str]] = {}
    capture_group_platforms: dict[str, set[str]] = {}
    capture_group_conflicts: dict[str, Counter[str]] = {}
    cameras: Counter[str] = Counter()
    gps_altitudes: list[float] = []
    relative_altitudes: list[float] = []
    times: list[datetime] = []
    missing_gps = 0
    metadata_errors = 0
    mapping_geotagged = 0
    mapping_rtk_metadata = 0
    mapping_rtk_fixed = 0
    mapping_orientation_metadata = 0
    mapping_metadata_errors = 0
    mapping_positions: list[tuple[float, float]] = []
    mapping_camera_models: Counter[str] = Counter()
    mapping_focal_lengths: list[float] = []
    mapping_gimbal_pitches: list[float] = []
    mapping_capture_times: list[datetime] = []
    mapping_relative_altitudes: list[float] = []
    mapping_absolute_altitudes: list[float] = []
    mapping_altitude_offsets: list[float] = []
    classification_conflicts: Counter[str] = Counter()
    multispectral_conflict_files: list[str] = []
    multispectral_conflict_groups: set[str] = set()

    for item in files:
        classification = reconciled[item["relative_path"]]
        platform_counts[classification.platform] += 1
        media_counts[classification.media_kind] += 1
        if classification.capture_group:
            capture_groups.setdefault(classification.capture_group, set()).add(
                classification.media_kind
            )
            capture_group_platforms.setdefault(
                classification.capture_group,
                set(),
            ).add(classification.platform)

        if classification.conflicts:
            classification_conflicts.update(classification.conflicts)
            if classification.media_kind in {
                "MS_GREEN",
                "MS_RED",
                "MS_RED_EDGE",
                "MS_NIR",
            }:
                multispectral_conflict_files.append(item["relative_path"])
                if classification.capture_group:
                    multispectral_conflict_groups.add(classification.capture_group)
                    capture_group_conflicts.setdefault(
                        classification.capture_group,
                        Counter(),
                    ).update(classification.conflicts)

        metadata = item.get("metadata") or {}
        camera = metadata.get("camera") or {}
        camera_model = camera.get("model")
        if camera_model:
            cameras[str(camera_model)] += 1

        gps = metadata.get("gps") or {}
        latitude = gps.get("latitude")
        longitude = gps.get("longitude")
        is_mapping_input = classification.media_kind in {"RGB", "WIDE"}
        if latitude is None or longitude is None:
            missing_gps += 1
        elif is_mapping_input:
            mapping_geotagged += 1
            if (
                isinstance(latitude, (int, float))
                and not isinstance(latitude, bool)
                and isinstance(longitude, (int, float))
                and not isinstance(longitude, bool)
            ):
                mapping_positions.append(
                    (float(latitude), float(longitude))
                )

        if is_mapping_input and camera_model:
            mapping_camera_models[str(camera_model)] += 1

        image = metadata.get("image") or {}
        focal_length = image.get("focal_length")
        if (
            is_mapping_input
            and isinstance(focal_length, (int, float))
            and not isinstance(focal_length, bool)
        ):
            mapping_focal_lengths.append(float(focal_length))

        gps_altitude = gps.get("altitude")
        if isinstance(gps_altitude, (int, float)):
            gps_altitudes.append(float(gps_altitude))

        dji = metadata.get("dji") or {}
        relative_altitude = dji.get("relative_altitude")
        if isinstance(relative_altitude, (int, float)) and not isinstance(
            relative_altitude,
            bool,
        ):
            relative_altitudes.append(float(relative_altitude))
            if is_mapping_input:
                mapping_relative_altitudes.append(float(relative_altitude))

        absolute_altitude = dji.get("absolute_altitude")
        if (
            is_mapping_input
            and isinstance(absolute_altitude, (int, float))
            and not isinstance(absolute_altitude, bool)
        ):
            mapping_absolute_altitudes.append(float(absolute_altitude))

        if (
            is_mapping_input
            and isinstance(relative_altitude, (int, float))
            and not isinstance(relative_altitude, bool)
            and isinstance(absolute_altitude, (int, float))
            and not isinstance(absolute_altitude, bool)
        ):
            mapping_altitude_offsets.append(
                float(absolute_altitude) - float(relative_altitude)
            )

        if is_mapping_input:
            if dji.get("rtk_flag") is not None:
                mapping_rtk_metadata += 1
                rtk_fixed = dji.get("rtk_fixed")
                if rtk_fixed is True or (
                    rtk_fixed is None
                    and str(dji.get("rtk_flag")).strip() == "50"
                ):
                    mapping_rtk_fixed += 1
            gimbal_pitch = dji.get("gimbal_pitch")
            if isinstance(gimbal_pitch, (int, float)) and not isinstance(
                gimbal_pitch,
                bool,
            ):
                mapping_gimbal_pitches.append(float(gimbal_pitch))

            orientation_values = (
                dji.get("flight_yaw"),
                dji.get("flight_pitch"),
                dji.get("flight_roll"),
                dji.get("gimbal_yaw"),
                dji.get("gimbal_pitch"),
                dji.get("gimbal_roll"),
            )
            if all(value is not None for value in orientation_values):
                mapping_orientation_metadata += 1

        capture_time = _parse_time(
            metadata.get("utc_at_exposure")
            or metadata.get("capture_time")
        )
        if capture_time is not None:
            times.append(capture_time)
            if is_mapping_input:
                mapping_capture_times.append(capture_time)

        if item.get("scan_error"):
            metadata_errors += 1
            if is_mapping_input:
                mapping_metadata_errors += 1

    total = len(files)
    geotagged = total - missing_gps
    mapping_inputs = media_counts.get("RGB", 0) + media_counts.get("WIDE", 0)
    mapping_missing_gps = max(mapping_inputs - mapping_geotagged, 0)
    mapping_ready = mapping_inputs >= 2

    unique_positions = {
        (round(latitude, 7), round(longitude, 7))
        for latitude, longitude in mapping_positions
    }
    if len(mapping_positions) < 2:
        gps_distribution_status = "unknown"
    elif len(unique_positions) < 2:
        gps_distribution_status = "warning"
    else:
        gps_distribution_status = "pass"

    if not mapping_camera_models:
        camera_status = "unknown"
    elif len(mapping_camera_models) > 1:
        camera_status = "warning"
    else:
        camera_status = "pass"

    focal_span = _span(mapping_focal_lengths)
    focal_mean = (
        sum(mapping_focal_lengths) / len(mapping_focal_lengths)
        if mapping_focal_lengths
        else None
    )
    focal_tolerance = (
        max(0.1, abs(focal_mean) * 0.02)
        if focal_mean is not None
        else None
    )
    if len(mapping_focal_lengths) < 2:
        focal_status = "unknown"
    elif focal_span is not None and focal_tolerance is not None and focal_span > focal_tolerance:
        focal_status = "warning"
    else:
        focal_status = "pass"

    nadir_tolerance_deg = 15.0
    nadir_like_count = sum(
        1
        for pitch in mapping_gimbal_pitches
        if abs(pitch + 90.0) <= nadir_tolerance_deg
    )
    nadir_like_percent = _percent(
        nadir_like_count,
        len(mapping_gimbal_pitches),
    )
    if not mapping_gimbal_pitches:
        gimbal_status = "unknown"
    elif nadir_like_percent < 80.0:
        gimbal_status = "warning"
    else:
        gimbal_status = "pass"

    capture_time_unique = len(set(mapping_capture_times))
    if not mapping_capture_times:
        capture_time_status = "unknown"
    elif (
        len(mapping_capture_times) < mapping_inputs
        or capture_time_unique < len(mapping_capture_times)
    ):
        capture_time_status = "warning"
    else:
        capture_time_status = "pass"
    try:
        capture_time_span_seconds = (
            (max(mapping_capture_times) - min(mapping_capture_times)).total_seconds()
            if len(mapping_capture_times) >= 2
            else None
        )
    except TypeError:
        capture_time_span_seconds = None
        capture_time_status = "unknown"

    relative_altitude_span = _span(mapping_relative_altitudes)
    relative_altitude_mean = (
        sum(mapping_relative_altitudes) / len(mapping_relative_altitudes)
        if mapping_relative_altitudes
        else None
    )
    relative_altitude_tolerance = (
        max(10.0, abs(relative_altitude_mean) * 0.25)
        if relative_altitude_mean is not None
        else None
    )
    if len(mapping_relative_altitudes) < 2:
        relative_altitude_status = "unknown"
    elif (
        relative_altitude_span is not None
        and relative_altitude_tolerance is not None
        and relative_altitude_span > relative_altitude_tolerance
    ):
        relative_altitude_status = "warning"
    else:
        relative_altitude_status = "pass"

    absolute_altitude_span = _span(mapping_absolute_altitudes)
    if len(mapping_absolute_altitudes) < 2:
        absolute_altitude_status = "unknown"
    elif absolute_altitude_span is not None and absolute_altitude_span > 50.0:
        absolute_altitude_status = "warning"
    else:
        absolute_altitude_status = "pass"

    altitude_offset_span = _span(mapping_altitude_offsets)
    if len(mapping_altitude_offsets) < 2:
        altitude_offset_status = "unknown"
    elif altitude_offset_span is not None and altitude_offset_span > 5.0:
        altitude_offset_status = "warning"
    else:
        altitude_offset_status = "pass"

    mapping_checks = {
        "gps_distribution": {
            "status": gps_distribution_status,
            "known_positions": len(mapping_positions),
            "unique_positions": len(unique_positions),
            "coverage_percent": _percent(len(mapping_positions), mapping_inputs),
        },
        "camera_consistency": {
            "status": camera_status,
            "known_images": sum(mapping_camera_models.values()),
            "models": dict(mapping_camera_models),
            "coverage_percent": _percent(
                sum(mapping_camera_models.values()),
                mapping_inputs,
            ),
        },
        "focal_length_consistency": {
            "status": focal_status,
            "known_images": len(mapping_focal_lengths),
            "coverage_percent": _percent(
                len(mapping_focal_lengths),
                mapping_inputs,
            ),
            "range_mm": _range(mapping_focal_lengths),
            "span_mm": focal_span,
            "tolerance_mm": focal_tolerance,
        },
        "gimbal_nadir": {
            "status": gimbal_status,
            "known_images": len(mapping_gimbal_pitches),
            "coverage_percent": _percent(
                len(mapping_gimbal_pitches),
                mapping_inputs,
            ),
            "nadir_like_images": nadir_like_count,
            "nadir_like_percent": nadir_like_percent,
            "tolerance_deg": nadir_tolerance_deg,
            "pitch_range_deg": _range(mapping_gimbal_pitches),
        },
        "capture_time": {
            "status": capture_time_status,
            "known_images": len(mapping_capture_times),
            "coverage_percent": _percent(
                len(mapping_capture_times),
                mapping_inputs,
            ),
            "unique_timestamps": capture_time_unique,
            "span_seconds": capture_time_span_seconds,
        },
        "relative_altitude": {
            "status": relative_altitude_status,
            "known_images": len(mapping_relative_altitudes),
            "coverage_percent": _percent(
                len(mapping_relative_altitudes),
                mapping_inputs,
            ),
            "range_m": _range(mapping_relative_altitudes),
            "span_m": relative_altitude_span,
            "tolerance_m": relative_altitude_tolerance,
        },
        "absolute_altitude": {
            "status": absolute_altitude_status,
            "known_images": len(mapping_absolute_altitudes),
            "coverage_percent": _percent(
                len(mapping_absolute_altitudes),
                mapping_inputs,
            ),
            "range_m": _range(mapping_absolute_altitudes),
            "span_m": absolute_altitude_span,
            "warning_threshold_m": 50.0,
        },
        "altitude_offset_consistency": {
            "status": altitude_offset_status,
            "known_pairs": len(mapping_altitude_offsets),
            "range_m": _range(mapping_altitude_offsets),
            "span_m": altitude_offset_span,
            "warning_threshold_m": 5.0,
        },
    }

    mapping_reasons: list[dict[str, Any]] = []
    if not mapping_ready:
        mapping_reasons.append({
            "code": "TOO_FEW_MAPPING_IMAGES",
            "severity": "error",
            "message": "Mindestens zwei RGB/WIDE-Bilder sind erforderlich.",
        })
    if mapping_missing_gps:
        mapping_reasons.append({
            "code": "MAPPING_GPS_INCOMPLETE",
            "severity": "warning",
            "message": f"{mapping_missing_gps} Mapping-Bild(er) ohne GPS-Koordinaten.",
        })
    if mapping_metadata_errors:
        mapping_reasons.append({
            "code": "MAPPING_METADATA_ERRORS",
            "severity": "warning",
            "message": f"{mapping_metadata_errors} Mapping-Bild(er) mit Metadatenfehlern.",
        })

    check_reason_specs = {
        "gps_distribution": (
            "MAPPING_GPS_DEGENERATE",
            "GPS-Aufnahmezentren sind räumlich degeneriert oder identisch.",
        ),
        "camera_consistency": (
            "MAPPING_MIXED_CAMERAS",
            "Mehrere Kameramodelle sind im Mapping-Datensatz gemischt.",
        ),
        "focal_length_consistency": (
            "MAPPING_FOCAL_LENGTH_VARIATION",
            "Die Brennweite variiert stärker als die Mapping-Toleranz.",
        ),
        "gimbal_nadir": (
            "MAPPING_NON_NADIR",
            "Ein relevanter Anteil der bekannten Gimbal-Winkel ist nicht nadirnah.",
        ),
        "capture_time": (
            "MAPPING_CAPTURE_TIME_INCONSISTENT",
            "Aufnahmezeiten fehlen teilweise oder enthalten Duplikate.",
        ),
        "relative_altitude": (
            "MAPPING_RELATIVE_ALTITUDE_VARIATION",
            "Die relative Flughöhe variiert stärker als die Mapping-Heuristik.",
        ),
        "absolute_altitude": (
            "MAPPING_ABSOLUTE_ALTITUDE_VARIATION",
            "Die absolute Höhe variiert um mehr als 50 m.",
        ),
        "altitude_offset_consistency": (
            "MAPPING_ALTITUDE_OFFSET_INCONSISTENT",
            "Die Differenz zwischen absoluter und relativer Höhe ist nicht konsistent.",
        ),
    }
    for check_name, (code, message) in check_reason_specs.items():
        if mapping_checks[check_name]["status"] == "warning":
            mapping_reasons.append({
                "code": code,
                "severity": "warning",
                "message": message,
                "check": check_name,
            })

    if not mapping_ready:
        mapping_status = "blocked"
    elif any(
        reason["severity"] == "warning"
        for reason in mapping_reasons
    ):
        mapping_status = "warning"
    else:
        mapping_status = "ready"
    mapping_reason = (
        mapping_reasons[0]["message"] if mapping_reasons else None
    )
    thermal_inputs = media_counts.get("THERMAL", 0)
    multispectral_inputs = sum(
        media_counts.get(kind, 0)
        for kind in ("MS_GREEN", "MS_RED", "MS_RED_EDGE", "MS_NIR")
    )
    required_m3m_kinds = {
        "RGB",
        "MS_GREEN",
        "MS_RED",
        "MS_RED_EDGE",
        "MS_NIR",
    }
    complete_multispectral_group_ids = [
        group
        for group, kinds in capture_groups.items()
        if required_m3m_kinds.issubset(kinds)
    ]
    complete_multispectral_groups = len(complete_multispectral_group_ids)
    multispectral_blocking_conflict_groups = sorted(
        group
        for group in complete_multispectral_group_ids
        if any(
            code in _MULTISPECTRAL_BLOCKING_CONFLICTS
            for code in capture_group_conflicts.get(group, {})
        )
    )
    multispectral_blocking_conflict_count = sum(
        count
        for group in multispectral_blocking_conflict_groups
        for code, count in capture_group_conflicts.get(group, {}).items()
        if code in _MULTISPECTRAL_BLOCKING_CONFLICTS
    )
    multispectral_group_count = sum(
        1
        for kinds in capture_groups.values()
        if kinds.intersection(required_m3m_kinds - {"RGB"})
    )

    complete_thermal_group_ids = [
        group
        for group, kinds in capture_groups.items()
        if {"WIDE", "THERMAL"}.issubset(kinds)
    ]
    complete_thermal_groups = len(complete_thermal_group_ids)
    thermal_group_count = sum(
        1
        for kinds in capture_groups.values()
        if "THERMAL" in kinds
    )
    thermal_group_platforms = {
        platform
        for group in complete_thermal_group_ids
        for platform in capture_group_platforms.get(group, {"UNKNOWN"})
        if platform != "UNKNOWN"
    }
    thermal_has_unknown_platform = any(
        "UNKNOWN" in capture_group_platforms.get(group, {"UNKNOWN"})
        for group in complete_thermal_group_ids
    )
    thermal_platform = (
        next(iter(thermal_group_platforms))
        if len(thermal_group_platforms) == 1 and not thermal_has_unknown_platform
        else None
    )
    thermal_ready = (
        complete_thermal_groups >= 1
        and thermal_platform in {"M3T", "M4T"}
        and len(thermal_group_platforms) == 1
        and not thermal_has_unknown_platform
    )
    warnings: list[dict[str, Any]] = []
    if missing_gps:
        warnings.append(
            {
                "code": "MISSING_GPS",
                "severity": "warning",
                "count": missing_gps,
            }
        )
    if metadata_errors:
        warnings.append(
            {
                "code": "METADATA_ERRORS",
                "severity": "warning",
                "count": metadata_errors,
            }
        )
    unknown_platform = platform_counts.get("UNKNOWN", 0)
    if unknown_platform:
        warnings.append(
            {
                "code": "UNKNOWN_PLATFORM",
                "severity": "info",
                "count": unknown_platform,
            }
        )
    if len(cameras) > 1:
        warnings.append(
            {
                "code": "MIXED_CAMERAS",
                "severity": "info",
                "count": len(cameras),
            }
        )
    if multispectral_conflict_files:
        warnings.append(
            {
                "code": "MULTISPECTRAL_CLASSIFICATION_CONFLICT",
                "severity": (
                    "error"
                    if multispectral_blocking_conflict_count
                    else "warning"
                ),
                "count": len(multispectral_conflict_files),
            }
        )

    multispectral_ready = (
        complete_multispectral_groups >= 2
        and multispectral_blocking_conflict_count == 0
    )
    if multispectral_blocking_conflict_count:
        multispectral_reason = (
            f"{multispectral_blocking_conflict_count} blockierende "
            "M3M-Klassifikationskonflikt(e) in "
            f"{len(multispectral_blocking_conflict_groups)} vollständigen "
            "Aufnahmegruppe(n)."
        )
    elif complete_multispectral_groups < 2:
        multispectral_reason = (
            "Mindestens zwei vollständige M3M-Aufnahmegruppen sind erforderlich "
            "(RGB + Grün + Rot + Red Edge + NIR)."
        )
    else:
        multispectral_reason = None

    readiness = {
        "odm": {
            "ready": mapping_inputs >= 2,
            "eligible_images": mapping_inputs,
            "reason": None if mapping_inputs >= 2 else "Mindestens zwei RGB/WIDE-Bilder sind erforderlich.",
        },
        "micmac": {
            "ready": mapping_inputs >= 3,
            "eligible_images": mapping_inputs,
            "reason": None if mapping_inputs >= 3 else "Mindestens drei RGB/WIDE-Bilder sind erforderlich.",
        },
        "gsplat": {
            "ready": mapping_inputs >= 3,
            "eligible_images": mapping_inputs,
            "reason": None if mapping_inputs >= 3 else "Mindestens drei RGB/WIDE-Bilder sind erforderlich.",
        },
        "thermal": {
            "ready": thermal_ready,
            "eligible_images": complete_thermal_groups * 2,
            "complete_groups": complete_thermal_groups,
            "platform": thermal_platform,
            "reason": (
                None
                if thermal_ready
                else (
                    "Mindestens eine vollständige WIDE+THERMAL-Aufnahmegruppe von "
                    "genau einer bestätigten M3T- oder M4T-Plattform ist erforderlich."
                )
            ),
        },
        "odm_multispectral": {
            "ready": multispectral_ready,
            "eligible_images": (
                complete_multispectral_groups * len(required_m3m_kinds)
            ),
            "complete_groups": complete_multispectral_groups,
            "classification_conflict_files": len(multispectral_conflict_files),
            "classification_conflict_groups": len(multispectral_conflict_groups),
            "blocking_conflicts": multispectral_blocking_conflict_count,
            "blocking_conflict_groups": multispectral_blocking_conflict_groups,
            "reason": multispectral_reason,
        },
    }

    return {
        "image_count": total,
        "geotagged_count": geotagged,
        "geotagged_percent": round(geotagged * 100 / total, 1) if total else 0.0,
        "platforms": dict(platform_counts),
        "media_kinds": dict(media_counts),
        "camera_models": dict(cameras),
        "altitude": {
            "gps_m": _range(gps_altitudes),
            "relative_takeoff_m": _range(relative_altitudes),
        },
        "capture_period": {
            "start": min(times).isoformat() if times else None,
            "end": max(times).isoformat() if times else None,
            "count": len(times),
        },
        "warnings": warnings,
        "engine_inputs": {
            "rgb_wide": mapping_inputs,
            "thermal": thermal_inputs,
            "multispectral": multispectral_inputs,
            "multispectral_groups": multispectral_group_count,
            "complete_multispectral_groups": complete_multispectral_groups,
            "multispectral_classification_conflicts": len(multispectral_conflict_files),
            "thermal_groups": thermal_group_count,
            "complete_thermal_groups": complete_thermal_groups,
        },
        "mapping": {
            "status": mapping_status,
            "ready": mapping_ready,
            "minimum_images": 2,
            "eligible_images": mapping_inputs,
            "geotagged_images": mapping_geotagged,
            "geotagged_percent": (
                round(mapping_geotagged * 100 / mapping_inputs, 1)
                if mapping_inputs
                else 0.0
            ),
            "missing_gps": mapping_missing_gps,
            "rtk_metadata_images": mapping_rtk_metadata,
            "rtk_fixed_images": mapping_rtk_fixed,
            "orientation_metadata_images": mapping_orientation_metadata,
            "metadata_errors": mapping_metadata_errors,
            "checks": mapping_checks,
            "reasons": mapping_reasons,
            "reason": mapping_reason,
        },
        "thermal": {
            "group_count": thermal_group_count,
            "complete_groups": complete_thermal_groups,
            "platform": thermal_platform,
        },
        "multispectral": {
            "required_media_kinds": sorted(required_m3m_kinds),
            "group_count": multispectral_group_count,
            "complete_groups": complete_multispectral_groups,
            "classification_conflicts": dict(classification_conflicts),
            "conflict_file_count": len(multispectral_conflict_files),
            "conflict_files": sorted(multispectral_conflict_files),
            "conflict_group_count": len(multispectral_conflict_groups),
            "conflict_groups": sorted(multispectral_conflict_groups),
            "blocking_conflict_count": multispectral_blocking_conflict_count,
            "blocking_conflict_groups": multispectral_blocking_conflict_groups,
        },
        "readiness": readiness,
        "classifications": {
            path: classification.as_dict()
            for path, classification in reconciled.items()
        },
    }
