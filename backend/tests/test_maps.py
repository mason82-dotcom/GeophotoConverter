from __future__ import annotations

import gzip
import sqlite3

from app.config import MAPS_ROOT


def _create_mbtiles(path):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        conn.execute(
            "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
        )
        conn.executemany(
            "INSERT INTO metadata(name,value) VALUES(?,?)",
            [
                ("minzoom", "0"),
                ("maxzoom", "2"),
                ("bounds", "7.0,47.0,10.5,49.9"),
                ("center", "9.0,48.5,7"),
            ],
        )
        # XYZ z=1/x=1/y=0 maps to TMS row 1.
        conn.execute(
            "INSERT INTO tiles(zoom_level,tile_column,tile_row,tile_data) VALUES(?,?,?,?)",
            (1, 1, 1, gzip.compress(b"vector-tile")),
        )


def test_offline_map_catalog_and_tile_serving(client):
    path = MAPS_ROOT / "baden-wuerttemberg-shortbread-1.0.mbtiles"
    _create_mbtiles(path)

    catalog = client.get("/api/v1/maps")
    assert catalog.status_code == 200
    bw = next(p for p in catalog.json()["packs"] if p["id"] == "baden-wuerttemberg")
    assert bw["installed"] is True
    assert bw["bounds"] == [7.0, 47.0, 10.5, 49.9]

    tilejson = client.get("/api/v1/maps/baden-wuerttemberg/tilejson.json")
    assert tilejson.status_code == 200
    assert tilejson.json()["scheme"] == "xyz"

    tile = client.get("/api/v1/maps/baden-wuerttemberg/tiles/1/1/0.pbf")
    assert tile.status_code == 200
    assert tile.headers["content-encoding"] == "gzip"
    assert tile.content == b"vector-tile"
