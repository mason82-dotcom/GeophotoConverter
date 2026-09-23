from __future__ import annotations

from math import isfinite
from pathlib import PurePosixPath
from string import hexdigits
from typing import Any, Mapping

from pyproj import CRS
from pyproj.exceptions import CRSError


SCHEMA_VERSION = 1
PROVENANCE_SCHEMA_VERSION = 1
PDAL_VERSION_CONTRACT = "2.10.2"
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
        raise ValueError("Reprojection input must be LAS, LAZ, or COPC-LAZ.")

    return path


def _reader_type(path: PurePosixPath) -> str:
    if path.name.lower().endswith(".copc.laz"):
        return "readers.copc"
    return "readers.las"


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

    if crs.is_compound or crs.is_vertical or len(crs.axis_info) != 2:
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
            if str(axis.unit_name or "").strip().lower() not in {"metre", "meter"}:
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
    reader = _reader_type(source_path)

    pipeline = {
        "pipeline": [
            {
                "type": reader,
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
                # PDAL's special "header" value excludes source scale/offset.
                # VLR forwarding is explicit; projection/format VLRs are rebuilt.
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
        "pdal_version_contract": PDAL_VERSION_CONTRACT,
        "source": {
            "relative_path": source_path.as_posix(),
            "reader": reader,
            "crs": source_identifier,
        },
        "output": {
            "relative_path": output_path.as_posix(),
            "writer": "writers.las",
            "crs": target_identifier,
            "format": "laz",
        },
        "coordinate_scale_m": scale,
        "vertical_transform": False,
        "vertical_reference": {
            "status": "unchanged_unspecified",
            "note": (
                "Contract v1 performs horizontal reprojection only and does "
                "not assert or transform a vertical datum."
            ),
        },
        "pipeline": pipeline,
    }


def _sha256(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("source_sha256 must be a hexadecimal SHA-256 string.")
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in hexdigits for char in normalized):
        raise ValueError("source_sha256 must be a hexadecimal SHA-256 string.")
    return normalized


def reprojection_provenance(
    contract: Mapping[str, Any],
    *,
    source_job_id: str,
    source_artifact_index: int,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """Attach source identity and software provenance to a ready contract."""

    if contract.get("operation") != "horizontal_reprojection":
        raise ValueError("Unsupported point-cloud processing contract.")
    if not isinstance(source_job_id, str) or not source_job_id.strip():
        raise ValueError("source_job_id must be a non-empty string.")
    if (
        isinstance(source_artifact_index, bool)
        or not isinstance(source_artifact_index, int)
        or source_artifact_index < 0
    ):
        raise ValueError("source_artifact_index must be a non-negative integer.")

    source = contract.get("source")
    output = contract.get("output")
    pipeline = contract.get("pipeline")
    vertical_reference = contract.get("vertical_reference")
    if not all(isinstance(value, Mapping) for value in (
        source,
        output,
        pipeline,
        vertical_reference,
    )):
        raise ValueError("Reprojection contract is incomplete.")

    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "operation": "horizontal_reprojection",
        "source_job_id": source_job_id.strip(),
        "source_artifact_index": source_artifact_index,
        "source_sha256": _sha256(source_sha256),
        "source_relative_path": source["relative_path"],
        "output_relative_path": output["relative_path"],
        "source_crs": source["crs"],
        "target_crs": output["crs"],
        "coordinate_scale_m": contract.get("coordinate_scale_m"),
        "vertical_reference": dict(vertical_reference),
        "pipeline": dict(pipeline),
        "software": {
            "engine": "pdal",
            "version_contract": PDAL_VERSION_CONTRACT,
        },
    }
