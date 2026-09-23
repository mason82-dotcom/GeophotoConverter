from __future__ import annotations

from app.qa import dataset_qa


def _file(
    path: str,
    capture_uuid: str,
    band_name: str | None = None,
) -> dict:
    dji = {
        "capture_uuid": capture_uuid,
        "product_name": "Mavic 3 Multispectral",
    }
    if band_name is not None:
        dji["band_name"] = band_name
    return {
        "relative_path": path,
        "metadata": {
            "camera": {"make": "DJI", "model": "Mavic 3 Multispectral"},
            "gps": {"latitude": 49.1, "longitude": 8.5, "altitude": 120.0},
            "dji": dji,
        },
        "scan_error": None,
    }


def _complete_group(prefix: str, capture_uuid: str) -> list[dict]:
    return [
        _file(f"M3M/{prefix}_D.JPG", capture_uuid),
        _file(f"M3M/{prefix}_MS_G.TIF", capture_uuid, "Green"),
        _file(f"M3M/{prefix}_MS_R.TIF", capture_uuid, "Red"),
        _file(f"M3M/{prefix}_MS_RE.TIF", capture_uuid, "Red Edge"),
        _file(f"M3M/{prefix}_MS_NIR.TIF", capture_uuid, "NIR"),
    ]


def test_complete_m3m_group_with_band_conflict_blocks_readiness() -> None:
    files = [
        *_complete_group("DJI_8101", "capture-clean"),
        *_complete_group("DJI_8102", "capture-conflict"),
        _file(
            "M3M/DJI_8102_EXTRA_MS_NIR.TIF",
            "capture-conflict",
            "Red",
        ),
    ]

    qa = dataset_qa(files)

    assert qa["multispectral"]["complete_groups"] == 2
    assert qa["multispectral"]["classification_conflicts"] == {
        "band_metadata_filename_conflict": 1
    }
    assert qa["multispectral"]["blocking_conflict_count"] == 1
    assert qa["multispectral"]["blocking_conflict_groups"] == [
        "dji:capture-conflict"
    ]

    readiness = qa["readiness"]["odm_multispectral"]
    assert readiness["ready"] is False
    assert readiness["complete_groups"] == 2
    assert readiness["blocking_conflicts"] == 1
    assert readiness["blocking_conflict_groups"] == [
        "dji:capture-conflict"
    ]
    assert "Klassifikationskonflikt" in readiness["reason"]

    warning = next(
        item
        for item in qa["warnings"]
        if item["code"] == "MULTISPECTRAL_CLASSIFICATION_CONFLICT"
    )
    assert warning == {
        "code": "MULTISPECTRAL_CLASSIFICATION_CONFLICT",
        "severity": "error",
        "count": 1,
    }


def test_conflict_in_incomplete_group_does_not_block_clean_complete_groups() -> None:
    files = [
        *_complete_group("DJI_8201", "capture-clean-a"),
        *_complete_group("DJI_8202", "capture-clean-b"),
        _file(
            "M3M/DJI_8299_MS_NIR.TIF",
            "capture-incomplete",
            "Red",
        ),
    ]

    qa = dataset_qa(files)

    assert qa["multispectral"]["complete_groups"] == 2
    assert qa["multispectral"]["classification_conflicts"] == {
        "band_metadata_filename_conflict": 1
    }
    assert qa["multispectral"]["blocking_conflict_count"] == 0
    assert qa["multispectral"]["blocking_conflict_groups"] == []
    assert qa["readiness"]["odm_multispectral"]["ready"] is True
    warning = next(
        item
        for item in qa["warnings"]
        if item["code"] == "MULTISPECTRAL_CLASSIFICATION_CONFLICT"
    )
    assert warning == {
        "code": "MULTISPECTRAL_CLASSIFICATION_CONFLICT",
        "severity": "warning",
        "count": 1,
    }



def test_platform_band_conflict_in_complete_group_blocks_readiness() -> None:
    conflicted_group = _complete_group("DJI_8302", "capture-platform-conflict")
    green = next(
        item
        for item in conflicted_group
        if item["relative_path"].endswith("_MS_G.TIF")
    )
    green["metadata"]["camera"]["model"] = "Mavic 3 Enterprise"
    green["metadata"]["dji"]["product_name"] = "Mavic 3 Enterprise"

    qa = dataset_qa(
        [
            *_complete_group("DJI_8301", "capture-clean"),
            *conflicted_group,
        ]
    )

    assert qa["multispectral"]["complete_groups"] == 2
    assert qa["multispectral"]["classification_conflicts"] == {
        "band_platform_conflict": 1
    }
    assert qa["multispectral"]["blocking_conflict_count"] == 1
    assert qa["multispectral"]["blocking_conflict_groups"] == [
        "dji:capture-platform-conflict"
    ]
    assert qa["readiness"]["odm_multispectral"]["ready"] is False
