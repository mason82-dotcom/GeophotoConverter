from __future__ import annotations

import json
from pathlib import Path

import pytest

from workers.common import images as worker_images


_BANDS = (
    ("MS_G.TIF", "Green"),
    ("MS_R.TIF", "Red"),
    ("MS_RE.TIF", "Red Edge"),
    ("MS_NIR.TIF", "NIR"),
)


def _record(
    relative_path: str,
    *,
    capture_uuid: str | None = None,
    band_name: str | None = None,
    stored_path: Path | None = None,
) -> dict:
    dji: dict[str, object] = {
        "product_name": "Mavic 3 Multispectral",
    }
    if capture_uuid is not None:
        dji["capture_uuid"] = capture_uuid
    if band_name is not None:
        dji["band_name"] = band_name
    metadata = {
        "camera": {"make": "DJI", "model": "Mavic 3 Multispectral"},
        "dji": dji,
    }
    return {
        "relative_path": relative_path,
        "stored_path": str(stored_path) if stored_path else relative_path,
        "size_bytes": 1,
        "sha256": relative_path,
        "metadata_json": json.dumps(metadata),
    }


def _capture(prefix: str, capture_uuid: str, *, complete: bool = True) -> list[dict]:
    records = [
        _record(
            f"M3M/{prefix}_D.JPG",
            capture_uuid=capture_uuid,
        )
    ]
    bands = _BANDS if complete else (_BANDS[-1],)
    for suffix, band_name in bands:
        records.append(
            _record(
                f"M3M/{prefix}_{suffix}",
                capture_uuid=capture_uuid,
                band_name=band_name,
            )
        )
    return records


def test_multispectral_plan_uses_capture_uuid_and_marks_incomplete_groups():
    records = [
        *_capture("DJI_8001", "capture-a"),
        *_capture("DJI_8002", "capture-b"),
        *_capture("DJI_8003", "capture-c", complete=False),
    ]

    plan = worker_images._multispectral_plan(records)

    assert plan["complete_groups"] == ["dji:capture-a", "dji:capture-b"]
    assert plan["incomplete_groups"] == ["dji:capture-c"]
    assert plan["conflicts"] == []


def test_multispectral_plan_falls_back_to_filename_grouping():
    records = [
        _record("M3M/DJI_8101_D.JPG"),
        *[
            _record(f"M3M/DJI_8101_{suffix}", band_name=band_name)
            for suffix, band_name in _BANDS
        ],
    ]

    plan = worker_images._multispectral_plan(records)

    assert plan["complete_groups"] == ["M3M/DJI_8101"]
    assert plan["incomplete_groups"] == []


def test_prepare_multispectral_images_stages_only_complete_groups(
    monkeypatch,
    tmp_path: Path,
):
    records = [
        *_capture("DJI_8201", "capture-a"),
        *_capture("DJI_8202", "capture-b"),
        *_capture("DJI_8203", "capture-c", complete=False),
    ]
    materialized: list[dict] = []
    for index, record in enumerate(records):
        suffix = Path(record["relative_path"]).suffix
        source = tmp_path / "source" / f"{index:02d}{suffix}"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(f"asset-{index}".encode())
        materialized.append({**record, "stored_path": str(source)})

    monkeypatch.setattr(
        worker_images,
        "_dataset_files",
        lambda dataset_id: materialized,
    )

    manifest = worker_images.prepare_multispectral_images(
        "dataset-1",
        tmp_path / "prepared",
    )

    assert manifest["complete_capture_groups"] == [
        "dji:capture-a",
        "dji:capture-b",
    ]
    assert manifest["incomplete_capture_groups"] == ["dji:capture-c"]
    assert manifest["prepared_count"] == 10
    assert len(
        [
            item
            for item in manifest["skipped"]
            if item["reason"] == "incomplete_m3m_capture_group"
        ]
    ) == 2
    assert {
        item["capture_group"]
        for item in manifest["prepared"]
    } == {"dji:capture-a", "dji:capture-b"}


def test_prepare_multispectral_images_rejects_classification_conflicts(
    monkeypatch,
    tmp_path: Path,
):
    records = _capture("DJI_8301", "capture-a")
    conflicting = records[1].copy()
    metadata = json.loads(conflicting["metadata_json"])
    metadata["dji"]["band_name"] = "Red"
    conflicting["metadata_json"] = json.dumps(metadata)
    records[1] = conflicting

    monkeypatch.setattr(
        worker_images,
        "_dataset_files",
        lambda dataset_id: records,
    )

    with pytest.raises(ValueError, match="M3M classification conflict"):
        worker_images.prepare_multispectral_images(
            "dataset-2",
            tmp_path / "prepared",
        )
