from __future__ import annotations

import os
import tempfile
from math import isfinite
from pathlib import Path
from typing import Any, Callable

import numpy as np
import rasterio
from rasterio.windows import Window


INDEX_BANDS: dict[str, tuple[str, str]] = {
    "ndvi": ("nir", "red"),
    "ndre": ("nir", "rededge"),
    "gndvi": ("nir", "green"),
}
DEFAULT_CUDA_MIN_PIXELS = 1_048_576
DEFAULT_TILE_SIZE = 1024
OUTPUT_NODATA = -9999.0


class RasterProcessingCancelled(RuntimeError):
    """Raised when a long-running raster operation is cancelled safely."""


def _normalize_band_name(value: str | None) -> str | None:
    if not value:
        return None

    normalized = "".join(character for character in value.upper() if character.isalnum())
    if normalized in {"RED", "R"}:
        return "red"
    if normalized in {"GREEN", "G"}:
        return "green"
    if "REDEDGE" in normalized or normalized == "RE":
        return "rededge"
    if "NIR" in normalized or normalized == "N":
        return "nir"
    return None


def inspect_multispectral_orthophoto(
    path: str | Path,
    *,
    allow_m3m_fallback: bool = False,
) -> dict[str, Any]:
    """Resolve Red/Green/NIR/RedEdge bands in an ODM-style multiband raster."""

    source = Path(path)
    with rasterio.open(source) as dataset:
        descriptions = [
            description or f"Band {index}"
            for index, description in enumerate(dataset.descriptions, start=1)
        ]
        band_map: dict[str, int] = {}
        for index, description in enumerate(dataset.descriptions, start=1):
            normalized = _normalize_band_name(description)
            if normalized is not None and normalized not in band_map:
                band_map[normalized] = index

        warnings: list[dict[str, str]] = []
        required = {"red", "green", "nir", "rededge"}
        if not required.issubset(band_map):
            if allow_m3m_fallback and dataset.count == 4:
                band_map = {
                    "red": 1,
                    "green": 2,
                    "nir": 3,
                    "rededge": 4,
                }
                mapping_source = "odm_m3m_fallback_order"
                warnings.append(
                    {
                        "code": "M3M_BAND_DESCRIPTION_FALLBACK",
                        "severity": "warning",
                        "message": (
                            "Bandbeschreibungen fehlen oder sind unvollständig; "
                            "für ein explizit bestätigtes M3M-Vierband-Orthomosaik "
                            "wird Red, Green, NIR, Red Edge angenommen."
                        ),
                    }
                )
            else:
                missing = sorted(required.difference(band_map))
                raise ValueError(
                    "Multispektrale Bandzuordnung ist nicht eindeutig; "
                    f"fehlend: {', '.join(missing)}"
                )
        else:
            mapping_source = "raster_band_descriptions"

        return {
            "path": str(source),
            "width": int(dataset.width),
            "height": int(dataset.height),
            "band_count": int(dataset.count),
            "driver": dataset.driver,
            "crs": dataset.crs.to_string() if dataset.crs else None,
            "band_descriptions": descriptions,
            "band_map": band_map,
            "mapping_source": mapping_source,
            "warnings": warnings,
        }


def probe_cupy() -> dict[str, Any]:
    """Return optional CuPy/CUDA capability without making CUDA mandatory."""

    try:
        import cupy as cp
    except Exception:
        return {
            "available": False,
            "version": None,
            "device_count": 0,
            "device_name": None,
        }

    try:
        count = int(cp.cuda.runtime.getDeviceCount())
    except Exception:
        count = 0

    name = None
    if count > 0:
        try:
            properties = cp.cuda.runtime.getDeviceProperties(0)
            candidate = properties.get("name")
            if isinstance(candidate, bytes):
                candidate = candidate.decode("utf-8", errors="replace")
            if candidate:
                name = str(candidate)
        except Exception:
            pass

    return {
        "available": count > 0,
        "version": getattr(cp, "__version__", None),
        "device_count": count,
        "device_name": name,
    }


def _select_backend(
    requested: str,
    *,
    pixel_count: int,
    cuda_min_pixels: int,
) -> tuple[str, dict[str, Any]]:
    requested = requested.strip().lower()
    if requested not in {"auto", "cpu", "cuda"}:
        raise ValueError("backend must be one of: auto, cpu, cuda")

    cuda = probe_cupy()
    if requested == "cpu":
        return "cpu", cuda
    if requested == "cuda":
        if not cuda["available"]:
            raise RuntimeError(
                "CUDA backend requested, but CuPy reports no CUDA-enabled device"
            )
        return "cuda", cuda

    threshold = max(0, int(cuda_min_pixels))
    if cuda["available"] and int(pixel_count) >= threshold:
        return "cuda", cuda
    return "cpu", cuda


