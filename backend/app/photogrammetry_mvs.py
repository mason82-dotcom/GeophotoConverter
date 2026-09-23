from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


OPENMVS_VERSION = "2.4.0"

_PROFILE_STAGES = {
    "preview": ("interface", "densify", "mesh"),
    "standard": ("interface", "densify", "mesh", "texture"),
    "high": ("interface", "densify", "mesh", "refine", "texture"),
}


def _absolute_path(value: str | Path, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path.")
    return path


def openmvs_capability() -> dict[str, Any]:
    return {
        "backend": "openmvs",
        "version": OPENMVS_VERSION,
        "role": "optional_dense_mesh_backend",
        "replaces_odm_mapping": False,
        "input": "prepared_colmap_workspace",
        "profiles": sorted(_PROFILE_STAGES),
        "license": "AGPL-3.0",
    }


def evaluate_mvs_readiness(
    sfm_qa: Mapping[str, Any],
) -> dict[str, Any]:
    """Translate sparse-SfM QA into an OpenMVS gate without hiding warnings."""

    status = sfm_qa.get("status")
    if status == "blocked":
        return {
            "status": "blocked",
            "reason": "sfm_qa_blocked",
            "issues": list(sfm_qa.get("issues") or []),
        }

    images = sfm_qa.get("images")
    image_info = images if isinstance(images, Mapping) else {}
    sparse = sfm_qa.get("sparse_points")
    sparse_info = sparse if isinstance(sparse, Mapping) else {}

    registered = int(image_info.get("registered") or 0)
    points = int(sparse_info.get("count") or 0)
    if registered < 2:
        return {
            "status": "blocked",
            "reason": "insufficient_registered_images",
            "issues": list(sfm_qa.get("issues") or []),
        }
    if points <= 0:
        return {
            "status": "blocked",
            "reason": "no_sparse_points",
            "issues": list(sfm_qa.get("issues") or []),
        }

    return {
        "status": "warning" if status == "warning" else "ready",
        "reason": None,
        "registered_images": registered,
        "sparse_points": points,
        "issues": list(sfm_qa.get("issues") or []),
    }


def plan_openmvs_pipeline(
    *,
    colmap_workspace: str | Path,
    image_folder: str | Path,
    output_dir: str | Path,
    profile: str = "standard",
) -> dict[str, Any]:
    """Create a deterministic COLMAP -> OpenMVS command plan.

    The caller is responsible for staging a COLMAP workspace that OpenMVS can
    consume. Paths are required to be absolute to avoid ambiguous relative image
    resolution in OpenMVS 2.4.0.
    """

    if profile not in _PROFILE_STAGES:
        raise ValueError(
            f"Unsupported OpenMVS profile: {profile}. "
            f"Expected one of {sorted(_PROFILE_STAGES)}."
        )

    colmap = _absolute_path(colmap_workspace, "colmap_workspace")
    images = _absolute_path(image_folder, "image_folder")
    output = _absolute_path(output_dir, "output_dir")

    scene = output / "scene.mvs"
    dense = output / "scene_dense.mvs"
    mesh = output / "scene_dense_mesh.mvs"
    refined = output / "scene_dense_mesh_refine.mvs"
    textured = output / "scene_dense_mesh_texture.mvs"

    stages: dict[str, dict[str, Any]] = {
        "interface": {
            "name": "InterfaceCOLMAP",
            "command": [
                "InterfaceCOLMAP",
                "-i",
                str(colmap),
                "-o",
                str(scene),
                "--image-folder",
                str(images),
            ],
            "output": str(scene),
        },
        "densify": {
            "name": "DensifyPointCloud",
            "command": [
                "DensifyPointCloud",
                str(scene),
                "-o",
                str(dense),
            ],
            "input": str(scene),
            "output": str(dense),
        },
        "mesh": {
            "name": "ReconstructMesh",
            "command": [
                "ReconstructMesh",
                str(dense),
                "-o",
                str(mesh),
            ],
            "input": str(dense),
            "output": str(mesh),
        },
        "refine": {
            "name": "RefineMesh",
            "command": [
                "RefineMesh",
                str(mesh),
                "-o",
                str(refined),
            ],
            "input": str(mesh),
            "output": str(refined),
        },
    }

    texture_input = refined if "refine" in _PROFILE_STAGES[profile] else mesh
    stages["texture"] = {
        "name": "TextureMesh",
        "command": [
            "TextureMesh",
            str(texture_input),
            "-o",
            str(textured),
        ],
        "input": str(texture_input),
        "output": str(textured),
    }

    ordered = [stages[name] for name in _PROFILE_STAGES[profile]]
    final_scene = Path(ordered[-1]["output"])

    artifacts = [
        {
            "type": "openmvs_scene",
            "path": str(scene),
            "required": True,
        },
        {
            "type": "dense_scene",
            "path": str(dense),
            "required": True,
        },
        {
            "type": "dense_point_cloud",
            "glob": str(output / "scene_dense*.ply"),
            "required": False,
        },
        {
            "type": "mesh",
            "glob": str(output / "scene_dense_mesh*.ply"),
            "required": profile in {"preview", "standard", "high"},
        },
    ]
    if "refine" in _PROFILE_STAGES[profile]:
        artifacts.append(
            {
                "type": "refined_scene",
                "path": str(refined),
                "required": True,
            }
        )
    if "texture" in _PROFILE_STAGES[profile]:
        artifacts.extend(
            [
                {
                    "type": "textured_scene",
                    "path": str(textured),
                    "required": True,
                },
                {
                    "type": "textured_mesh",
                    "glob": str(output / "*.obj"),
                    "required": False,
                },
                {
                    "type": "texture_material",
                    "glob": str(output / "*.mtl"),
                    "required": False,
                },
                {
                    "type": "texture_image",
                    "glob": str(output / "*material*"),
                    "required": False,
                },
            ]
        )

    return {
        "backend": "openmvs",
        "version": OPENMVS_VERSION,
        "profile": profile,
        "colmap_workspace": str(colmap),
        "image_folder": str(images),
        "output_dir": str(output),
        "stages": ordered,
        "final_scene": str(final_scene),
        "artifacts": artifacts,
    }
