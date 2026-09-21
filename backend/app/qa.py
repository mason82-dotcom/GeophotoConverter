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
    cameras: Counter[str] = Counter()
    gps_altitudes: list[float] = []
    relative_altitudes: list[float] = []
    times: list[datetime] = []
    missing_gps = 0
    metadata_errors = 0

    for item in files:
        classification = reconciled[item["relative_path"]]
        platform_counts[classification.platform] += 1
        media_counts[classification.media_kind] += 1

        metadata = item.get("metadata") or {}
        camera = metadata.get("camera") or {}
        camera_model = camera.get("model")
        if camera_model:
            cameras[str(camera_model)] += 1

        gps = metadata.get("gps") or {}
        latitude = gps.get("latitude")
        longitude = gps.get("longitude")
        if latitude is None or longitude is None:
            missing_gps += 1

        gps_altitude = gps.get("altitude")
        if isinstance(gps_altitude, (int, float)):
            gps_altitudes.append(float(gps_altitude))

        dji = metadata.get("dji") or {}
        relative_altitude = dji.get("relative_altitude")
        if isinstance(relative_altitude, (int, float)):
            relative_altitudes.append(float(relative_altitude))

        capture_time = _parse_time(metadata.get("capture_time"))
        if capture_time is not None:
            times.append(capture_time)

        if item.get("scan_error"):
            metadata_errors += 1

    total = len(files)
    geotagged = total - missing_gps
    mapping_inputs = media_counts.get("RGB", 0) + media_counts.get("WIDE", 0)
    thermal_inputs = media_counts.get("THERMAL", 0)
    multispectral_inputs = sum(
        media_counts.get(kind, 0)
        for kind in ("MS_GREEN", "MS_RED", "MS_RED_EDGE", "MS_NIR")
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
            "reason": None if mapping_inputs >= 2 else "At least two RGB/WIDE images are required.",
        },
        "micmac": {
            "ready": mapping_inputs >= 3,
            "eligible_images": mapping_inputs,
            "reason": None if mapping_inputs >= 3 else "At least three RGB/WIDE images are required.",
        },
        "gsplat": {
            "ready": mapping_inputs >= 3,
            "eligible_images": mapping_inputs,
            "reason": None if mapping_inputs >= 3 else "At least three RGB/WIDE images are required.",
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
        },
        "readiness": readiness,
        "classifications": {
            path: classification.as_dict()
            for path, classification in reconciled.items()
        },
    }
