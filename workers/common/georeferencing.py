from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


_RASTER_OUTPUTS = {
    "orthophoto": "odm_orthophoto/odm_orthophoto.tif",
    "dsm": "odm_dem/dsm.tif",
    "dtm": "odm_dem/dtm.tif",
}
_POINT_CLOUD_OUTPUTS = {
    "point_cloud_laz": "odm_georeferencing/odm_georeferenced_model.laz",
}


def _run_json(command: list[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return None, {
            "inspection_status": "unavailable",
            "inspection_error": f"{command[0]} not found",
        }
    except subprocess.TimeoutExpired:
        return None, {
            "inspection_status": "error",
            "inspection_error": f"{command[0]} timed out",
        }

    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        return None, {
            "inspection_status": "error",
            "inspection_error": message or f"{command[0]} exited {result.returncode}",
        }

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, {
            "inspection_status": "error",
            "inspection_error": f"{command[0]} returned invalid JSON",
        }
    if not isinstance(payload, dict):
        return None, {
            "inspection_status": "error",
            "inspection_error": f"{command[0]} returned non-object JSON",
        }
    return payload, {"inspection_status": "ok", "inspection_error": None}


def inspect_geotiff(path: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "inspection_status": "not_applicable",
        "inspection_error": None,
        "has_crs": False,
        "has_geotransform": False,
        "georeferencing_verified": False,
    }
    if not path.is_file() or path.stat().st_size <= 0:
        return evidence

    payload, inspection = _run_json(["gdalinfo", "-json", str(path)])
    evidence.update(inspection)
    if payload is None:
        return evidence

    coordinate_system = payload.get("coordinateSystem")
    if not isinstance(coordinate_system, dict):
        coordinate_system = {}
    wkt = coordinate_system.get("wkt")
    geotransform = payload.get("geoTransform")
    stac = payload.get("stac")
    if not isinstance(stac, dict):
        stac = {}

    has_crs = isinstance(wkt, str) and bool(wkt.strip())
    has_geotransform = (
        isinstance(geotransform, list)
        and len(geotransform) == 6
        and all(isinstance(value, (int, float)) for value in geotransform)
    )
    evidence.update({
        "has_crs": has_crs,
        "has_geotransform": has_geotransform,
        "georeferencing_verified": has_crs and has_geotransform,
        "raster_size": payload.get("size"),
        "geo_transform": geotransform if has_geotransform else None,
        "epsg": stac.get("proj:epsg"),
        "crs_wkt": wkt if has_crs else None,
    })
    return evidence


_CRS_KEYS = {
    "spatialreference",
    "comp_spatialreference",
    "wkt",
    "prettywkt",
    "proj4",
}


def _crs_values(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                str(key).lower() in _CRS_KEYS
                and isinstance(item, str)
                and item.strip()
            ):
                found.append(item.strip())
            found.extend(_crs_values(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_crs_values(item))
    return found


def inspect_laz(path: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "inspection_status": "not_applicable",
        "inspection_error": None,
        "crs_reported": False,
    }
    if not path.is_file() or path.stat().st_size <= 0:
        return evidence

    payload, inspection = _run_json(["pdal", "info", "--metadata", str(path)])
    evidence.update(inspection)
    if payload is None:
        return evidence

    crs_values = _crs_values(payload)
    evidence.update({
        "crs_reported": bool(crs_values),
        "crs_metadata": crs_values[:4],
    })
    return evidence


def build_odm_result_evidence(
    project_dir: Path,
    input_manifest: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}

    for kind, relative in _RASTER_OUTPUTS.items():
        outputs[kind] = {
            "relative_path": relative,
            **inspect_geotiff(project_dir / relative),
        }
    for kind, relative in _POINT_CLOUD_OUTPUTS.items():
        outputs[kind] = {
            "relative_path": relative,
            **inspect_laz(project_dir / relative),
        }

    raster_verified = sum(
        1
        for kind in _RASTER_OUTPUTS
        if outputs[kind].get("georeferencing_verified") is True
    )
    point_cloud_crs_reported = sum(
        1
        for kind in _POINT_CLOUD_OUTPUTS
        if outputs[kind].get("crs_reported") is True
    )
    existing_outputs = sum(
        1 for item in outputs.values() if item.get("exists") is True
    )

    evidence = {
        "schema": "geophoto.odm.georeferencing-evidence.v1",
        "input_georeferencing": input_manifest.get("georeferencing"),
        "outputs": outputs,
        "summary": {
            "existing_outputs": existing_outputs,
            "raster_outputs_with_verified_georeferencing": raster_verified,
            "point_cloud_outputs_with_reported_crs": point_cloud_crs_reported,
        },
        "interpretation": (
            "verified means the inspection tool reported both CRS and a GeoTransform "
            "for a raster; unavailable/error never implies valid georeferencing"
        ),
    }
    path = project_dir / "geophoto-odm-evidence.json"
    path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return path, evidence
