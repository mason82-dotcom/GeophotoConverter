from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any

from common.runtime import (
    DATA_ROOT,
    DB_PATH,
    cancellation_requested,
    consume,
    update_job,
)
from thermal_core.dji_sdk import DjiThermalSdk
from thermal_core.processor import process_handoff

ENGINE = "thermal"

_CAPTURE_PATTERN = re.compile(
    r"^(?P<base>.+)_(?P<kind>W|T|R)\.(?:JPG|JPEG|RJPEG|DNG)$",
    re.IGNORECASE,
)


def _records(dataset_id: str) -> list[dict[str, Any]]:
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


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("metadata_json")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _platform(record: dict[str, Any]) -> str:
    path = PurePosixPath(record["relative_path"])
    for part in path.parts[:-1]:
        value = part.upper()
        if value in {"M3T", "M4T"}:
            return value

    metadata = _metadata(record)
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
    if any(token in haystack for token in ("MAVIC 3 THERMAL", "MAVIC 3T", "M3T")):
        return "M3T"
    if any(token in haystack for token in ("MATRICE 4 THERMAL", "MATRICE 4T", "M4T")):
        return "M4T"
    return "UNKNOWN"


def _capture_time_utc(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("capture_time")
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if len(text) >= 19 and text[4:5] == ":" and text[7:8] == ":":
        text = f"{text[:4]}-{text[5:7]}-{text[8:]}"
    if text.endswith("Z") or "+" in text[10:] or "-" in text[10:]:
        return text
    return None


def _thermal_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    camera = metadata.get("camera") or {}
    image = metadata.get("image") or {}
    gps = metadata.get("gps") or {}
    dji = metadata.get("dji") or {}

    return {
        "camera": {
            "make": camera.get("make"),
            "model": camera.get("model"),
            "serial": camera.get("serial"),
            "lens_model": camera.get("lens"),
        },
        "image": {
            "width": image.get("width"),
            "height": image.get("height"),
            "focal_length_mm": image.get("focal_length"),
            "f_number": image.get("f_number"),
            "iso": image.get("iso"),
            "exposure_time_s": image.get("exposure_time"),
        },
        "gps": {
            "latitude": gps.get("latitude"),
            "longitude": gps.get("longitude"),
            "altitude_m": gps.get("altitude"),
        },
        "dji_altitude": {
            "absolute_ellipsoid_m": dji.get("absolute_altitude"),
            "relative_takeoff_m": dji.get("relative_altitude"),
        },
        "flight_attitude": {
            "yaw_deg": dji.get("flight_yaw"),
            "pitch_deg": dji.get("flight_pitch"),
            "roll_deg": dji.get("flight_roll"),
        },
        "gimbal_attitude": {
            "yaw_deg": dji.get("gimbal_yaw"),
            "pitch_deg": dji.get("gimbal_pitch"),
            "roll_deg": dji.get("gimbal_roll"),
        },
        "raw": {},
    }


def _build_handoff(dataset_id: str, job_id: str, job_root: Path) -> tuple[Path, str, int]:
    source_root = DATA_ROOT / "datasets" / dataset_id / "images"
    groups: dict[str, dict[str, dict[str, Any]]] = {}
    platforms: set[str] = set()

    for record in _records(dataset_id):
        relative = PurePosixPath(record["relative_path"])
        match = _CAPTURE_PATTERN.match(relative.name)
        if not match:
            continue

        suffix_kind = match.group("kind").upper()
        media_kind = "WIDE" if suffix_kind == "W" else "THERMAL"
        group_name = (
            match.group("base")
            if relative.parent.as_posix() == "."
            else f"{relative.parent.as_posix()}/{match.group('base')}"
        )
        metadata = _metadata(record)
        platform = _platform(record)
        if platform != "UNKNOWN":
            platforms.add(platform)

        item = {
            "media_kind": media_kind,
            "relative_path": record["relative_path"],
            "path_relative_to_input": record["relative_path"],
            "filename": relative.name,
            "size_bytes": int(record["size_bytes"]),
            "sha256": record.get("sha256"),
            "capture_time_utc": _capture_time_utc(metadata),
            "metadata": _thermal_metadata(metadata),
        }
        groups.setdefault(group_name, {})[media_kind] = item

    complete = [
        {
            "capture_group": name,
            "files": [items["WIDE"], items["THERMAL"]],
        }
        for name, items in sorted(groups.items())
        if "WIDE" in items and "THERMAL" in items
    ]
    if not complete:
        raise ValueError("Keine vollständigen WIDE+THERMAL-Aufnahmegruppen gefunden.")
    if len(platforms) != 1:
        raise ValueError(
            "Thermal-Verarbeitung erfordert genau eine bestätigte Plattform (M3T oder M4T)."
        )
    platform = next(iter(platforms))
    if platform not in {"M3T", "M4T"}:
        raise ValueError(f"Nicht unterstützte Thermal-Plattform: {platform}")

    handoff = {
        "schema_version": 4,
        "worker_contract": (
            "M3T_RJPEG_V2" if platform == "M3T" else "M4T_RJPEG_V1"
        ),
        "workflow": "THERMOGRAM",
        "platform": platform,
        "job_id": job_id,
        "external_path": str(source_root),
        "capture_groups": complete,
    }
    handoff_path = job_root / "thermal-handoff.json"
    handoff_path.write_text(json.dumps(handoff, indent=2), encoding="utf-8")
    return handoff_path, platform, len(complete)


def _artifact_kind(path: Path) -> str:
    name = path.name
    if name == "temperature.tif":
        return "thermal_temperature_tiff"
    if name == "preview.png":
        return "thermal_preview"
    if name == "hotspot-mask.png":
        return "thermal_hotspot_mask"
    if name == "hotspots.json":
        return "thermal_hotspots"
    if name == "capture-points.geojson":
        return "thermal_capture_points"
    if name == "registration-audit.json":
        return "thermal_registration_audit"
    if name == "thermal-summary.json":
        return "thermal_summary"
    if name == "thermal-summary.csv":
        return "thermal_summary_csv"
    if name == "result-manifest.json":
        return "thermal_result_manifest"
    if name == "thermal.json":
        return "thermal_capture_metadata"
    return "thermal_artifact"


def _collect_artifacts(result_dir: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in sorted(result_dir.rglob("*")):
        if not path.is_file():
            continue
        artifacts.append({
            "type": _artifact_kind(path),
            "name": path.name,
            "relative_path": path.relative_to(DATA_ROOT).as_posix(),
            "size_bytes": path.stat().st_size,
        })
    return artifacts


def handle(payload: dict) -> None:
    job_id = payload["job_id"]
    dataset_id = payload["dataset_id"]
    options = payload.get("options") or {}
    measurement_overrides = {
        key: options[key]
        for key in (
            "distance_m",
            "humidity_pct",
            "emissivity",
            "reflection_c",
            "ambient_temp_c",
        )
        if key in options
    }
    hotspot_delta_c = float(options.get("hotspot_delta_c", 10.0))
    hotspot_min_pixels = int(options.get("hotspot_min_pixels", 4))
    job_root = DATA_ROOT / "jobs" / job_id
    job_root.mkdir(parents=True, exist_ok=True)
    result_dir = job_root / "thermal" / "results"

    if cancellation_requested(job_id):
        update_job(
            job_id,
            status="cancelled",
            phase="cancelled",
            message="Thermal-Auftrag wurde vor der Dekodierung abgebrochen.",
        )
        return

    update_job(
        job_id,
        status="running",
        progress=2,
        phase="thermal_handoff",
        message="WIDE/THERMAL-Aufnahmepaare werden vorbereitet.",
    )
    handoff_path, platform, group_count = _build_handoff(
        dataset_id,
        job_id,
        job_root,
    )

    sdk_dir = os.environ.get("DJI_TSDK_DIR", "/opt/dji-tsdk")
    sdk_label = os.environ.get("DJI_TSDK_VERSION")
    update_job(
        job_id,
        progress=8,
        phase="thermal_decode",
        message=(
            f"Dekodiere {group_count} {platform} radiometrische Aufnahmen mit "
            "DJI DIRP. Temperaturpixel verbleiben im Sensor-Pixelraum."
        ),
    )
    decoder = DjiThermalSdk(sdk_dir, sdk_label=sdk_label)
    process_handoff(
        handoff_path,
        result_dir,
        decoder,
        measurement_overrides=measurement_overrides or None,
        hotspot_delta_c=hotspot_delta_c,
        hotspot_min_pixels=hotspot_min_pixels,
    )

    artifacts = _collect_artifacts(result_dir)
    if cancellation_requested(job_id):
        update_job(
            job_id,
            status="cancelled",
            progress=100,
            phase="cancelled",
            message=(
                "Während der DIRP-Verarbeitung wurde ein Abbruch angefordert; "
                "der aktuelle Aufnahmeblock wurde beendet und erzeugte Artefakte "
                "wurden beibehalten."
            ),
            artifacts=artifacts,
        )
        return

    update_job(
        job_id,
        status="completed",
        progress=100,
        phase="completed",
        message=(
            f"Thermal-Verarbeitung abgeschlossen: {group_count} {platform}-"
            f"Aufnahmegruppen, {len(artifacts)} Artefakte."
        ),
        artifacts=artifacts,
    )


if __name__ == "__main__":
    consume(ENGINE, handle)
