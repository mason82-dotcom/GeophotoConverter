from __future__ import annotations

import pytest

from app.photogrammetry_epoch import (
    build_epoch_report,
    change_mask,
    summarize_cloud_change,
    summarize_raster_change,
    validate_epoch_pair,
)


def _epoch(epoch_id: str, captured_at: str, crs: str = "EPSG:32632") -> dict:
    return {
        "id": epoch_id,
        "captured_at": captured_at,
        "crs": {
            "identifier": crs,
            "projected": True,
            "metric": True,
        },
    }


def test_epoch_pair_requires_same_metric_projected_crs() -> None:
    result = validate_epoch_pair(
        _epoch("A", "2026-01-01T10:00:00Z"),
        _epoch("B", "2026-02-01T10:00:00Z"),
    )

    assert result["status"] == "ready"
    assert result["crs_identifier"] == "EPSG:32632"
    assert result["issues"] == []


def test_epoch_pair_blocks_crs_mismatch() -> None:
    result = validate_epoch_pair(
        _epoch("A", "2026-01-01T10:00:00Z", "EPSG:32632"),
        _epoch("B", "2026-02-01T10:00:00Z", "EPSG:32633"),
    )

    assert result["status"] == "blocked"
    assert any(
        issue["code"] == "EPOCH_CRS_MISMATCH"
        for issue in result["issues"]
    )


def test_epoch_pair_blocks_wrong_time_order() -> None:
    result = validate_epoch_pair(
        _epoch("A", "2026-02-01T10:00:00Z"),
        _epoch("B", "2026-01-01T10:00:00Z"),
    )

    assert result["status"] == "blocked"
    assert any(
        issue["code"] == "EPOCH_ORDER_INVALID"
        for issue in result["issues"]
    )


def test_change_mask_is_signed_and_thresholded() -> None:
    assert change_mask(
        [-0.3, -0.1, 0.0, 0.1, 0.3, None],
        threshold_m=0.2,
    ) == [-1, 0, 0, 0, 1, None]


def test_raster_change_calculates_cut_fill_and_net_volume() -> None:
    result = summarize_raster_change(
        [-0.5, -0.3, 0.0, 0.1, 0.4, 0.6],
        cell_area_m2=4.0,
        threshold_m=0.2,
    )

    assert result["changed_cell_count"] == 4
    assert result["stable_cell_count"] == 2
    assert result["changed_area_m2"] == pytest.approx(16.0)
    assert result["cut_volume_m3"] == pytest.approx(3.2)
    assert result["fill_volume_m3"] == pytest.approx(4.0)
    assert result["net_volume_m3"] == pytest.approx(0.8)


def test_cloud_change_does_not_invent_volume() -> None:
    result = summarize_cloud_change(
        [-0.4, -0.1, 0.0, 0.25, 0.5],
        threshold_m=0.2,
    )

    assert result["valid_point_count"] == 5
    assert result["changed_point_count"] == 3
    assert "net_volume_m3" not in result


def test_epoch_report_preserves_provenance() -> None:
    reference = _epoch("flight-1", "2026-01-01T10:00:00Z")
    comparison = _epoch("flight-2", "2026-03-01T10:00:00Z")
    raster = summarize_raster_change(
        [0.0, 0.3],
        cell_area_m2=1.0,
        threshold_m=0.2,
    )

    report = build_epoch_report(
        reference=reference,
        comparison=comparison,
        raster_change=raster,
        provenance={
            "reference_artifact": "job-a/dsm.tif",
            "comparison_artifact": "job-b/dsm.tif",
        },
    )

    assert report["status"] == "ready"
    assert report["provenance"]["reference_artifact"] == "job-a/dsm.tif"


def test_epoch_report_warns_without_change_product() -> None:
    report = build_epoch_report(
        reference=_epoch("A", "2026-01-01T10:00:00Z"),
        comparison=_epoch("B", "2026-02-01T10:00:00Z"),
    )

    assert report["status"] == "warning"
    assert any(
        issue["code"] == "EPOCH_CHANGE_PRODUCT_MISSING"
        for issue in report["issues"]
    )


def test_invalid_cell_area_is_rejected() -> None:
    with pytest.raises(ValueError, match="cell_area_m2"):
        summarize_raster_change(
            [0.2],
            cell_area_m2=0.0,
            threshold_m=0.1,
        )



def test_epoch_pair_does_not_trust_declared_crs_flags() -> None:
    reference = _epoch("A", "2026-01-01T10:00:00Z", "EPSG:4326")
    comparison = _epoch("B", "2026-02-01T10:00:00Z", "EPSG:4326")

    reference["crs"]["projected"] = True
    reference["crs"]["metric"] = True
    comparison["crs"]["projected"] = True
    comparison["crs"]["metric"] = True

    result = validate_epoch_pair(reference, comparison)

    assert result["status"] == "blocked"
    assert any(
        issue["code"] == "EPOCH_CRS_NOT_METRIC_PROJECTED"
        for issue in result["issues"]
    )


def test_epoch_pair_rejects_unresolvable_crs_identifier() -> None:
    result = validate_epoch_pair(
        _epoch("A", "2026-01-01T10:00:00Z", "NOT-A-CRS"),
        _epoch("B", "2026-02-01T10:00:00Z", "NOT-A-CRS"),
    )

    assert result["status"] == "blocked"
    assert any(
        issue["code"] == "EPOCH_CRS_INVALID"
        for issue in result["issues"]
    )
