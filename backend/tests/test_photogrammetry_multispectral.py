from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.config import DATA_ROOT
from app.photogrammetry_multispectral import (
    OUTPUT_NODATA,
    classify_ndvi_zones,
    compute_vegetation_index,
    inspect_multispectral_orthophoto,
)
from app.storage import store


def _write_multiband(path: Path, *, descriptions: bool = True) -> None:
    width = 6
    height = 4
    data = np.zeros((4, height, width), dtype=np.float32)
    data[0] = 0.20  # Red
    data[1] = 0.40  # Green
    data[2] = 0.80  # NIR
    data[3] = 0.30  # Red Edge
    data[:, 0, 0] = np.nan

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=4,
        dtype="float32",
        crs="EPSG:32632",
        transform=from_origin(500000.0, 5500000.0, 0.05, 0.05),
        nodata=np.nan,
    ) as dst:
        dst.write(data)
        if descriptions:
            dst.set_band_description(1, "Red")
            dst.set_band_description(2, "Green")
            dst.set_band_description(3, "NIR")
            dst.set_band_description(4, "Red Edge")


def test_multispectral_band_map_prefers_raster_descriptions(tmp_path: Path):
    source = tmp_path / "m3m.tif"
    _write_multiband(source)

    info = inspect_multispectral_orthophoto(source)

    assert info["band_map"] == {
        "red": 1,
        "green": 2,
        "nir": 3,
        "rededge": 4,
    }
    assert info["mapping_source"] == "raster_band_descriptions"
    assert info["warnings"] == []


def test_m3m_fallback_is_explicit_and_four_band_only(tmp_path: Path):
    source = tmp_path / "m3m-no-descriptions.tif"
    _write_multiband(source, descriptions=False)

    with pytest.raises(ValueError, match="Bandzuordnung"):
        inspect_multispectral_orthophoto(source)

    info = inspect_multispectral_orthophoto(
        source,
        allow_m3m_fallback=True,
    )
    assert info["band_map"] == {
        "red": 1,
        "green": 2,
        "nir": 3,
        "rededge": 4,
    }
    assert info["mapping_source"] == "odm_m3m_fallback_order"
    assert info["warnings"][0]["code"] == "M3M_BAND_DESCRIPTION_FALLBACK"


@pytest.mark.parametrize(
    ("index_type", "expected"),
    [
        ("ndvi", 0.60),
        ("ndre", 0.45454545),
        ("gndvi", 0.33333333),
    ],
)
def test_compute_vegetation_indices_cpu_preserve_georeferencing(
    tmp_path: Path,
    index_type: str,
    expected: float,
):
    source = tmp_path / "m3m.tif"
    output = tmp_path / f"{index_type}.tif"
    _write_multiband(source)

    result = compute_vegetation_index(
        source,
        output,
        index_type=index_type,
        backend="cpu",
        tile_size=128,
    )

    assert result["backend_used"] == "cpu"
    assert result["valid_pixels"] == 23
    assert result["minimum"] == pytest.approx(expected, abs=1e-6)
    assert result["maximum"] == pytest.approx(expected, abs=1e-6)
    assert result["mean"] == pytest.approx(expected, abs=1e-6)

    with rasterio.open(source) as src, rasterio.open(output) as dst:
        assert dst.crs == src.crs
        assert dst.transform == src.transform
        assert dst.width == src.width
        assert dst.height == src.height
        assert dst.count == 1
        assert dst.descriptions[0] == index_type.upper()
        values = dst.read(1)
        assert values[0, 0] == OUTPUT_NODATA
        assert values[1, 1] == pytest.approx(expected, abs=1e-6)


def test_explicit_cuda_is_strict_without_device(monkeypatch, tmp_path: Path):
    source = tmp_path / "m3m.tif"
    output = tmp_path / "ndvi.tif"
    _write_multiband(source)

    monkeypatch.setattr(
        "app.photogrammetry_multispectral.probe_cupy",
        lambda: {
            "available": False,
            "version": None,
            "device_count": 0,
            "device_name": None,
        },
    )

    with pytest.raises(RuntimeError, match="CuPy"):
        compute_vegetation_index(
            source,
            output,
            index_type="ndvi",
            backend="cuda",
            tile_size=128,
        )

    assert not output.exists()


def test_ndvi_scouting_zones_preserve_raster_geometry(tmp_path: Path):
    source = tmp_path / "ndvi.tif"
    output = tmp_path / "zones.tif"
    values = np.asarray(
        [
            [-0.5, 0.1, 0.3],
            [0.5, 0.7, 0.9],
        ],
        dtype=np.float32,
    )

    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=3,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:32632",
        transform=from_origin(500000.0, 5500000.0, 0.10, 0.10),
        nodata=OUTPUT_NODATA,
    ) as dst:
        dst.write(values, 1)
        dst.set_band_description(1, "NDVI")

    result = classify_ndvi_zones(
        source,
        output,
        thresholds=(0.2, 0.4, 0.6, 0.8),
        tile_size=128,
    )

    assert result["class_counts"] == {
        "0": 0,
        "1": 2,
        "2": 1,
        "3": 1,
        "4": 1,
        "5": 1,
    }

    with rasterio.open(source) as src, rasterio.open(output) as dst:
        assert dst.crs == src.crs
        assert dst.transform == src.transform
        assert dst.descriptions[0] == "NDVI_SCOUTING_ZONE"
        assert dst.read(1).tolist() == [[1, 1, 2], [3, 4, 5]]


def test_zone_thresholds_must_be_strictly_increasing(tmp_path: Path):
    source = tmp_path / "ndvi.tif"
    output = tmp_path / "zones.tif"

    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=1,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:32632",
        transform=from_origin(0.0, 1.0, 1.0, 1.0),
    ) as dst:
        dst.write(np.asarray([[0.5]], dtype=np.float32), 1)

    with pytest.raises(ValueError, match="strictly increasing"):
        classify_ndvi_zones(
            source,
            output,
            thresholds=(0.2, 0.4, 0.4, 0.8),
            tile_size=128,
        )


def test_api_inspects_multiband_orthophoto(client):
    dataset = store.create_dataset("M3M result", None)
    job = store.create_job(dataset["id"], "odm", "standard", "multispectral")

    artifact_path = DATA_ROOT / "jobs" / job["id"] / "project" / "odm_orthophoto" / "odm_orthophoto.tif"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    _write_multiband(artifact_path)

    store.update_job(
        job["id"],
        status="completed",
        progress=100,
        artifacts=[
            {
                "type": "multiband_orthophoto",
                "name": artifact_path.name,
                "relative_path": str(artifact_path.relative_to(DATA_ROOT)).replace("\\", "/"),
                "size_bytes": artifact_path.stat().st_size,
            }
        ],
    )

    response = client.get(
        f"/api/v1/jobs/{job['id']}/artifacts/0/multispectral"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_type"] == "multiband_orthophoto"
    assert body["band_map"] == {
        "red": 1,
        "green": 2,
        "nir": 3,
        "rededge": 4,
    }
    assert body["mapping_source"] == "raster_band_descriptions"
