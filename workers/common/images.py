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
_M3M_BANDS = {
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
_M3M_BLOCKING_CONFLICTS = {
    "band_metadata_filename_conflict",
    "band_platform_conflict",
}


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
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _metadata_platform(metadata: dict[str, Any]) -> str:
    camera = metadata.get("camera") or {}
    dji = metadata.get("dji") or {}
    haystack = " | ".join(
        str(value).upper()
        for value in (
            camera.get("model"),
            dji.get("product_name"),
            dji.get("aircraft_type"),
            dji.get("drone_model"),
        )
        if value
    )
    for token, platform in (
        ("MAVIC 3 MULTISPECTRAL", "M3M"),
        ("MAVIC 3 ENTERPRISE", "M3E"),
        ("MAVIC 3 THERMAL", "M3T"),
        ("M3M", "M3M"),
        ("M3E", "M3E"),
        ("M3T", "M3T"),
    ):
        if token in haystack:
            return platform
    return "UNKNOWN"


def _platform_hint(record: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
    path = PurePosixPath(record["relative_path"])
    for part in path.parts[:-1]:
        if part.upper() == "M3M":
            return "M3M"

    platform = _metadata_platform(metadata or _record_metadata(record))
    return platform


def _capture_uuid(metadata: dict[str, Any]) -> str | None:
    dji = metadata.get("dji") or {}
    value = dji.get("capture_uuid")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _m3m_filename_parts(relative_path: str) -> tuple[str | None, str | None]:
    path = PurePosixPath(relative_path)
    upper = path.name.upper()
    multispectral = re.match(
        r"^(?P<base>.+)_MS_(?P<band>G|R|RE|NIR)\.(?:TIF|TIFF)$",
        upper,
    )
    if multispectral:
        return multispectral.group("base"), _M3M_BANDS[multispectral.group("band")]

    rgb = re.match(r"^(?P<base>.+)_D\.(?:JPG|JPEG|DNG)$", upper)
    if rgb:
        return rgb.group("base"), "RGB"
    return None, None


def _m3m_group_key(
    relative_path: str,
    metadata: dict[str, Any],
) -> tuple[str | None, str]:
    capture_uuid = _capture_uuid(metadata)
    if capture_uuid:
        return f"dji:{capture_uuid}", "authoritative"

    path = PurePosixPath(relative_path)
    base, _ = _m3m_filename_parts(relative_path)
    if base is None:
        return None, "unavailable"
    parent = path.parent.as_posix()
    return (
        base if parent == "." else f"{parent}/{base}",
        "heuristic",
    )


def _m3m_kind_and_conflicts(
    relative_path: str,
    metadata: dict[str, Any],
) -> tuple[str | None, list[str]]:
    _, filename_kind = _m3m_filename_parts(relative_path)
    dji = metadata.get("dji") or {}
    raw_band = dji.get("band_name")
    metadata_kind = None
    if isinstance(raw_band, str):
        normalized = raw_band.strip().upper().replace("_", " ")
        metadata_kind = _DJI_BAND_NAMES.get(normalized)

    conflicts: list[str] = []
    if metadata_kind is not None:
        if filename_kind is not None and filename_kind != metadata_kind:
            conflicts.append("band_metadata_filename_conflict")
        platform = _metadata_platform(metadata)
        if platform not in {"UNKNOWN", "M3M"}:
            conflicts.append("band_platform_conflict")
        return metadata_kind, conflicts

    return filename_kind, conflicts


def prepare_multispectral_images(
    dataset_id: str,
    target_dir: Path,
) -> dict[str, Any]:
    target_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}

    for record in _dataset_files(dataset_id):
        relative_path = record["relative_path"]
        source = Path(record["stored_path"])
        metadata = _record_metadata(record)
        platform = _platform_hint(record, metadata)
        kind, conflicts = _m3m_kind_and_conflicts(relative_path, metadata)

        if kind not in _M3M_REQUIRED_KINDS or platform != "M3M":
            skipped.append({
                "relative_path": relative_path,
                "media_kind": kind or media_kind(relative_path),
                "reason": "not_m3m_multispectral_input",
            })
            continue

        group_key, group_source = _m3m_group_key(relative_path, metadata)
        if group_key is None:
            skipped.append({
                "relative_path": relative_path,
                "media_kind": kind,
                "reason": "capture_group_unavailable",
            })
            continue

        if not source.is_file():
            skipped.append({
                "relative_path": relative_path,
                "media_kind": kind,
                "capture_group": group_key,
                "reason": "source_missing",
            })
            continue

        suffix = source.suffix.lower()
        if suffix != ".dng" and suffix not in _DIRECT_EXTENSIONS:
            skipped.append({
                "relative_path": relative_path,
                "media_kind": kind,
                "capture_group": group_key,
                "reason": "unsupported_extension",
            })
            continue

        grouped.setdefault(group_key, []).append({
            "record": record,
            "source": source,
            "metadata": metadata,
            "media_kind": kind,
            "platform": platform,
            "capture_group": group_key,
            "capture_group_source": group_source,
            "conflicts": conflicts,
        })

    capture_groups: list[dict[str, Any]] = []
    selected_groups: set[str] = set()

    for group_key in sorted(grouped):
        entries = grouped[group_key]
        kinds = {entry["media_kind"] for entry in entries}
        missing = sorted(_M3M_REQUIRED_KINDS - kinds)
        blocking_conflicts = sorted({
            conflict
            for entry in entries
            for conflict in entry["conflicts"]
            if conflict in _M3M_BLOCKING_CONFLICTS
        })

        if blocking_conflicts:
            status = "classification_conflict"
        elif missing:
            status = "incomplete_capture_group"
        else:
            status = "selected"
            selected_groups.add(group_key)

        capture_groups.append({
            "capture_group": group_key,
            "capture_group_source": entries[0]["capture_group_source"],
            "status": status,
            "media_kinds": sorted(kinds),
            "missing_media_kinds": missing,
            "blocking_conflicts": blocking_conflicts,
            "file_count": len(entries),
        })

        if status != "selected":
            for entry in entries:
                skipped.append({
                    "relative_path": entry["record"]["relative_path"],
                    "media_kind": entry["media_kind"],
                    "capture_group": group_key,
                    "reason": status,
                    "missing_media_kinds": missing,
                    "blocking_conflicts": blocking_conflicts,
                })

    for group_key in sorted(selected_groups):
        for entry in grouped[group_key]:
            record = entry["record"]
            source = entry["source"]
            relative_path = record["relative_path"]
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
            else:
                action = _link_or_copy(source, target)

            prepared.append({
                "relative_path": relative_path,
                "media_kind": entry["media_kind"],
                "platform": entry["platform"],
                "capture_group": group_key,
                "capture_group_source": entry["capture_group_source"],
                "prepared_name": target.name,
                "action": action,
                "sha256": record.get("sha256"),
            })

    selected_capture_groups = sorted(selected_groups)
    manifest = {
        "dataset_id": dataset_id,
        "workflow": "multispectral",
        "required_media_kinds": sorted(_M3M_REQUIRED_KINDS),
        "selected_group_count": len(selected_capture_groups),
        "selected_capture_groups": selected_capture_groups,
        "capture_groups": capture_groups,
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
