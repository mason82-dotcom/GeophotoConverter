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
    checksums: Counter[str] = Counter(
        str(item["sha256"]) for item in files if item.get("sha256")
    )

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
            "ready": total >= 2,
            "reason": None if total >= 2 else "Mindestens zwei unterstützte Bilder sind erforderlich.",
        },
        "micmac": {
            "ready": total >= 3,
            "reason": None if total >= 3 else "Mindestens drei Bilder sind erforderlich.",
        },
        "gsplat": {
            "ready": total >= 3,
            "reason": None if total >= 3 else "Mindestens drei Bilder sind erforderlich.",
        },
    }
    ready_count = sum(1 for state in readiness.values() if state["ready"])
    processing_readiness = (
        "Ready" if ready_count == len(readiness)
        else "Partially ready" if ready_count
        else "Not ready"
    )
    known_platforms = {
        name: count for name, count in platform_counts.items() if name != "UNKNOWN"
    }
    platform = max(known_platforms, key=known_platforms.get) if known_platforms else None
    duplicate_count = sum(count - 1 for count in checksums.values() if count > 1)

    return {
        "image_count": total,
        "geotagged_count": geotagged,
        "geotagged_percent": round(geotagged * 100 / total, 1) if total else 0.0,
        "platforms": dict(platform_counts),
        "platform": platform,
        "duplicate_count": duplicate_count,
        "processing_readiness": processing_readiness,
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
        "readiness": readiness,
        "classifications": {
            path: classification.as_dict()
            for path, classification in reconciled.items()
        },
    }
