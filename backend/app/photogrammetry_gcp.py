from __future__ import annotations

from collections import defaultdict
from math import hypot, isfinite, sqrt
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree as ET

from pyproj import CRS


_ALLOWED_ROLES = {"control", "checkpoint"}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _metric_projected_crs(value: Any) -> CRS:
    crs = CRS.from_user_input(value)
    if not crs.is_projected:
        raise ValueError("GCP project CRS must be projected.")
    if not crs.axis_info:
        raise ValueError("GCP project CRS has no axis information.")
    for axis in crs.axis_info[:2]:
        if axis.unit_name not in {"metre", "meter"}:
            raise ValueError("GCP project CRS must use metre axes.")
    return crs


def _crs_descriptor(crs: CRS) -> dict[str, Any]:
    authority = crs.to_authority()
    identifier = f"{authority[0]}:{authority[1]}" if authority else None
    return {
        "identifier": identifier,
        "name": crs.name,
        "is_projected": crs.is_projected,
        "axis_units": [axis.unit_name for axis in crs.axis_info],
        "wkt": crs.to_wkt(),
    }


def _issue(
    code: str,
    severity: str,
    *,
    point_id: str | None = None,
    observation_index: int | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "severity": severity,
    }
    if point_id is not None:
        result["point_id"] = point_id
    if observation_index is not None:
        result["observation_index"] = observation_index
    if detail is not None:
        result["detail"] = detail
    return result


def normalize_gcp_project(
    points: Iterable[Mapping[str, Any]],
    project_crs: Any,
) -> dict[str, Any]:
    """Normalize and validate an engine-neutral GCP/checkpoint project.

    Input point contract:
      {
        "id": "GCP-01",
        "role": "control" | "checkpoint",
        "x_m": 123.4,
        "y_m": 456.7,
        "z_m": 89.0,
        "sigma_x_m": 0.02,   # optional
        "sigma_y_m": 0.02,   # optional
        "sigma_z_m": 0.03,   # optional
        "observations": [
          {"image_name": "IMG_0001.JPG", "pixel_x": 1234.5, "pixel_y": 678.9}
        ]
      }

    The function does not transform coordinates. CRS conversion must be explicit
    and performed before calling this contract.
    """

    issues: list[dict[str, Any]] = []
    try:
        crs = _metric_projected_crs(project_crs)
        crs_info = _crs_descriptor(crs)
    except Exception as exc:
        return {
            "status": "blocked",
            "crs": None,
            "summary": {
                "point_count": 0,
                "control_points": 0,
                "checkpoints": 0,
                "observation_count": 0,
            },
            "points": [],
            "issues": [
                _issue(
                    "invalid_project_crs",
                    "blocked",
                    detail=str(exc),
                )
            ],
        }

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for raw in points:
        point_id = _text(raw.get("id"))
        if point_id is None:
            issues.append(_issue("missing_point_id", "blocked"))
            continue
        if point_id in seen_ids:
            issues.append(
                _issue(
                    "duplicate_point_id",
                    "blocked",
                    point_id=point_id,
                )
            )
            continue
        seen_ids.add(point_id)

        role = _text(raw.get("role"))
        if role not in _ALLOWED_ROLES:
            issues.append(
                _issue(
                    "invalid_point_role",
                    "blocked",
                    point_id=point_id,
                    detail=f"Expected one of {sorted(_ALLOWED_ROLES)}.",
                )
            )
            continue

        x_m = _finite(raw.get("x_m"))
        y_m = _finite(raw.get("y_m"))
        z_m = _finite(raw.get("z_m"))
        if None in {x_m, y_m, z_m}:
            issues.append(
                _issue(
                    "invalid_ground_coordinate",
                    "blocked",
                    point_id=point_id,
                )
            )
            continue

        sigmas: dict[str, float | None] = {}
        for field in ("sigma_x_m", "sigma_y_m", "sigma_z_m"):
            value = _finite(raw.get(field))
            if value is not None and value <= 0.0:
                issues.append(
                    _issue(
                        "invalid_point_uncertainty",
                        "blocked",
                        point_id=point_id,
                        detail=f"{field} must be positive when provided.",
                    )
                )
                value = None
            sigmas[field] = value

        observations: list[dict[str, Any]] = []
        seen_images: set[str] = set()
        raw_observations = raw.get("observations")
        if not isinstance(raw_observations, list):
            raw_observations = []

        for index, observation in enumerate(raw_observations):
            if not isinstance(observation, Mapping):
                issues.append(
                    _issue(
                        "invalid_observation",
                        "blocked",
                        point_id=point_id,
                        observation_index=index,
                    )
                )
                continue
            image_name = _text(observation.get("image_name"))
            pixel_x = _finite(observation.get("pixel_x"))
            pixel_y = _finite(observation.get("pixel_y"))
            if image_name is None or pixel_x is None or pixel_y is None:
                issues.append(
                    _issue(
                        "invalid_observation",
                        "blocked",
                        point_id=point_id,
                        observation_index=index,
                    )
                )
                continue
            if pixel_x < 0.0 or pixel_y < 0.0:
                issues.append(
                    _issue(
                        "negative_image_coordinate",
                        "blocked",
                        point_id=point_id,
                        observation_index=index,
                    )
                )
                continue
            if image_name in seen_images:
                issues.append(
                    _issue(
                        "duplicate_image_observation",
                        "blocked",
                        point_id=point_id,
                        observation_index=index,
                        detail=image_name,
                    )
                )
                continue
            seen_images.add(image_name)
            observations.append(
                {
                    "image_name": image_name,
                    "pixel_x": pixel_x,
                    "pixel_y": pixel_y,
                }
            )

        if len(observations) < 2:
            issues.append(
                _issue(
                    "insufficient_point_observations",
                    "blocked",
                    point_id=point_id,
                    detail="At least two image observations are required.",
                )
            )
        elif len(observations) < 3:
            issues.append(
                _issue(
                    "low_point_observation_count",
                    "warning",
                    point_id=point_id,
                    detail="Three or more image observations are recommended.",
                )
            )

        normalized.append(
            {
                "id": point_id,
                "role": role,
                "x_m": x_m,
                "y_m": y_m,
                "z_m": z_m,
                **sigmas,
                "observations": observations,
            }
        )

    controls = [point for point in normalized if point["role"] == "control"]
    checkpoints = [point for point in normalized if point["role"] == "checkpoint"]
    observation_count = sum(len(point["observations"]) for point in normalized)

    if len(controls) < 3:
        issues.append(
            _issue(
                "insufficient_control_points",
                "blocked",
                detail="At least three control points are required.",
            )
        )
    elif len(controls) < 5:
        issues.append(
            _issue(
                "low_control_point_count",
                "warning",
                detail=(
                    "At least five well-distributed control points are recommended "
                    "for robust mapping."
                ),
            )
        )

    status = (
        "blocked"
        if any(item["severity"] == "blocked" for item in issues)
        else "warning"
        if any(item["severity"] == "warning" for item in issues)
        else "ready"
    )
    return {
        "status": status,
        "crs": crs_info,
        "summary": {
            "point_count": len(normalized),
            "control_points": len(controls),
            "checkpoints": len(checkpoints),
            "observation_count": observation_count,
        },
        "points": normalized,
        "issues": issues,
    }


