from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from .runtime import DB_PATH

PHOTOGRAMMETRY_KINDS = {"RGB", "WIDE"}
_DIRECT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
_M3M_REQUIRED_KINDS = {"RGB", "MS_GREEN", "MS_RED", "MS_RED_EDGE", "MS_NIR"}
_M3M_FILENAME_BANDS = {
    "G": "MS_GREEN",
    "R": "MS_RED",
    "RE": "MS_RED_EDGE",
    "NIR": "MS_NIR",
}
_DJI_BAND_NAMES = {
    "GREEN": "MS_GREEN",
    "RED": "MS_RED",
    "REDEDGE": "MS_RED_EDGE",
    "RED EDGE": "MS_RED_EDGE",
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


def media_kind(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    name = path.name.upper()

    if "_MS_" in name and path.suffix.lower() in {".tif", ".tiff"}:
        return "MULTISPECTRAL"
    if path.suffix.lower() == ".rjpeg":
        return "THERMAL"
    if any(name.endswith(s) for s in (
        "_T.JPG", "_T.JPEG", "_T.RJPEG",
        "_R.JPG", "_R.JPEG", "_R.RJPEG",
    )):
        return "THERMAL"
    if any(name.endswith(s) for s in ("_Z.JPG", "_Z.JPEG", "_Z.DNG")):
        return "ZOOM"
    if any(name.endswith(s) for s in ("_W.JPG", "_W.JPEG", "_W.DNG")):
        return "WIDE"
    if any(name.endswith(s) for s in ("_D.JPG", "_D.JPEG", "_D.DNG")):
        return "RGB"
    if path.suffix.lower() in _DIRECT_EXTENSIONS | {".dng"}:
        return "RGB"
    return "UNKNOWN"


def _dataset_files(dataset_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT relative_path, stored_path, size_bytes, sha256, metadata_json
            FROM files
            WHERE dataset_id=?
            ORDER BY relative_path
            """,
            (dataset_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _link_or_copy(source: Path, target: Path) -> str:
    try:
        target.symlink_to(source)
        return "symlink"
    except OSError:
        shutil.copy2(source, target)
        return "copy"


def _normalize_dng(source: Path, target: Path) -> None:
    rendered = subprocess.run(
        [
            "dcraw_emu",
            "-w",
            "-6",
            "-T",
            "-q",
            "3",
            "-Z",
            str(target),
            str(source),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if rendered.returncode != 0 or not target.is_file():
        raise RuntimeError(
            f"LibRaw failed to normalize {source.name}: "
            f"{(rendered.stderr or rendered.stdout).strip()}"
        )

    copied = subprocess.run(
        [
            "exiftool",
            "-overwrite_original",
            "-TagsFromFile",
            str(source),
            "-all:all",
            "-unsafe",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if copied.returncode != 0:
        target.unlink(missing_ok=True)
        raise RuntimeError(
            f"ExifTool failed to copy metadata from {source.name}: "
            f"{(copied.stderr or copied.stdout).strip()}"
        )


def prepare_photogrammetry_images(
    dataset_id: str,
    target_dir: Path,
    *,
    allowed_kinds: set[str] | None = None,
) -> dict[str, Any]:
    allowed = allowed_kinds or PHOTOGRAMMETRY_KINDS
    target_dir.mkdir(parents=True, exist_ok=True)

    prepared: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for record in _dataset_files(dataset_id):
        relative_path = record["relative_path"]
        source = Path(record["stored_path"])
        kind = media_kind(relative_path)

        if kind not in allowed:
            skipped.append({
                "relative_path": relative_path,
                "media_kind": kind,
                "reason": "media_kind_not_selected",
            })
            continue
        if not source.is_file():
            skipped.append({
                "relative_path": relative_path,
                "media_kind": kind,
                "reason": "source_missing",
            })
            continue

        index = len(prepared) + 1
        suffix = source.suffix.lower()
        if suffix == ".dng":
            target = target_dir / f"IMG_{index:06d}.TIF"
            _normalize_dng(source, target)
            action = "dng_to_tiff"
        elif suffix in _DIRECT_EXTENSIONS:
            out_suffix = ".JPG" if suffix in {".jpg", ".jpeg"} else suffix.upper()
            target = target_dir / f"IMG_{index:06d}{out_suffix}"
            action = _link_or_copy(source, target)
        else:
            skipped.append({
                "relative_path": relative_path,
                "media_kind": kind,
                "reason": "unsupported_extension",
            })
            continue

        prepared.append({
            "relative_path": relative_path,
            "media_kind": kind,
            "source_extension": suffix,
            "prepared_name": target.name,
            "action": action,
            "sha256": record.get("sha256"),
        })

    manifest = {
        "dataset_id": dataset_id,
        "allowed_media_kinds": sorted(allowed),
        "prepared_count": len(prepared),
        "skipped_count": len(skipped),
        "prepared": prepared,
        "skipped": skipped,
    }
    (target_dir / "geophoto-input-manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return manifest


def _record_metadata(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("metadata_json")
    if isinstance(raw, dict):
        return raw
    if raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _metadata_platform(metadata: dict[str, Any]) -> str:
    camera = metadata.get("camera") or {}
    dji = metadata.get("dji") or {}
    haystack = " | ".join(
        str(value).upper()
        for value in (
            camera.get("model"),
            camera.get("make"),
            dji.get("product_name"),
            dji.get("aircraft_type"),
            dji.get("drone_model"),
        )
        if value
    )
    for token, platform in _PLATFORM_TOKENS:
        if token in haystack:
            return platform
    return "UNKNOWN"


def _path_platform(path: PurePosixPath) -> str:
    for part in path.parts[:-1]:
        value = part.upper()
        if value in {"M3E", "M3T", "M3M", "M4T", "M4E"}:
            return value
    return "UNKNOWN"


def _platform_hint(record: dict[str, Any]) -> str:
    metadata_platform = _metadata_platform(_record_metadata(record))
    if metadata_platform != "UNKNOWN":
        return metadata_platform
    return _path_platform(PurePosixPath(record["relative_path"]))


def _capture_uuid(metadata: dict[str, Any]) -> str | None:
    dji = metadata.get("dji") or {}
    value = dji.get("capture_uuid")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _group_path(path: PurePosixPath, base: str) -> str:
    parent = path.parent.as_posix()
    return base if parent == "." else f"{parent}/{base}"


def _metadata_band_kind(metadata: dict[str, Any]) -> str | None:
    dji = metadata.get("dji") or {}
    value = dji.get("band_name")
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper().replace("_", " ")
    return _DJI_BAND_NAMES.get(normalized)


def _m3m_record_info(record: dict[str, Any]) -> dict[str, Any] | None:
    relative_path = record["relative_path"]
    path = PurePosixPath(relative_path)
    upper = path.name.upper()
    metadata = _record_metadata(record)
    platform = _metadata_platform(metadata)
    if platform == "UNKNOWN":
        platform = _path_platform(path)

    filename_band = re.match(
        r"^(?P<base>.+)_MS_(?P<band>G|R|RE|NIR)\.(?:TIF|TIFF)$",
        upper,
    )
    metadata_band = _metadata_band_kind(metadata)
    conflicts: list[str] = []

    if metadata_band:
        if platform not in {"UNKNOWN", "M3M"}:
            conflicts.append("band_platform_conflict")
        if filename_band:
            filename_kind = _M3M_FILENAME_BANDS[filename_band.group("band")]
            if filename_kind != metadata_band:
                conflicts.append("band_metadata_filename_conflict")
        media_kind_value = metadata_band
        platform = "M3M"
        base = filename_band.group("base") if filename_band else path.stem
    elif filename_band:
        media_kind_value = _M3M_FILENAME_BANDS[filename_band.group("band")]
        platform = "M3M"
        base = filename_band.group("base")
    else:
        if media_kind(relative_path) != "RGB" or platform != "M3M":
            return None
        rgb_match = re.match(
            r"^(?P<base>.+)_D\.(?:JPG|JPEG|DNG)$",
            upper,
        )
        generic = re.match(
            r"^(?P<base>DJI_.+?)\.(?:JPG|JPEG|TIF|TIFF|DNG)$",
            upper,
        )
        media_kind_value = "RGB"
        base = (
            rgb_match.group("base")
            if rgb_match
            else generic.group("base")
            if generic
            else path.stem
        )

    capture_uuid = _capture_uuid(metadata)
    capture_group = (
        f"dji:{capture_uuid}"
        if capture_uuid
        else _group_path(path, base)
    )
    return {
        "relative_path": relative_path,
        "media_kind": media_kind_value,
        "platform": platform,
        "capture_group": capture_group,
        "conflicts": conflicts,
    }


def _multispectral_plan(records: list[dict[str, Any]]) -> dict[str, Any]:
    classifications: dict[str, dict[str, Any]] = {}
    group_kinds: dict[str, set[str]] = {}
    conflicts: list[dict[str, Any]] = []

    for record in records:
        info = _m3m_record_info(record)
        if info is None:
            continue
        classifications[record["relative_path"]] = info
        group = info["capture_group"]
        group_kinds.setdefault(group, set()).add(info["media_kind"])
        if info["conflicts"]:
            conflicts.append(
                {
                    "relative_path": record["relative_path"],
                    "capture_group": group,
                    "codes": list(info["conflicts"]),
                }
            )

    complete_groups = {
        group
        for group, kinds in group_kinds.items()
        if _M3M_REQUIRED_KINDS.issubset(kinds)
    }
    incomplete_groups = set(group_kinds) - complete_groups
    return {
        "classifications": classifications,
        "complete_groups": sorted(complete_groups),
        "incomplete_groups": sorted(incomplete_groups),
        "conflicts": conflicts,
    }


def prepare_multispectral_images(
    dataset_id: str,
    target_dir: Path,
) -> dict[str, Any]:
    target_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    records = _dataset_files(dataset_id)
    plan = _multispectral_plan(records)
    if plan["conflicts"]:
        conflict = plan["conflicts"][0]
        raise ValueError(
            "M3M classification conflict for "
            f"{conflict['relative_path']}: {', '.join(conflict['codes'])}"
        )

    classifications = plan["classifications"]
    complete_groups = set(plan["complete_groups"])

    for record in records:
        relative_path = record["relative_path"]
        source = Path(record["stored_path"])
        info = classifications.get(relative_path)

        if info is None:
            skipped.append({
                "relative_path": relative_path,
                "media_kind": media_kind(relative_path),
                "reason": "not_m3m_multispectral_input",
            })
            continue

        capture_group = info["capture_group"]
        if capture_group not in complete_groups:
            skipped.append({
                "relative_path": relative_path,
                "media_kind": info["media_kind"],
                "capture_group": capture_group,
                "reason": "incomplete_m3m_capture_group",
            })
            continue

        if not source.is_file():
            skipped.append({
                "relative_path": relative_path,
                "media_kind": info["media_kind"],
                "capture_group": capture_group,
                "reason": "source_missing",
            })
            continue

        target = target_dir / PurePosixPath(relative_path).name
        if target.exists():
            raise ValueError(
                "Duplicate M3M filename while flattening dataset: "
                f"{target.name}. Keep capture filenames unique."
            )

        if source.suffix.lower() == ".dng":
            target = target.with_suffix(".TIF")
            _normalize_dng(source, target)
            action = "dng_to_tiff"
        elif source.suffix.lower() in _DIRECT_EXTENSIONS:
            action = _link_or_copy(source, target)
        else:
            skipped.append({
                "relative_path": relative_path,
                "media_kind": info["media_kind"],
                "capture_group": capture_group,
                "reason": "unsupported_extension",
            })
            continue

        prepared.append({
            "relative_path": relative_path,
            "media_kind": info["media_kind"],
            "platform": info["platform"],
            "capture_group": capture_group,
            "prepared_name": target.name,
            "action": action,
            "sha256": record.get("sha256"),
        })

    manifest = {
        "dataset_id": dataset_id,
        "workflow": "multispectral",
        "complete_capture_groups": plan["complete_groups"],
        "incomplete_capture_groups": plan["incomplete_groups"],
        "prepared_count": len(prepared),
        "skipped_count": len(skipped),
        "prepared": prepared,
        "skipped": skipped,
    }
    (target_dir / "geophoto-input-manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return manifest
