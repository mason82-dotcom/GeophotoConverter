from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


_M3M_BANDS = {
    "G": "MS_GREEN",
    "R": "MS_RED",
    "RE": "MS_RED_EDGE",
    "NIR": "MS_NIR",
}

_PLATFORM_TOKENS = (
    ("MAVIC 3 MULTISPECTRAL", "M3M"),
    ("MAVIC 3 THERMAL", "M3T"),
    ("MAVIC 3 ENTERPRISE", "M3E"),
    ("MATRICE 4 THERMAL", "M4T"),
    ("MATRICE 4T", "M4T"),
    ("MATRICE 4E", "M4E"),
    ("M3M", "M3M"),
    ("M3T", "M3T"),
    ("M3E", "M3E"),
    ("M4T", "M4T"),
    ("M4E", "M4E"),
)


@dataclass(frozen=True)
class MediaClassification:
    platform: str
    media_kind: str
    capture_group: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "platform": self.platform,
            "media_kind": self.media_kind,
            "capture_group": self.capture_group,
        }


def _group_path(path: PurePosixPath, base: str) -> str:
    parent = path.parent.as_posix()
    return base if parent == "." else f"{parent}/{base}"


def _capture_group(
    path: PurePosixPath,
    base: str | None,
    metadata: dict[str, Any] | None,
) -> str | None:
    dji = (metadata or {}).get("dji") or {}
    capture_uuid = dji.get("capture_uuid")
    if isinstance(capture_uuid, str) and capture_uuid.strip():
        return f"dji:{capture_uuid.strip()}"
    if base:
        return _group_path(path, base)
    return None


def _path_platform(path: PurePosixPath) -> str:
    for part in path.parts[:-1]:
        value = part.upper()
        if value in {"M3E", "M3T", "M3M", "M4T", "M4E"}:
            return value
    return "UNKNOWN"


def _metadata_platform(metadata: dict[str, Any] | None) -> str:
    metadata = metadata or {}
    camera = metadata.get("camera") or {}
    dji = metadata.get("dji") or {}
    candidates = (
        camera.get("model"),
        camera.get("make"),
        dji.get("product_name"),
        dji.get("aircraft_type"),
        dji.get("drone_model"),
    )
    haystack = " | ".join(str(value).upper() for value in candidates if value)
    for token, platform in _PLATFORM_TOKENS:
        if token in haystack:
            return platform
    return "UNKNOWN"


def classify_media(
    relative_path: str,
    metadata: dict[str, Any] | None = None,
) -> MediaClassification:
    path = PurePosixPath(relative_path)
    upper = path.name.upper()
    platform = _metadata_platform(metadata)
    if platform == "UNKNOWN":
        platform = _path_platform(path)

    m3m = re.match(
        r"^(?P<base>.+)_MS_(?P<band>G|R|RE|NIR)\.(?:TIF|TIFF)$",
        upper,
    )
    if m3m:
        return MediaClassification(
            platform="M3M",
            media_kind=_M3M_BANDS[m3m.group("band")],
            capture_group=_capture_group(path, m3m.group("base"), metadata),
        )

    patterns = (
        (r"^(?P<base>.+)_D\.(?:JPG|JPEG|DNG)$", "RGB"),
        (r"^(?P<base>.+)_W\.(?:JPG|JPEG|DNG)$", "WIDE"),
        (r"^(?P<base>.+)_Z\.(?:JPG|JPEG|DNG)$", "ZOOM"),
        (r"^(?P<base>.+)_(?:T|R)\.(?:JPG|JPEG|RJPEG)$", "THERMAL"),
    )
    for pattern, media_kind in patterns:
        match = re.match(pattern, upper)
        if match:
            return MediaClassification(
                platform=platform,
                media_kind=media_kind,
                capture_group=_capture_group(path, match.group("base"), metadata),
            )

    generic = re.match(
        r"^(?P<base>DJI_.+?)\.(?:JPG|JPEG|TIF|TIFF|DNG|RJPEG)$",
        upper,
    )
    if path.suffix.lower() in {".jpg", ".jpeg", ".dng", ".tif", ".tiff"}:
        media_kind = "RGB"
    else:
        media_kind = "UNKNOWN"

    return MediaClassification(
        platform=platform,
        media_kind=media_kind,
        capture_group=_capture_group(path, generic.group("base") if generic else None, metadata),
    )


def reconcile_group_platforms(
    items: list[tuple[str, MediaClassification]],
) -> dict[str, MediaClassification]:
    by_group: dict[str, str] = {}
    definitive = {"M3M", "M3T", "M3E", "M4T", "M4E"}
    for _, item in items:
        if item.capture_group and item.platform in definitive:
            by_group.setdefault(item.capture_group, item.platform)

    result: dict[str, MediaClassification] = {}
    for relative_path, item in items:
        group_platform = by_group.get(item.capture_group or "")
        result[relative_path] = MediaClassification(
            platform=group_platform or item.platform,
            media_kind=item.media_kind,
            capture_group=item.capture_group,
        )
    return result
