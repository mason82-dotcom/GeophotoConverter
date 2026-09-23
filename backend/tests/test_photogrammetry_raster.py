from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.transform import from_origin

from app.photogrammetry_raster import evaluate_raster_set, inspect_raster


def _write_tif(
    path: Path,
    *,
    crs="EPSG:32632",
    x=500000.0,
    y=5500000.0,
    res=0.05,
    transform=None,
):
    data = np.ones((1, 20, 30), dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=30,
        height=20,
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform or from_origin(x, y, res, res),
        nodata=-9999.0,
    ) as dst:
        dst.write(data)


def test_inspect_projected_geotiff(tmp_path: Path):
    path = tmp_path / "ortho.tif"
    _write_tif(path)

    result = inspect_raster(path)

    assert result["status"] == "ready"
    assert result["driver"] == "GTiff"
    assert result["crs"]["identifier"] == "EPSG:32632"
    assert result["crs"]["metric"] is True
    assert result["crs"]["linear_units"] == "metre"
    assert result["resolution"] == {"x": 0.05, "y": 0.05}
    assert result["band_count"] == 1
    assert result["nodata"] == -9999.0


def test_missing_crs_blocks_raster(tmp_path: Path):
    path = tmp_path / "no-crs.tif"
    _write_tif(path, crs=None)

    result = inspect_raster(path)

    assert result["status"] == "blocked"
    assert any(issue["code"] == "RASTER_CRS_MISSING" for issue in result["issues"])


def test_geographic_crs_is_warning(tmp_path: Path):
    path = tmp_path / "geo.tif"
    _write_tif(path, crs="EPSG:4326", x=8.5, y=49.3, res=0.00001)

    result = inspect_raster(path)

    assert result["status"] == "warning"
    assert result["crs"]["metric"] is False
    assert any(
        issue["code"] == "RASTER_CRS_NOT_PROJECTED"
        for issue in result["issues"]
    )


def test_rotated_transform_reports_vector_resolution(tmp_path: Path):
    path = tmp_path / "rotated.tif"
    transform = Affine(0.04, 0.03, 500000.0, 0.03, -0.04, 5500000.0)
    _write_tif(path, transform=transform)

    result = inspect_raster(path)

    assert result["status"] == "warning"
    assert result["resolution"]["x"] == 0.05
    assert result["resolution"]["y"] == 0.05
    assert any(
        issue["code"] == "RASTER_ROTATED_OR_SHEARED"
        for issue in result["issues"]
    )


def test_raster_set_same_crs_and_overlap_is_ready(tmp_path: Path):
    a = tmp_path / "ortho.tif"
    b = tmp_path / "dsm.tif"
    _write_tif(a)
    _write_tif(b, x=500000.5)

    ra = inspect_raster(a)
    rb = inspect_raster(b)
    ra["kind"] = "orthophoto"
    rb["kind"] = "dsm"

    result = evaluate_raster_set([ra, rb])

    assert result["status"] == "ready"
    assert result["crs_identifiers"] == ["EPSG:32632"]


def test_raster_set_crs_mismatch_blocks(tmp_path: Path):
    a = tmp_path / "a.tif"
    b = tmp_path / "b.tif"
    _write_tif(a, crs="EPSG:32632")
    _write_tif(b, crs="EPSG:32633")

    result = evaluate_raster_set([inspect_raster(a), inspect_raster(b)])

    assert result["status"] == "blocked"
    assert any(
        issue["code"] == "RASTER_SET_CRS_MISMATCH"
        for issue in result["issues"]
    )


def test_raster_set_disjoint_bounds_blocks(tmp_path: Path):
    a = tmp_path / "a.tif"
    b = tmp_path / "b.tif"
    _write_tif(a, x=500000.0)
    _write_tif(b, x=600000.0)

    result = evaluate_raster_set([inspect_raster(a), inspect_raster(b)])

    assert result["status"] == "blocked"
    assert any(
        issue["code"] == "RASTER_SET_BOUNDS_DISJOINT"
        for issue in result["issues"]
    )
