from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from .runtime import DB_PATH

PHOTOGRAMMETRY_KINDS = {"RGB", "WIDE"}
_DIRECT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


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


def _platform_hint(record: dict[str, Any]) -> str:
    path = PurePosixPath(record["relative_path"])
    for part in path.parts[:-1]:
        if part.upper() == "M3M":
            return "M3M"

    raw = record.get("metadata_json")
    if raw:
        try:
            metadata = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        camera = metadata.get("camera") or {}
        dji = metadata.get("dji") or {}
        haystack = " | ".join(
            str(value).upper()
            for value in (
                camera.get("model"),
                dji.get("product_name"),
                dji.get("aircraft_type"),
            )
            if value
        )
        if "MAVIC 3 MULTISPECTRAL" in haystack or "M3M" in haystack:
            return "M3M"
    return "UNKNOWN"


def prepare_multispectral_images(
    dataset_id: str,
    target_dir: Path,
) -> dict[str, Any]:
    target_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for record in _dataset_files(dataset_id):
        relative_path = record["relative_path"]
        source = Path(record["stored_path"])
        kind = media_kind(relative_path)
        platform = _platform_hint(record)

        include = kind == "MULTISPECTRAL" or (
            kind == "RGB" and platform == "M3M"
        )
        if not include:
            skipped.append({
                "relative_path": relative_path,
                "media_kind": kind,
                "reason": "not_m3m_multispectral_input",
            })
            continue
        if not source.is_file():
            skipped.append({
                "relative_path": relative_path,
                "media_kind": kind,
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
                "media_kind": kind,
                "reason": "unsupported_extension",
            })
            continue

        prepared.append({
            "relative_path": relative_path,
            "media_kind": kind,
            "platform": platform,
            "prepared_name": target.name,
            "action": action,
            "sha256": record.get("sha256"),
        })

    manifest = {
        "dataset_id": dataset_id,
        "workflow": "multispectral",
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