def _require_ready(project: Mapping[str, Any]) -> None:
    if project.get("status") not in {"ready", "warning"}:
        raise ValueError("Blocked GCP project cannot be exported.")
    if not isinstance(project.get("points"), list):
        raise ValueError("GCP project has no normalized points.")
    if not isinstance(project.get("crs"), Mapping):
        raise ValueError("GCP project has no valid CRS.")


def _selected_points(
    project: Mapping[str, Any],
    roles: set[str],
) -> list[Mapping[str, Any]]:
    _require_ready(project)
    return [
        point
        for point in project["points"]
        if isinstance(point, Mapping) and point.get("role") in roles
    ]


def build_odm_gcp_list(
    project: Mapping[str, Any],
    *,
    roles: set[str] | None = None,
) -> str:
    """Build ODM gcp_list.txt content.

    By default only control points are exported. Checkpoints must never be fed
    into the adjustment silently.
    """

    selected_roles = roles or {"control"}
    points = _selected_points(project, selected_roles)
    crs = project["crs"]
    identifier = crs.get("identifier")
    if not identifier:
        raise ValueError("ODM export requires an authority-backed CRS identifier.")

    lines = [str(identifier)]
    for point in points:
        for observation in point["observations"]:
            lines.append(
                " ".join(
                    [
                        f"{point['x_m']:.6f}",
                        f"{point['y_m']:.6f}",
                        f"{point['z_m']:.6f}",
                        f"{observation['pixel_x']:.6f}",
                        f"{observation['pixel_y']:.6f}",
                        observation["image_name"],
                        point["id"],
                    ]
                )
            )
    return "\n".join(lines) + "\n"


