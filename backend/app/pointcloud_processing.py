from __future__ import annotations

from pathlib import Path
from typing import Any

from pyproj import CRS
from pyproj.exceptions import CRSError


PDAL_REPROJECTION_CONTRACT_VERSION = "1"
_SUPPORTED_INPUT_SUFFIXES = {".las", ".laz"}
_SUPPORTED_OUTPUT_SUFFIXES = {".laz"}
_METRE_UNITS = {"metre", "meter"}


def _parse_crs(value: Any, *, role: str) -> CRS:
    if value in (None, ""):
        raise ValueError(f"{role}_crs is required.")
    try:
        crs = CRS.from_user_input(value)
    except (CRSError, ValueError, TypeError) as exc:
        raise ValueError(f"{role}_crs is invalid.") from exc

    if crs.is_compound or crs.is_vertical or len(crs.axis_info) != 2:
        raise ValueError(
            f"{role}_crs must be a horizontal 2D CRS in reprojection contract v1."
        )
    if not (crs.is_geographic or crs.is_projected):
        raise ValueError(
            f"{role}_crs must be geographic or projected in contract v1."
        )
    return crs


def _crs_identifier(crs: CRS) -> str:
    authority = crs.to_authority()
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.to_wkt()


def _metric_projected_target(crs: CRS) -> bool:
    if not crs.is_projected or len(crs.axis_info) < 2:
        return False
    return all(
        str(axis.unit_name or "").strip().lower() in _METRE_UNITS
        for axis in crs.axis_info[:2]
    )


def _reader_for(path: Path) -> str:
    lower_name = path.name.lower()
    if lower_name.endswith(".copc.laz"):
        return "readers.copc"
    if path.suffix.lower() in _SUPPORTED_INPUT_SUFFIXES:
        return "readers.las"
    raise ValueError("source point cloud must be LAS, LAZ, or COPC-LAZ.")


def _validate_output(path: Path) -> None:
    if path.suffix.lower() not in _SUPPORTED_OUTPUT_SUFFIXES:
        raise ValueError("reprojection output must use .laz in contract v1.")


def build_reprojection_pipeline(
    source_path: str | Path,
    output_path: str | Path,
    *,
    source_crs: Any,
    target_crs: Any,
) -> dict[str, Any]:
    """Build the canonical PDAL horizontal reprojection pipeline.

    Contract v1 intentionally excludes vertical datum transformations.
    Z values are carried through without assigning them a new vertical
    reference. The target must be a projected CRS using metre axes.
    """

    source = Path(source_path)
    output = Path(output_path)

    reader_type = _reader_for(source)
    _validate_output(output)
    if source.resolve(strict=False) == output.resolve(strict=False):
        raise ValueError("source and output paths must differ.")

    source_ref = _parse_crs(source_crs, role="source")
    target_ref = _parse_crs(target_crs, role="target")

    if not _metric_projected_target(target_ref):
        raise ValueError("target_crs must be projected with metre axes.")
    if source_ref.equals(target_ref):
        raise ValueError("source_crs and target_crs are identical.")

    source_id = _crs_identifier(source_ref)
    target_id = _crs_identifier(target_ref)

    pipeline = {
        "pipeline": [
            {
                "type": reader_type,
                "filename": str(source),
            },
            {
                "type": "filters.reprojection",
                "in_srs": source_id,
                "out_srs": target_id,
            },
            {
                "type": "writers.las",
                "filename": str(output),
                "compression": True,
                "a_srs": target_id,
                # Preserve non-coordinate LAS header metadata only. Scale and
                # offset from the source CRS must not leak into reprojected data.
                "forward": "header",
                "scale_x": "auto",
                "scale_y": "auto",
                "scale_z": "auto",
                "offset_x": "auto",
                "offset_y": "auto",
                "offset_z": "auto",
            },
        ]
    }

    return {
        "schema_version": PDAL_REPROJECTION_CONTRACT_VERSION,
        "operation": "reproject",
        "source": {
            "path": str(source),
            "reader": reader_type,
            "crs": source_id,
        },
        "target": {
            "path": str(output),
            "writer": "writers.las",
            "crs": target_id,
            "format": "laz",
        },
        "vertical_reference": {
            "status": "unchanged_unspecified",
            "note": (
                "Contract v1 performs horizontal reprojection only and does "
                "not assert or transform a vertical datum."
            ),
        },
        "pipeline": pipeline,
    }


def reprojection_provenance(
    contract: dict[str, Any],
    *,
    source_job_id: str,
    source_artifact_index: int,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    if contract.get("operation") != "reproject":
        raise ValueError("unsupported pointcloud processing contract.")

    return {
        "schema_version": "1",
        "operation": "reproject",
        "source_job_id": source_job_id,
        "source_artifact_index": int(source_artifact_index),
        "source_sha256": source_sha256,
        "source_crs": contract["source"]["crs"],
        "target_crs": contract["target"]["crs"],
        "pipeline": contract["pipeline"],
        "vertical_reference": contract["vertical_reference"],
        "software": {
            "engine": "pdal",
            "version_contract": "2.10.2",
        },
    }
