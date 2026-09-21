#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "backend" / "app" / "map_catalog.json"


def load_catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def validate_mbtiles(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 4096:
        raise RuntimeError("Downloaded file is too small to be a valid MBTiles database")
    with sqlite3.connect(path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('metadata','tiles')"
            )
        }
        if tables != {"metadata", "tiles"}:
            raise RuntimeError("Downloaded SQLite file does not contain MBTiles metadata/tiles tables")


def download(pack: dict, data_dir: Path, force: bool) -> None:
    maps_dir = data_dir / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    target = maps_dir / pack["filename"]

    if target.exists() and not force:
        validate_mbtiles(target)
        print(f"[ok] {pack['name']}: already installed at {target}")
        return

    partial = target.with_suffix(target.suffix + ".part")
    req = urllib.request.Request(
        pack["url"],
        headers={"User-Agent": "GeoPhotoConverter/0.1 offline-map-installer"},
    )
    print(f"[download] {pack['name']} -> {target}")
    try:
        with urllib.request.urlopen(req, timeout=60) as response, partial.open("wb") as out:
            total = int(response.headers.get("Content-Length", "0"))
            done = 0
            while True:
                chunk = response.read(4 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1024 / 1024:.0f} / {total / 1024 / 1024:.0f} MiB ({done * 100 / total:.1f}%)", end="", flush=True)
        if total:
            print()
        validate_mbtiles(partial)
        partial.replace(target)
        print(f"[ok] installed {pack['id']}")
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def main() -> int:
    catalog = load_catalog()
    packs = {pack["id"]: pack for pack in catalog["packs"]}

    parser = argparse.ArgumentParser(description="Install GeoPhotoConverter offline map packs")
    parser.add_argument(
        "region",
        choices=[*packs.keys(), "south-germany"],
        help="Map pack id or the south-germany group",
    )
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    selected = (
        [pack for pack in packs.values() if pack.get("group") == "south-germany"]
        if args.region == "south-germany"
        else [packs[args.region]]
    )

    for pack in selected:
        download(pack, args.data_dir.resolve(), args.force)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130)
