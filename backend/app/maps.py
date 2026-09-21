from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from .config import MAPS_ROOT

router = APIRouter(prefix="/api/v1/maps", tags=["maps"])
CATALOG_PATH = Path(__file__).with_name("map_catalog.json")


def _catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _pack(region_id: str) -> dict[str, Any]:
    for pack in _catalog().get("packs", []):
        if pack["id"] == region_id:
            return pack
    raise HTTPException(status_code=404, detail="Unknown offline map pack")


def _map_path(pack: dict[str, Any]) -> Path:
    path = (MAPS_ROOT / pack["filename"]).resolve()
    if MAPS_ROOT.resolve() not in path.parents:
        raise HTTPException(status_code=500, detail="Invalid map pack path")
    return path


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _metadata(path: Path) -> dict[str, str]:
    with _connect(path) as conn:
        rows = conn.execute("SELECT name, value FROM metadata").fetchall()
    return {str(name): str(value) for name, value in rows}


def _bounds(value: str | None) -> list[float] | None:
    if not value:
        return None
    try:
        result = [float(item) for item in value.split(",")]
    except ValueError:
        return None
    return result if len(result) == 4 else None


@router.get("")
def list_map_packs() -> dict[str, Any]:
    catalog = _catalog()
    packs = []
    for pack in catalog.get("packs", []):
        path = _map_path(pack)
        item = {
            **pack,
            "installed": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
        }
        if path.is_file():
            try:
                meta = _metadata(path)
                item["minzoom"] = int(meta["minzoom"]) if meta.get("minzoom") else None
                item["maxzoom"] = int(meta["maxzoom"]) if meta.get("maxzoom") else None
                item["bounds"] = _bounds(meta.get("bounds"))
            except (sqlite3.DatabaseError, ValueError):
                item["status"] = "invalid"
        packs.append(item)

    return {
        "format": catalog.get("format"),
        "attribution": catalog.get("attribution"),
        "license": catalog.get("license"),
        "packs": packs,
    }


@router.get("/{region_id}/tilejson.json")
def tilejson(region_id: str, request: Request) -> dict[str, Any]:
    pack = _pack(region_id)
    path = _map_path(pack)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Offline map pack is not installed")

    meta = _metadata(path)
    base = str(request.base_url).rstrip("/")
    result: dict[str, Any] = {
        "tilejson": "3.0.0",
        "name": pack["name"],
        "scheme": "xyz",
        "tiles": [f"{base}/api/v1/maps/{region_id}/tiles/{{z}}/{{x}}/{{y}}.pbf"],
        "attribution": _catalog().get("attribution"),
    }
    bounds = _bounds(meta.get("bounds"))
    if bounds:
        result["bounds"] = bounds
    if meta.get("minzoom"):
        result["minzoom"] = int(meta["minzoom"])
    if meta.get("maxzoom"):
        result["maxzoom"] = int(meta["maxzoom"])
    if meta.get("center"):
        try:
            result["center"] = [float(v) for v in meta["center"].split(",")]
        except ValueError:
            pass
    return result


@router.get("/{region_id}/tiles/{z}/{x}/{y}.pbf")
def vector_tile(region_id: str, z: int, x: int, y: int) -> Response:
    pack = _pack(region_id)
    path = _map_path(pack)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Offline map pack is not installed")
    if z < 0 or z > 30 or x < 0 or y < 0:
        raise HTTPException(status_code=404, detail="Tile not found")

    # MBTiles stores rows using TMS coordinates; MapLibre requests XYZ.
    tms_y = (1 << z) - 1 - y
    with _connect(path) as conn:
        row = conn.execute(
            """
            SELECT tile_data
            FROM tiles
            WHERE zoom_level=? AND tile_column=? AND tile_row=?
            """,
            (z, x, tms_y),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Tile not found")

    payload = bytes(row[0])
    headers = {"Cache-Control": "public, max-age=86400"}
    if payload.startswith(b"\x1f\x8b"):
        headers["Content-Encoding"] = "gzip"

    return Response(
        content=payload,
        media_type="application/vnd.mapbox-vector-tile",
        headers=headers,
    )
