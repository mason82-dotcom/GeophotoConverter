from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
    conflicting = _record(
        "M3M/DJI_8301_EXTRA_MS_NIR.TIF",
        capture_uuid="capture-a",
        band_name="Red",
    )
    records.append(conflicting)

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



def test_prepare_multispectral_images_excludes_group_with_missing_source(
    monkeypatch,
    tmp_path: Path,
):
    records = [
        *_capture("DJI_8401", "capture-a"),
        *_capture("DJI_8402", "capture-b"),
        *_capture("DJI_8403", "capture-c"),
    ]
    materialized: list[dict] = []
    missing_path = "M3M/DJI_8403_MS_NIR.TIF"
    for index, record in enumerate(records):
        suffix = Path(record["relative_path"]).suffix
        source = tmp_path / "source" / f"{index:02d}{suffix}"
        if record["relative_path"] != missing_path:
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(f"asset-{index}".encode())
        materialized.append({**record, "stored_path": str(source)})

    monkeypatch.setattr(
        worker_images,
        "_dataset_files",
        lambda dataset_id: materialized,
    )

    manifest = worker_images.prepare_multispectral_images(
        "dataset-3",
        tmp_path / "prepared",
    )

    assert manifest["complete_capture_groups"] == [
        "dji:capture-a",
        "dji:capture-b",
    ]
    assert manifest["unstageable_capture_groups"] == ["dji:capture-c"]
    assert manifest["prepared_count"] == 10
    assert any(
        item["capture_group"] == "dji:capture-c"
        and item["reason"] == "unstageable_m3m_capture_group"
        for item in manifest["skipped"]
    )



def test_incomplete_group_conflict_is_diagnostic_only(
    monkeypatch,
    tmp_path: Path,
):
    records = [
        *_capture("DJI_8501", "capture-clean-a"),
        *_capture("DJI_8502", "capture-clean-b"),
        *_capture("DJI_8503", "capture-incomplete", complete=False),
    ]
    conflicting = next(
        item
        for item in records
        if item["relative_path"].endswith("DJI_8503_MS_NIR.TIF")
    )
    metadata = json.loads(conflicting["metadata_json"])
    metadata["dji"]["band_name"] = "Red"
    conflicting["metadata_json"] = json.dumps(metadata)

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
        "dataset-incomplete-conflict",
        tmp_path / "prepared-incomplete-conflict",
    )

    assert manifest["complete_capture_groups"] == [
        "dji:capture-clean-a",
        "dji:capture-clean-b",
    ]
    assert manifest["incomplete_capture_groups"] == [
        "dji:capture-incomplete"
    ]
    assert manifest["blocking_conflict_groups"] == []
    assert manifest["prepared_count"] == 10
    assert manifest["classification_conflicts"] == [
        {
            "relative_path": "M3M/DJI_8503_MS_NIR.TIF",
            "capture_group": "dji:capture-incomplete",
            "codes": ["band_metadata_filename_conflict"],
        }
    ]


def test_multispectral_plan_marks_complete_conflict_group_as_blocking():
    records = _capture("DJI_8601", "capture-conflict")
    records.append(
        _record(
            "M3M/DJI_8601_EXTRA_MS_NIR.TIF",
            capture_uuid="capture-conflict",
            band_name="Red",
        )
    )

    plan = worker_images._multispectral_plan(records)

    assert plan["complete_groups"] == ["dji:capture-conflict"]
    assert plan["blocking_conflict_groups"] == ["dji:capture-conflict"]



def test_odm_worker_image_ships_canonical_media_modules():
    dockerfile = (REPO_ROOT / "workers" / "odm" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "backend/app/classifier.py" in dockerfile
    assert "backend/app/photogrammetry.py" in dockerfile
    assert "/worker/app/" in dockerfile
