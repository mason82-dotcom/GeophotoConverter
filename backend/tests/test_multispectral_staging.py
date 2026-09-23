from __future__ import annotations

import json
from pathlib import Path

from workers.common import images


def _record(
    root: Path,
    relative_path: str,
    *,
    capture_uuid: str,
    band_name: str | None = None,
    model: str = "Mavic 3 Multispectral",
) -> dict:
    source = root / relative_path.replace("/", "__")
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(relative_path.encode())

    dji: dict[str, object] = {
        "capture_uuid": capture_uuid,
        "product_name": model,
    }
    if band_name is not None:
        dji["band_name"] = band_name

    return {
        "relative_path": relative_path,
        "stored_path": str(source),
        "size_bytes": source.stat().st_size,
        "sha256": f"sha-{relative_path}",
        "metadata_json": json.dumps(
            {
                "camera": {"make": "DJI", "model": model},
                "dji": dji,
            }
        ),
    }


def _complete_group(
    root: Path,
    prefix: str,
    capture_uuid: str,
) -> list[dict]:
    return [
        _record(
            root,
            f"M3M/{prefix}_D.JPG",
            capture_uuid=capture_uuid,
        ),
        _record(
            root,
            f"M3M/{prefix}_MS_G.TIF",
            capture_uuid=capture_uuid,
            band_name="Green",
        ),
        _record(
            root,
            f"M3M/{prefix}_MS_R.TIF",
            capture_uuid=capture_uuid,
            band_name="Red",
        ),
        _record(
            root,
            f"M3M/{prefix}_MS_RE.TIF",
            capture_uuid=capture_uuid,
            band_name="Red Edge",
        ),
        _record(
            root,
            f"M3M/{prefix}_MS_NIR.TIF",
            capture_uuid=capture_uuid,
            band_name="NIR",
        ),
    ]


def test_multispectral_staging_excludes_incomplete_capture_group(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        *_complete_group(tmp_path, "DJI_1001", "capture-a"),
        *_complete_group(tmp_path, "DJI_1002", "capture-b"),
        _record(
            tmp_path,
            "M3M/DJI_1003_D.JPG",
            capture_uuid="capture-incomplete",
        ),
        _record(
            tmp_path,
            "M3M/DJI_1003_MS_G.TIF",
            capture_uuid="capture-incomplete",
            band_name="Green",
        ),
        _record(
            tmp_path,
            "M3M/DJI_1003_MS_NIR.TIF",
            capture_uuid="capture-incomplete",
            band_name="NIR",
        ),
    ]
    monkeypatch.setattr(images, "_dataset_files", lambda _: records)

    target = tmp_path / "staged"
    manifest = images.prepare_multispectral_images("dataset-1", target)

    assert manifest["selected_group_count"] == 2
    assert manifest["selected_capture_groups"] == [
        "dji:capture-a",
        "dji:capture-b",
    ]
    assert manifest["prepared_count"] == 10
    assert all(
        item["capture_group"] != "dji:capture-incomplete"
        for item in manifest["prepared"]
    )

    incomplete = next(
        group
        for group in manifest["capture_groups"]
        if group["capture_group"] == "dji:capture-incomplete"
    )
    assert incomplete["status"] == "incomplete_capture_group"
    assert incomplete["missing_media_kinds"] == ["MS_RED", "MS_RED_EDGE"]

    skipped = [
        item
        for item in manifest["skipped"]
        if item.get("capture_group") == "dji:capture-incomplete"
    ]
    assert len(skipped) == 3
    assert {item["reason"] for item in skipped} == {
        "incomplete_capture_group"
    }

    written = json.loads(
        (target / "geophoto-input-manifest.json").read_text(encoding="utf-8")
    )
    assert written["selected_group_count"] == 2
    assert written["prepared_count"] == 10


def test_capture_uuid_groups_files_with_different_filename_bases(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        _record(
            tmp_path,
            "M3M/DJI_2001_D.JPG",
            capture_uuid="shared-capture",
        ),
        _record(
            tmp_path,
            "M3M/DJI_9001_MS_G.TIF",
            capture_uuid="shared-capture",
            band_name="Green",
        ),
        _record(
            tmp_path,
            "M3M/DJI_9002_MS_R.TIF",
            capture_uuid="shared-capture",
            band_name="Red",
        ),
        _record(
            tmp_path,
            "M3M/DJI_9003_MS_RE.TIF",
            capture_uuid="shared-capture",
            band_name="Red Edge",
        ),
        _record(
            tmp_path,
            "M3M/DJI_9004_MS_NIR.TIF",
            capture_uuid="shared-capture",
            band_name="NIR",
        ),
    ]
    monkeypatch.setattr(images, "_dataset_files", lambda _: records)

    manifest = images.prepare_multispectral_images(
        "dataset-2",
        tmp_path / "uuid-staged",
    )

    assert manifest["selected_group_count"] == 1
    assert manifest["selected_capture_groups"] == ["dji:shared-capture"]
    assert manifest["prepared_count"] == 5
    assert {
        item["capture_group_source"]
        for item in manifest["prepared"]
    } == {"authoritative"}


def test_conflicting_extra_group_is_not_staged(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        *_complete_group(tmp_path, "DJI_3001", "capture-clean-a"),
        *_complete_group(tmp_path, "DJI_3002", "capture-clean-b"),
        *_complete_group(tmp_path, "DJI_3003", "capture-conflict"),
    ]
    conflict = next(
        item
        for item in records
        if item["relative_path"].endswith("DJI_3003_MS_NIR.TIF")
    )
    metadata = json.loads(conflict["metadata_json"])
    metadata["dji"]["band_name"] = "Red"
    conflict["metadata_json"] = json.dumps(metadata)

    monkeypatch.setattr(images, "_dataset_files", lambda _: records)

    manifest = images.prepare_multispectral_images(
        "dataset-3",
        tmp_path / "conflict-staged",
    )

    assert manifest["selected_group_count"] == 2
    assert manifest["prepared_count"] == 10

    blocked = next(
        group
        for group in manifest["capture_groups"]
        if group["capture_group"] == "dji:capture-conflict"
    )
    assert blocked["status"] == "classification_conflict"
    assert blocked["blocking_conflicts"] == [
        "band_metadata_filename_conflict"
    ]
    assert all(
        item["capture_group"] != "dji:capture-conflict"
        for item in manifest["prepared"]
    )
