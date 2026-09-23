from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from common import images


def _write_dataset(
    db_path: Path,
    files: list[tuple[str, Path, dict]],
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE files (
                dataset_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT,
                metadata_json TEXT
            )
            """
        )
        for relative_path, stored_path, metadata in files:
            conn.execute(
                """
                INSERT INTO files(
                    dataset_id, relative_path, stored_path,
                    size_bytes, sha256, metadata_json
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    "dataset-1",
                    relative_path,
                    str(stored_path),
                    stored_path.stat().st_size,
                    relative_path,
                    json.dumps(metadata),
                ),
            )


def test_prepare_multispectral_images_uses_exact_qa_selection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    files: list[tuple[str, Path, dict]] = []
    selected_paths: list[str] = []
    for capture in ("DJI_9201", "DJI_9202"):
        for suffix in ("D.JPG", "MS_G.TIF", "MS_R.TIF", "MS_RE.TIF", "MS_NIR.TIF"):
            relative = f"M3M/{capture}_{suffix}"
            source = source_root / f"{capture}_{suffix}"
            source.write_bytes(relative.encode())
            files.append(
                (
                    relative,
                    source,
                    {
                        "camera": {"model": "Mavic 3 Multispectral"},
                        "dji": {"product_name": "Mavic 3 Multispectral"},
                    },
                )
            )
            selected_paths.append(relative)

    excluded_relative = "M3M/DJI_9299_MS_NIR.TIF"
    excluded_source = source_root / "DJI_9299_MS_NIR.TIF"
    excluded_source.write_bytes(b"excluded")
    files.append(
        (
            excluded_relative,
            excluded_source,
            {
                "camera": {"model": "Mavic 3 Multispectral"},
                "dji": {"product_name": "Mavic 3 Multispectral"},
            },
        )
    )

    db_path = tmp_path / "geophoto.db"
    _write_dataset(db_path, files)
    monkeypatch.setattr(images, "DB_PATH", db_path)

    target = tmp_path / "project" / "images"
    manifest = images.prepare_multispectral_images(
        "dataset-1",
        target,
        selection={
            "selected_capture_groups": ["group-a", "group-b"],
            "selected_relative_paths": selected_paths,
            "excluded": [
                {
                    "relative_path": excluded_relative,
                    "capture_group": "group-c",
                    "reason": "incomplete_capture_group",
                    "missing_media_kinds": ["MS_GREEN", "MS_RED", "MS_RED_EDGE"],
                }
            ],
        },
    )

    assert manifest["selection_mode"] == "qa"
    assert manifest["prepared_count"] == 10
    assert manifest["selected_path_count"] == 10
    assert manifest["missing_selected_paths"] == []
    assert {item["relative_path"] for item in manifest["prepared"]} == set(selected_paths)

    excluded = next(
        item for item in manifest["skipped"]
        if item["relative_path"] == excluded_relative
    )
    assert excluded["reason"] == "incomplete_capture_group"
    assert excluded["capture_group"] == "group-c"
    assert excluded["missing_media_kinds"] == [
        "MS_GREEN",
        "MS_RED",
        "MS_RED_EDGE",
    ]


def test_prepare_multispectral_images_reports_missing_selected_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "geophoto.db"
    _write_dataset(db_path, [])
    monkeypatch.setattr(images, "DB_PATH", db_path)

    manifest = images.prepare_multispectral_images(
        "dataset-1",
        tmp_path / "images",
        selection={
            "selected_capture_groups": ["group-a"],
            "selected_relative_paths": ["M3M/DJI_MISSING_MS_G.TIF"],
            "excluded": [],
        },
    )

    assert manifest["prepared_count"] == 0
    assert manifest["missing_selected_paths"] == [
        "M3M/DJI_MISSING_MS_G.TIF"
    ]