def build_micmac_gcp_bundle(
    project: Mapping[str, Any],
    *,
    roles: set[str] | None = None,
) -> dict[str, Any]:
    """Build MicMac control-point text and image measurement XML.

    The 3D text is compatible with:
      mm3d GCPConvert "#F=N_X_Y_Z" ground_points.txt Out=ground_points.xml

    Image measurements use SetOfMesureAppuisFlottants XML.
    """

    selected_roles = roles or {"control"}
    points = _selected_points(project, selected_roles)

    ground_lines = [
        f"{point['id']} {point['x_m']:.6f} {point['y_m']:.6f} {point['z_m']:.6f}"
        for point in points
    ]

    by_image: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    for point in points:
        for observation in point["observations"]:
            by_image[observation["image_name"]].append(
                (
                    point["id"],
                    observation["pixel_x"],
                    observation["pixel_y"],
                )
            )

    root = ET.Element("SetOfMesureAppuisFlottants")
    for image_name in sorted(by_image):
        image_node = ET.SubElement(root, "MesureAppuiFlottant1Im")
        ET.SubElement(image_node, "NameIm").text = image_name
        for point_id, pixel_x, pixel_y in sorted(by_image[image_name]):
            measurement = ET.SubElement(image_node, "OneMesureAF1I")
            ET.SubElement(measurement, "NamePt").text = point_id
            ET.SubElement(measurement, "PtIm").text = f"{pixel_x:.6f} {pixel_y:.6f}"

    xml_text = ET.tostring(root, encoding="unicode")
    return {
        "ground_points_text": "\n".join(ground_lines) + ("\n" if ground_lines else ""),
        "measurements_xml": xml_text + "\n",
        "gcpconvert_command": [
            "mm3d",
            "GCPConvert",
            "#F=N_X_Y_Z",
            "ground_points.txt",
            "Out=ground_points.xml",
        ],
        "roles": sorted(selected_roles),
    }


def colmap_direct_gcp_capability() -> dict[str, Any]:
    """Describe the intentional COLMAP limitation for arbitrary GCPs."""

    return {
        "status": "unsupported",
        "reason": "no_direct_ground_point_constraint_adapter",
        "note": (
            "COLMAP model_aligner accepts camera-center reference positions. "
            "It is not treated as a direct arbitrary ground-control-point adapter."
        ),
    }


def residual_report(
    project: Mapping[str, Any],
    estimates: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Calculate independent 3D residual/RMSE statistics.

    Estimates are reconstructed/adjusted ground coordinates keyed by point ID.
    Control and checkpoint statistics are always reported separately.
    """

    _require_ready(project)
    residuals: list[dict[str, Any]] = []

    for point in project["points"]:
        estimate = estimates.get(point["id"])
        if not isinstance(estimate, Mapping):
            continue
        x = _finite(estimate.get("x_m"))
        y = _finite(estimate.get("y_m"))
        z = _finite(estimate.get("z_m"))
        if None in {x, y, z}:
            continue

        dx = x - point["x_m"]
        dy = y - point["y_m"]
        dz = z - point["z_m"]
        residuals.append(
            {
                "point_id": point["id"],
                "role": point["role"],
                "dx_m": dx,
                "dy_m": dy,
                "dz_m": dz,
                "horizontal_m": hypot(dx, dy),
                "distance_3d_m": sqrt(dx * dx + dy * dy + dz * dz),
            }
        )

    def stats(role: str) -> dict[str, Any]:
        values = [item for item in residuals if item["role"] == role]
        count = len(values)
        if count == 0:
            return {
                "count": 0,
                "rmse_x_m": None,
                "rmse_y_m": None,
                "rmse_z_m": None,
                "rmse_horizontal_m": None,
                "rmse_3d_m": None,
            }

        def rmse(field: str) -> float:
            return sqrt(sum(item[field] ** 2 for item in values) / count)

        return {
            "count": count,
            "rmse_x_m": rmse("dx_m"),
            "rmse_y_m": rmse("dy_m"),
            "rmse_z_m": rmse("dz_m"),
            "rmse_horizontal_m": rmse("horizontal_m"),
            "rmse_3d_m": rmse("distance_3d_m"),
        }

    return {
        "control": stats("control"),
        "checkpoint": stats("checkpoint"),
        "residuals": residuals,
        "missing_estimates": sorted(
            point["id"]
            for point in project["points"]
            if point["id"] not in estimates
        ),
    }
