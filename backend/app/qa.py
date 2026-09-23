from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .classifier import classify_media, reconcile_group_platforms


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
    cameras: Counter[str] = Counter()
    gps_altitudes: list[float] = []
    relative_altitudes: list[float] = []
    times: list[datetime] = []
    missing_gps = 0
    metadata_errors = 0
    mapping_geotagged = 0
    mapping_rtk_metadata = 0
    mapping_orientation_metadata = 0
    mapping_metadata_errors = 0

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

        gps_altitude = gps.get("altitude")
        if isinstance(gps_altitude, (int, float)):
            gps_altitudes.append(float(gps_altitude))

        dji = metadata.get("dji") or {}
        relative_altitude = dji.get("relative_altitude")
        if isinstance(relative_altitude, (int, float)):
            relative_altitudes.append(float(relative_altitude))

        if is_mapping_input:
            if dji.get("rtk_flag") is not None:
                mapping_rtk_metadata += 1
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

        capture_time = _parse_time(metadata.get("capture_time"))
        if capture_time is not None:
            times.append(capture_time)

        if item.get("scan_error"):
            metadata_errors += 1
            if is_mapping_input:
                mapping_metadata_errors += 1

    total = len(files)
    geotagged = total - missing_gps
    mapping_inputs = media_counts.get("RGB", 0) + media_counts.get("WIDE", 0)
    mapping_missing_gps = max(mapping_inputs - mapping_geotagged, 0)
    mapping_ready = mapping_inputs >= 2
    if not mapping_ready:
        mapping_status = "blocked"
        mapping_reason = "Mindestens zwei RGB/WIDE-Bilder sind erforderlich."
    elif mapping_missing_gps:
        mapping_status = "warning"
        mapping_reason = f"{mapping_missing_gps} Mapping-Bild(er) ohne GPS-Koordinaten."
    elif mapping_metadata_errors:
        mapping_status = "warning"
        mapping_reason = f"{mapping_metadata_errors} Mapping-Bild(er) mit Metadatenfehlern."
    else:
        mapping_status = "ready"
        mapping_reason = None
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
    complete_multispectral_groups = sum(
        1
        for kinds in capture_groups.values()
        if required_m3m_kinds.issubset(kinds)
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
            "ready": complete_multispectral_groups >= 2,
            "eligible_images": (
                complete_multispectral_groups * len(required_m3m_kinds)
            ),
            "complete_groups": complete_multispectral_groups,
            "reason": (
                None
                if complete_multispectral_groups >= 2
                else (
                    "Mindestens zwei vollständige M3M-Aufnahmegruppen sind erforderlich "
                    "(RGB + Grün + Rot + Red Edge + NIR)."
                )
            ),
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
            "thermal_groups": thermal_group_count,
            "complete_thermal_groups": complete_thermal_groups,
        },
        "mapping": {
            "status": mapping_status,
            "ready": mapping_ready,
            "eligible_images": mapping_inputs,
            "geotagged_images": mapping_geotagged,
            "geotagged_percent": (
                round(mapping_geotagged * 100 / mapping_inputs, 1)
                if mapping_inputs
                else 0.0
            ),
            "missing_gps": mapping_missing_gps,
            "rtk_metadata_images": mapping_rtk_metadata,
            "orientation_metadata_images": mapping_orientation_metadata,
            "metadata_errors": mapping_metadata_errors,
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
        },
        "readiness": readiness,
        "classifications": {
            path: classification.as_dict()
            for path, classification in reconciled.items()
        },
    }
