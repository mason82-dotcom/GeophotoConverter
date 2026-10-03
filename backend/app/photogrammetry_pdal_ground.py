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

DEFAULT_SMRF = {
    "cell": 1.0,
    "cut": 0.0,
    "returns": "last,only",
    "scalar": 1.25,
    "slope": 0.15,
    "threshold": 0.5,
    "window": 18.0,
    "ground_class": 2,
    "other_class": 1,
    "only_ground": False,
}
DEFAULT_HAG = {
    "count": 1,
    "allow_extrapolation": False,
    "class": 2,
}
_ALLOWED_RETURNS = {"first", "last", "intermediate", "only"}


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

    if output:
        if path.suffix.lower() != ".laz":
            raise ValueError("Ground/HAG output must use the .laz suffix.")
    elif path.suffix.lower() not in {".las", ".laz"}:
        raise ValueError("Ground/HAG input must be LAS, LAZ, or COPC-LAZ.")
    return path


def _reader_type(path: PurePosixPath) -> str:
    return "readers.copc" if path.name.lower().endswith(".copc.laz") else "readers.las"


def _crs_identifier(crs: CRS) -> str:
    authority = crs.to_authority()
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.to_wkt()


def _metric_projected_2d_crs(value: Any) -> CRS:
    try:
        crs = CRS.from_user_input(value)
    except (CRSError, ValueError, TypeError) as exc:
        raise ValueError("Source CRS is invalid.") from exc

    if crs.is_compound or crs.is_vertical or len(crs.axis_info) != 2:
        raise ValueError(
            "Source CRS must be horizontal 2D; vertical/3D/compound CRS are "
            "not accepted by the Ground/HAG contract."
        )
    if not crs.is_projected:
        raise ValueError(
            "Source CRS must be projected before metric SMRF/HAG processing."
        )
    for axis in crs.axis_info[:2]:
        if str(axis.unit_name or "").strip().lower() not in {"metre", "meter"}:
            raise ValueError("Source CRS must use metre axes for SMRF/HAG.")
    return crs


def _finite_float(
    value: Any,
    *,
    name: str,
    minimum: float,
    maximum: float,
    allow_zero: bool = True,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric.")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric.") from exc
    if not isfinite(parsed):
        raise ValueError(f"{name} must be finite.")
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} is outside the supported range.")
    if not allow_zero and parsed == 0.0:
        raise ValueError(f"{name} must be greater than zero.")
    return parsed


