from __future__ import annotations

from math import isfinite
from pathlib import PurePosixPath
from typing import Any

from pyproj import CRS
from pyproj.exceptions import CRSError


SCHEMA_VERSION = 1
DEFAULT_DATA_ROOT = "/data"
DEFAULT_SCALE_M = 0.001
INPUT_SUFFIXES = {".las", ".laz"}


def _relative_path(value: Any, *, output: bool = False) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Point-cloud path must be a non-empty relative path.")

    raw = value.replace("\\", "/").strip()
    if raw.startswith("/"):
        raise ValueError("Point-cloud path must be relative.")

    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Point-cloud path contains unsafe path components.")

    suffix = path.suffix.lower()
    if output:
        if suffix != ".laz":
            raise ValueError("Reprojection output must use the .laz suffix.")
    elif suffix not in INPUT_SUFFIXES:
        raise ValueError("Reprojection input must be LAS or LAZ.")

    return path


def _crs_identifier(crs: CRS) -> str:
    authority = crs.to_authority()
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.to_wkt()


def _horizontal_2d_crs(
    value: Any,
    *,
    role: str,
    require_metric_projected: bool,
) -> CRS:
    try:
        crs = CRS.from_user_input(value)
    except (CRSError, ValueError, TypeError) as exc:
        raise ValueError(f"{role} CRS is invalid.") from exc

    if crs.is_compound or len(crs.axis_info) != 2:
        raise ValueError(
            f"{role} CRS must be a horizontal 2D CRS; vertical/3D CRS are not "
            "accepted by the reprojection contract."
        )
    if not (crs.is_projected or crs.is_geographic):
        raise ValueError(f"{role} CRS must be geographic or projected.")

    if require_metric_projected:
        if not crs.is_projected:
            raise ValueError("Target CRS must be projected.")
        for axis in crs.axis_info[:2]:
            if axis.unit_name not in {"metre", "meter"}:
                raise ValueError("Target CRS must use metre axes.")

    return crs


def _coordinate_scale(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Coordinate scale must be numeric.")
    try:
        scale = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Coordinate scale must be numeric.") from exc
    if not isfinite(scale) or not 1e-6 <= scale <= 0.1:
        raise ValueError(
            "Coordinate scale must be finite and between 1e-6 m and 0.1 m."
        )
    return scale


def build_reprojection_contract(
    *,
    source_relative_path: str,
    output_relative_path: str,
    source_crs: Any,
    target_crs: Any,
    data_root: str = DEFAULT_DATA_ROOT,
    coordinate_scale_m: float = DEFAULT_SCALE_M,
) -> dict[str, Any]:
    """Build a deterministic horizontal-only PDAL reprojection pipeline.

    The contract deliberately refuses vertical/3D CRS definitions. Z values
    therefore remain outside an implicit vertical datum transformation until
    GeoPhotoConverter has an explicit vertical CRS/grid policy.
    """

    source_path = _relative_path(source_relative_path)
    output_path = _relative_path(output_relative_path, output=True)
    if source_path == output_path:
        raise ValueError("Reprojection must create a new artifact.")

    source = _horizontal_2d_crs(
        source_crs,
        role="Source",
        require_metric_projected=False,
    )
    target = _horizontal_2d_crs(
        target_crs,
        role="Target",
        require_metric_projected=True,
    )
    if source.equals(target):
        raise ValueError("Source and target CRS must differ.")

    scale = _coordinate_scale(coordinate_scale_m)
    root = str(PurePosixPath(data_root))
    source_filename = str(PurePosixPath(root) / source_path)
    output_filename = str(PurePosixPath(root) / output_path)
    source_identifier = _crs_identifier(source)
    target_identifier = _crs_identifier(target)

    pipeline = {
        "pipeline": [
            {
                "type": "readers.las",
                "filename": source_filename,
            },
            {
                "type": "filters.reprojection",
                "in_srs": source_identifier,
                "out_srs": target_identifier,
            },
            {
                "type": "writers.las",
                "filename": output_filename,
                "a_srs": target_identifier,
                "compression": True,
                "forward": "header,vlr",
                "extra_dims": "all",
                "scale_x": scale,
                "scale_y": scale,
                "scale_z": scale,
                "offset_x": "auto",
                "offset_y": "auto",
                "offset_z": "auto",
            },
        ]
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "horizontal_reprojection",
        "pdal_version_contract": "2.10.2",
        "source": {
            "relative_path": source_path.as_posix(),
            "crs": source_identifier,
        },
        "output": {
            "relative_path": output_path.as_posix(),
            "crs": target_identifier,
            "format": "laz",
        },
        "coordinate_scale_m": scale,
        "vertical_transform": False,
        "pipeline": pipeline,
    }