def _resolved_tile_size(value: int | str, width: int, height: int) -> int:
    if isinstance(value, str):
        if value.strip().lower() != "auto":
            try:
                value = int(value)
            except ValueError as exc:
                raise ValueError("tile_size must be 'auto' or an integer") from exc
        else:
            largest = max(width, height)
            if largest >= 12_000:
                value = 2048
            elif largest >= 4_000:
                value = 1024
            else:
                value = 512

    tile_size = int(value)
    if tile_size < 128 or tile_size > 4096:
        raise ValueError("tile_size must be between 128 and 4096 pixels")

    # GeoTIFF tile dimensions must be multiples of 16.
    return max(128, (tile_size // 16) * 16)


def _windows(width: int, height: int, tile_size: int):
    for row_off in range(0, height, tile_size):
        for col_off in range(0, width, tile_size):
            yield Window(
                col_off=col_off,
                row_off=row_off,
                width=min(tile_size, width - col_off),
                height=min(tile_size, height - row_off),
            )


def _tile_count(width: int, height: int, tile_size: int) -> int:
    columns = (int(width) + tile_size - 1) // tile_size
    rows = (int(height) + tile_size - 1) // tile_size
    return max(1, columns * rows)


def _check_cancel(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise RasterProcessingCancelled("raster processing cancelled")


def _index_cpu(
    positive: np.ndarray,
    comparison: np.ndarray,
    *,
    nodata: float,
) -> np.ndarray:
    denominator = positive + comparison
    valid = (
        np.isfinite(positive)
        & np.isfinite(comparison)
        & (np.abs(denominator) >= 1e-12)
    )
    output = np.full(positive.shape, nodata, dtype=np.float32)
    np.divide(
        positive - comparison,
        denominator,
        out=output,
        where=valid,
    )
    return output


def _index_cuda(
    positive: np.ndarray,
    comparison: np.ndarray,
    *,
    nodata: float,
) -> np.ndarray:
    import cupy as cp

    a = cp.asarray(positive, dtype=cp.float32)
    b = cp.asarray(comparison, dtype=cp.float32)
    denominator = a + b
    valid = cp.isfinite(a) & cp.isfinite(b) & (cp.abs(denominator) >= 1e-12)
    output = cp.where(valid, (a - b) / denominator, cp.float32(nodata))
    return cp.asnumpy(output).astype(np.float32, copy=False)


def _atomic_raster_target(output: Path) -> tuple[Path, str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp.tif",
        delete=False,
    )
    handle.close()
    return Path(handle.name), handle.name


def _raster_profile(
    source_profile: dict[str, Any],
    *,
    tile_size: int,
    dtype: str,
    nodata: float | int,
) -> dict[str, Any]:
    profile = dict(source_profile)
    profile.update(
        driver="GTiff",
        count=1,
        dtype=dtype,
        nodata=nodata,
        tiled=True,
        blockxsize=tile_size,
        blockysize=tile_size,
        compress="deflate",
        BIGTIFF="IF_SAFER",
    )
    profile.pop("photometric", None)
    profile.pop("interleave", None)
    return profile


def _stats_update(
    values: np.ndarray,
    *,
    nodata: float,
    state: dict[str, float | int],
) -> None:
    valid = np.isfinite(values) & (values != nodata)
    if not valid.any():
        return
    selected = values[valid]
    state["valid_pixels"] = int(state["valid_pixels"]) + int(selected.size)
    state["sum"] = float(state["sum"]) + float(selected.sum(dtype=np.float64))
    state["min"] = min(float(state["min"]), float(selected.min()))
    state["max"] = max(float(state["max"]), float(selected.max()))


def compute_vegetation_index(
    source_path: str | Path,
    output_path: str | Path,
    *,
    index_type: str,
    backend: str = "auto",
    tile_size: int | str = "auto",
    cuda_min_pixels: int = DEFAULT_CUDA_MIN_PIXELS,
    allow_m3m_fallback: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Create a georeferenced NDVI/NDRE/GNDVI GeoTIFF with CPU/CUDA fallback."""

    index_key = index_type.strip().lower()
    if index_key not in INDEX_BANDS:
        raise ValueError(f"unsupported vegetation index: {index_type}")

    source = Path(source_path)
    output = Path(output_path)
    info = inspect_multispectral_orthophoto(
        source,
        allow_m3m_fallback=allow_m3m_fallback,
    )
    positive_name, comparison_name = INDEX_BANDS[index_key]
    positive_band = int(info["band_map"][positive_name])
    comparison_band = int(info["band_map"][comparison_name])
    pixel_count = int(info["width"]) * int(info["height"])
    selected_backend, cuda = _select_backend(
        backend,
        pixel_count=pixel_count,
        cuda_min_pixels=cuda_min_pixels,
    )
    resolved_tile = _resolved_tile_size(tile_size, info["width"], info["height"])
    total_tiles = _tile_count(info["width"], info["height"], resolved_tile)

    temp_path, _ = _atomic_raster_target(output)
    stats: dict[str, float | int] = {
        "valid_pixels": 0,
        "sum": 0.0,
        "min": float("inf"),
        "max": float("-inf"),
    }

    try:
        with rasterio.open(source) as src:
            profile = _raster_profile(
                src.profile,
                tile_size=resolved_tile,
                dtype="float32",
                nodata=OUTPUT_NODATA,
            )
            with rasterio.open(temp_path, "w", **profile) as dst:
                dst.set_band_description(1, index_key.upper())
                for tile_index, window in enumerate(
                    _windows(src.width, src.height, resolved_tile),
                    start=1,
                ):
                    _check_cancel(cancel_check)
                    positive = src.read(
                        positive_band,
                        window=window,
                        masked=True,
                        out_dtype="float32",
                    ).filled(np.nan)
                    comparison = src.read(
                        comparison_band,
                        window=window,
                        masked=True,
                        out_dtype="float32",
                    ).filled(np.nan)

                    if selected_backend == "cuda":
                        values = _index_cuda(
                            positive,
                            comparison,
                            nodata=OUTPUT_NODATA,
                        )
                    else:
                        values = _index_cpu(
                            positive,
                            comparison,
                            nodata=OUTPUT_NODATA,
                        )

                    dst.write(values, 1, window=window)
                    _stats_update(values, nodata=OUTPUT_NODATA, state=stats)
                    if progress_callback is not None:
                        progress_callback(tile_index, total_tiles)

        _check_cancel(cancel_check)
        if int(stats["valid_pixels"]) == 0:
            raise ValueError("vegetation index contains no valid pixels")

        os.replace(temp_path, output)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    valid_pixels = int(stats["valid_pixels"])
    return {
        "schema": "geophoto.multispectral-index.v1",
        "source": str(source),
        "output": str(output),
        "index": index_key,
        "positive_band": positive_band,
        "comparison_band": comparison_band,
        "band_mapping_source": info["mapping_source"],
        "backend_requested": backend.strip().lower(),
        "backend_used": selected_backend,
        "cuda_min_pixels": max(0, int(cuda_min_pixels)),
        "cuda": cuda,
        "tile_size": resolved_tile,
        "width": int(info["width"]),
        "height": int(info["height"]),
        "valid_pixels": valid_pixels,
        "minimum": float(stats["min"]),
        "maximum": float(stats["max"]),
        "mean": float(stats["sum"]) / valid_pixels,
        "warnings": info["warnings"],
    }


def _validate_thresholds(thresholds: tuple[float, float, float, float]) -> None:
    if len(thresholds) != 4:
        raise ValueError("exactly four NDVI thresholds are required")
    if not all(isfinite(float(value)) and -1.0 <= float(value) <= 1.0 for value in thresholds):
        raise ValueError("NDVI thresholds must be finite values between -1 and 1")
    if not all(left < right for left, right in zip(thresholds, thresholds[1:])):
        raise ValueError("NDVI thresholds must be strictly increasing")


def classify_ndvi_zones(
    source_path: str | Path,
    output_path: str | Path,
    *,
    thresholds: tuple[float, float, float, float] = (0.20, 0.40, 0.60, 0.80),
    tile_size: int | str = "auto",
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Classify an NDVI raster into five scouting zones; class 0 is NoData."""

    _validate_thresholds(thresholds)
    source = Path(source_path)
    output = Path(output_path)

    with rasterio.open(source) as src:
        if src.count != 1:
            raise ValueError("NDVI scouting zones require a single-band raster")
        resolved_tile = _resolved_tile_size(tile_size, src.width, src.height)
        total_tiles = _tile_count(src.width, src.height, resolved_tile)
        temp_path, _ = _atomic_raster_target(output)
        counts = {str(index): 0 for index in range(6)}

        try:
            profile = _raster_profile(
                src.profile,
                tile_size=resolved_tile,
                dtype="uint8",
                nodata=0,
            )
            with rasterio.open(temp_path, "w", **profile) as dst:
                dst.set_band_description(1, "NDVI_SCOUTING_ZONE")
                for tile_index, window in enumerate(
                    _windows(src.width, src.height, resolved_tile),
                    start=1,
                ):
                    _check_cancel(cancel_check)
                    values = src.read(
                        1,
                        window=window,
                        masked=True,
                        out_dtype="float32",
                    )
                    raw = values.filled(np.nan)
                    valid = np.isfinite(raw)
                    zones = np.zeros(raw.shape, dtype=np.uint8)
                    zones[valid] = np.digitize(
                        raw[valid],
                        np.asarray(thresholds, dtype=np.float32),
                        right=False,
                    ).astype(np.uint8) + 1
                    dst.write(zones, 1, window=window)
                    unique, frequencies = np.unique(zones, return_counts=True)
                    for key, frequency in zip(unique, frequencies):
                        counts[str(int(key))] += int(frequency)
                    if progress_callback is not None:
                        progress_callback(tile_index, total_tiles)

            _check_cancel(cancel_check)
            os.replace(temp_path, output)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        return {
            "schema": "geophoto.ndvi-zones.v1",
            "source": str(source),
            "output": str(output),
            "thresholds": [float(value) for value in thresholds],
            "tile_size": resolved_tile,
            "width": int(src.width),
            "height": int(src.height),
            "class_counts": counts,
            "note": (
                "Scouting-Zonen basieren ausschließlich auf NDVI-Schwellen und "
                "sind keine Dünge- oder Pflanzenschutzempfehlung."
            ),
        }