def _class_value(value: Any, *, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer classification value.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer classification value.") from exc
    if parsed != value or not 0 <= parsed <= 255:
        raise ValueError(f"{name} must be an integer from 0 through 255.")
    return parsed


def _return_selection(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("smrf_returns must be a comma-separated string.")
    values = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not values or len(values) != len(set(values)):
        raise ValueError("smrf_returns must contain unique return groups.")
    if any(item not in _ALLOWED_RETURNS for item in values):
        raise ValueError("smrf_returns contains an unsupported return group.")
    return ",".join(values)


def _coordinate_scale(value: Any) -> float:
    return _finite_float(
        value,
        name="coordinate_scale_m",
        minimum=1e-6,
        maximum=0.1,
        allow_zero=False,
    )


def build_ground_hag_contract(
    *,
    source_relative_path: str,
    output_relative_path: str,
    source_crs: Any,
    data_root: str = DEFAULT_DATA_ROOT,
    coordinate_scale_m: float = DEFAULT_SCALE_M,
    smrf_cell_m: float = 1.0,
    smrf_cut_m: float = 0.0,
    smrf_returns: str = "last,only",
    smrf_scalar: float = 1.25,
    smrf_slope: float = 0.15,
    smrf_threshold_m: float = 0.5,
    smrf_window_m: float = 18.0,
    ground_class: int = 2,
    other_class: int = 1,
    hag_count: int = 1,
    hag_max_distance_m: float | None = None,
    hag_allow_extrapolation: bool = False,
) -> dict[str, Any]:
    """Build a deterministic SMRF + nearest-neighbor HAG PDAL pipeline.

    Ground/HAG is metric geometry. Geographic degree coordinates are therefore
    rejected and must be reprojected first. Raw Z is preserved; HAG is emitted
    as the additional HeightAboveGround dimension.
    """

    source_path = _relative_path(source_relative_path)
    output_path = _relative_path(output_relative_path, output=True)
    if source_path == output_path:
        raise ValueError("Ground/HAG must create a new artifact.")

    source_ref = _metric_projected_2d_crs(source_crs)
    source_identifier = _crs_identifier(source_ref)
    scale = _coordinate_scale(coordinate_scale_m)

    cell = _finite_float(
        smrf_cell_m,
        name="smrf_cell_m",
        minimum=0.01,
        maximum=100.0,
        allow_zero=False,
    )
    cut = _finite_float(
        smrf_cut_m,
        name="smrf_cut_m",
        minimum=0.0,
        maximum=10000.0,
    )
    scalar = _finite_float(
        smrf_scalar,
        name="smrf_scalar",
        minimum=0.01,
        maximum=20.0,
        allow_zero=False,
    )
    slope = _finite_float(
        smrf_slope,
        name="smrf_slope",
        minimum=0.0,
        maximum=10.0,
    )
    threshold = _finite_float(
        smrf_threshold_m,
        name="smrf_threshold_m",
        minimum=0.0,
        maximum=1000.0,
    )
    window = _finite_float(
        smrf_window_m,
        name="smrf_window_m",
        minimum=0.01,
        maximum=10000.0,
        allow_zero=False,
    )
    if window < cell:
        raise ValueError("smrf_window_m must be greater than or equal to smrf_cell_m.")

    ground = _class_value(ground_class, name="ground_class")
    other = _class_value(other_class, name="other_class")
    if ground == other:
        raise ValueError("ground_class and other_class must differ.")

    if (
        isinstance(hag_count, bool)
        or not isinstance(hag_count, int)
        or not 1 <= hag_count <= 64
    ):
        raise ValueError("hag_count must be an integer from 1 through 64.")
    if not isinstance(hag_allow_extrapolation, bool):
        raise ValueError("hag_allow_extrapolation must be boolean.")

    max_distance: float | None = None
    if hag_max_distance_m is not None:
        max_distance = _finite_float(
            hag_max_distance_m,
            name="hag_max_distance_m",
            minimum=0.01,
            maximum=100000.0,
            allow_zero=False,
        )

    returns = _return_selection(smrf_returns)
    root = str(PurePosixPath(data_root))
    source_filename = str(PurePosixPath(root) / source_path)
    output_filename = str(PurePosixPath(root) / output_path)
    reader = _reader_type(source_path)

    smrf_stage = {
        "type": "filters.smrf",
        "cell": cell,
        "cut": cut,
        "returns": returns,
        "scalar": scalar,
        "slope": slope,
        "threshold": threshold,
        "window": window,
        "ground_class": ground,
        "other_class": other,
        "only_ground": False,
    }
    hag_stage: dict[str, Any] = {
        "type": "filters.hag_nn",
        "count": hag_count,
        "allow_extrapolation": hag_allow_extrapolation,
        "class": ground,
    }
    if max_distance is not None:
        hag_stage["max_distance"] = max_distance

    pipeline = {
        "pipeline": [
            {
                "type": reader,
                "filename": source_filename,
            },
            {
                "type": "filters.assign",
                "value": "Classification=0",
            },
            smrf_stage,
            hag_stage,
            {
                "type": "writers.las",
                "filename": output_filename,
                "a_srs": source_identifier,
                "compression": True,
                "minor_version": 4,
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
        "operation": "ground_hag",
        "pdal_version_contract": PDAL_VERSION_CONTRACT,
        "source": {
            "relative_path": source_path.as_posix(),
            "reader": reader,
            "crs": source_identifier,
        },
        "output": {
            "relative_path": output_path.as_posix(),
            "writer": "writers.las",
            "crs": source_identifier,
            "format": "laz",
            "las_minor_version": 4,
        },
        "coordinate_scale_m": scale,
        "classification_reset": 0,
        "smrf": {
            "cell_m": cell,
            "cut_m": cut,
            "returns": returns,
            "scalar": scalar,
            "slope": slope,
            "threshold_m": threshold,
            "window_m": window,
            "ground_class": ground,
            "other_class": other,
            "only_ground": False,
        },
        "hag": {
            "method": "nearest_neighbor",
            "count": hag_count,
            "max_distance_m": max_distance,
            "allow_extrapolation": hag_allow_extrapolation,
            "ground_class": ground,
            "dimension": "HeightAboveGround",
        },
        "vertical_reference": {
            "status": "source_z_unchanged",
            "hag_reference": "smrf_derived_ground_surface",
            "note": (
                "Raw Z is preserved. HeightAboveGround is a relative dimension "
                "derived from SMRF-classified ground and does not establish a "
                "new vertical datum."
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


def ground_hag_provenance(
    contract: Mapping[str, Any],
    *,
    source_job_id: str,
    source_artifact_index: int,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    if contract.get("operation") != "ground_hag":
        raise ValueError("Unsupported point-cloud processing contract.")
    if not isinstance(source_job_id, str) or not source_job_id.strip():
        raise ValueError("source_job_id must be a non-empty string.")
    if (
        isinstance(source_artifact_index, bool)
        or not isinstance(source_artifact_index, int)
        or source_artifact_index < 0
    ):
        raise ValueError("source_artifact_index must be a non-negative integer.")

    required = ("source", "output", "smrf", "hag", "vertical_reference", "pipeline")
    if any(not isinstance(contract.get(key), Mapping) for key in required):
        raise ValueError("Ground/HAG contract is incomplete.")

    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "operation": "ground_hag",
        "source_job_id": source_job_id.strip(),
        "source_artifact_index": source_artifact_index,
        "source_sha256": _sha256(source_sha256),
        "source_relative_path": contract["source"]["relative_path"],
        "output_relative_path": contract["output"]["relative_path"],
        "crs": contract["source"]["crs"],
        "coordinate_scale_m": contract.get("coordinate_scale_m"),
        "classification_reset": contract.get("classification_reset"),
        "smrf": dict(contract["smrf"]),
        "hag": dict(contract["hag"]),
        "vertical_reference": dict(contract["vertical_reference"]),
        "pipeline": dict(contract["pipeline"]),
        "software": {
            "engine": "pdal",
            "version_contract": PDAL_VERSION_CONTRACT,
        },
    }
