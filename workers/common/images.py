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
_M3M_REQUIRED_KINDS = {"RGB", "MS_GREEN", "MS_RED", "MS_RED_EDGE", "MS_NIR"}


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
            SELECT relative_path, stored_path, size_bytes, sha256,
                   metadata_json, fh2_media_json
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
    create_geo_override: bool = False,
) -> dict[str, Any]:
    allowed = allowed_kinds or PHOTOGRAMMETRY_KINDS
    target_dir.mkdir(parents=True, exist_ok=True)

    prepared: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    georeferencing_entries: list[dict[str, Any]] = []

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
        if create_geo_override:
            georeferencing_entries.append(
                _canonical_georeferencing(record, target.name)
            )

    georeferencing = (
        _write_geo_override(target_dir, georeferencing_entries)
        if create_geo_override
        else {
            "mode": "not_requested",
            "reason": None,
            "path": None,
        }
    )

    manifest = {
        "dataset_id": dataset_id,
        "allowed_media_kinds": sorted(allowed),
        "prepared_count": len(prepared),
        "skipped_count": len(skipped),
        "georeferencing": georeferencing,
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


def _record_fh2_media(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("fh2_media_json")
    if isinstance(raw, dict):
        return raw
    if raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _canonical_georeferencing(
    record: dict[str, Any],
    prepared_name: str,
) -> dict[str, Any]:
    from app.photogrammetry import fuse_photogrammetry_metadata

    canonical = fuse_photogrammetry_metadata(
        _record_metadata(record),
        _record_fh2_media(record) or None,
    )
    provenance = canonical.get("provenance") or {}
    latitude_source = (provenance.get("position.latitude_deg") or {}).get("source")
    longitude_source = (provenance.get("position.longitude_deg") or {}).get("source")
    if latitude_source and latitude_source == longitude_source:
        position_source = str(latitude_source)
    elif latitude_source or longitude_source:
        position_source = "mixed"
    else:
        position_source = "unavailable"

    rtk = canonical.get("rtk") or {}
    return {
        "relative_path": record["relative_path"],
        "prepared_name": prepared_name,
        "latitude_deg": (canonical.get("position") or {}).get("latitude_deg"),
        "longitude_deg": (canonical.get("position") or {}).get("longitude_deg"),
        "ellipsoid_m": (canonical.get("height") or {}).get("ellipsoid_m"),
        "position_source": position_source,
        "rtk_metadata": (
            rtk.get("raw_flag") is not None or rtk.get("fixed") is not None
        ),
        "rtk_fixed": rtk.get("fixed") is True,
        "fusion_conflicts": list(canonical.get("conflicts") or []),
    }


def _write_geo_override(
    target_dir: Path,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    source_counts: dict[str, int] = {}
    rtk_metadata_images = 0
    rtk_fixed_images = 0
    fusion_conflict_files = 0
    fusion_conflict_count = 0

    for entry in entries:
        source = str(entry["position_source"])
        source_counts[source] = source_counts.get(source, 0) + 1
        if entry["rtk_metadata"]:
            rtk_metadata_images += 1
        if entry["rtk_fixed"]:
            rtk_fixed_images += 1
        conflicts = entry["fusion_conflicts"]
        if conflicts:
            fusion_conflict_files += 1
            fusion_conflict_count += len(conflicts)

    position_entries = [
        entry
        for entry in entries
        if isinstance(entry["latitude_deg"], (int, float))
        and isinstance(entry["longitude_deg"], (int, float))
    ]
    ellipsoid_entries = [
        entry
        for entry in entries
        if isinstance(entry["ellipsoid_m"], (int, float))
    ]

    evidence: dict[str, Any] = {
        "projection": "EPSG:4326",
        "prepared_images": len(entries),
        "canonical_position_images": len(position_entries),
        "ellipsoid_height_images": len(ellipsoid_entries),
        "position_sources": source_counts,
        "rtk_metadata_images": rtk_metadata_images,
        "rtk_fixed_images": rtk_fixed_images,
        "fusion_conflict_files": fusion_conflict_files,
        "fusion_conflict_count": fusion_conflict_count,
    }

    geo_path = target_dir.parent / "geo.txt"
    if not entries or len(position_entries) != len(entries):
        evidence.update({
            "mode": "embedded_metadata_fallback",
            "reason": "incomplete_canonical_position",
            "height_mode": "embedded_metadata",
            "path": None,
        })
        geo_path.unlink(missing_ok=True)
        return evidence

    include_height = len(ellipsoid_entries) == len(entries)
    lines = ["EPSG:4326"]
    for entry in entries:
        line = (
            f"{entry['prepared_name']} "
            f"{float(entry['longitude_deg']):.10f} "
            f"{float(entry['latitude_deg']):.10f}"
        )
        if include_height:
            line += f" {float(entry['ellipsoid_m']):.3f}"
        lines.append(line)

    geo_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    evidence.update({
        "mode": "geo_override",
        "reason": None,
        "height_mode": "ellipsoid" if include_height else "xy_only",
        "path": geo_path.name,
    })
    return evidence


def _m3m_record_info(record: dict[str, Any]) -> dict[str, Any] | None:
    from app.classifier import classify_media

    relative_path = record["relative_path"]
    classification = classify_media(
        relative_path,
        _record_metadata(record),
    )
    if (
        classification.platform != "M3M"
        or classification.media_kind not in _M3M_REQUIRED_KINDS
    ):
        return None
    return {
        "relative_path": relative_path,
        "media_kind": classification.media_kind,
        "platform": classification.platform,
        "capture_group": classification.capture_group,
        "conflicts": list(classification.conflicts),
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
    blocking_conflict_groups = sorted({
        item["capture_group"]
        for item in conflicts
        if item["capture_group"] in complete_groups
        and any(
            code in {
                "band_metadata_filename_conflict",
                "band_platform_conflict",
            }
            for code in item["codes"]
        )
    })
    return {
        "classifications": classifications,
        "complete_groups": sorted(complete_groups),
        "incomplete_groups": sorted(incomplete_groups),
        "blocking_conflict_groups": blocking_conflict_groups,
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
    if plan["blocking_conflict_groups"]:
        blocking_groups = set(plan["blocking_conflict_groups"])
        conflict = next(
            item
            for item in plan["conflicts"]
            if item["capture_group"] in blocking_groups
        )
        raise ValueError(
            "M3M classification conflict in complete capture group for "
            f"{conflict['relative_path']}: {', '.join(conflict['codes'])}"
        )

    classifications = plan["classifications"]
    classified_complete_groups = set(plan["complete_groups"])

    stageable_group_kinds: dict[str, set[str]] = {}
    for record in records:
        info = classifications.get(record["relative_path"])
        if info is None or info["capture_group"] not in classified_complete_groups:
            continue
        source = Path(record["stored_path"])
        suffix = source.suffix.lower()
        if source.is_file() and (
            suffix == ".dng" or suffix in _DIRECT_EXTENSIONS
        ):
            stageable_group_kinds.setdefault(
                info["capture_group"],
                set(),
            ).add(info["media_kind"])

    complete_groups = {
        group
        for group in classified_complete_groups
        if _M3M_REQUIRED_KINDS.issubset(
            stageable_group_kinds.get(group, set())
        )
    }
    unstageable_groups = classified_complete_groups - complete_groups

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
                "reason": (
                    "unstageable_m3m_capture_group"
                    if capture_group in unstageable_groups
                    else "incomplete_m3m_capture_group"
                ),
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
        "complete_capture_groups": sorted(complete_groups),
        "incomplete_capture_groups": plan["incomplete_groups"],
        "unstageable_capture_groups": sorted(unstageable_groups),
        "classification_conflicts": plan["conflicts"],
        "blocking_conflict_groups": plan["blocking_conflict_groups"],
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
