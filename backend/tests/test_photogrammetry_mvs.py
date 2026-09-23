from __future__ import annotations

from pathlib import Path

import pytest

from app.photogrammetry_mvs import (
    OPENMVS_VERSION,
    evaluate_mvs_readiness,
    openmvs_capability,
    plan_openmvs_pipeline,
)


def test_capability_is_optional_and_does_not_replace_odm() -> None:
    capability = openmvs_capability()

    assert capability["version"] == "2.4.0"
    assert capability["role"] == "optional_dense_mesh_backend"
    assert capability["replaces_odm_mapping"] is False
    assert capability["license"] == "AGPL-3.0"


def test_preview_pipeline_stops_after_mesh() -> None:
    plan = plan_openmvs_pipeline(
        colmap_workspace="/data/job/colmap",
        image_folder="/data/job/colmap/images",
        output_dir="/data/job/openmvs",
        profile="preview",
    )

    assert [stage["name"] for stage in plan["stages"]] == [
        "InterfaceCOLMAP",
        "DensifyPointCloud",
        "ReconstructMesh",
    ]
    assert plan["final_scene"].endswith("scene_dense_mesh.mvs")


def test_standard_pipeline_adds_texture_without_refine() -> None:
    plan = plan_openmvs_pipeline(
        colmap_workspace="/data/job/colmap",
        image_folder="/data/job/colmap/images",
        output_dir="/data/job/openmvs",
        profile="standard",
    )

    names = [stage["name"] for stage in plan["stages"]]
    assert names == [
        "InterfaceCOLMAP",
        "DensifyPointCloud",
        "ReconstructMesh",
        "TextureMesh",
    ]
    texture = plan["stages"][-1]
    assert texture["input"].endswith("scene_dense_mesh.mvs")
    assert texture["output"].endswith("scene_dense_mesh_texture.mvs")


def test_high_pipeline_refines_before_texture() -> None:
    plan = plan_openmvs_pipeline(
        colmap_workspace="/data/job/colmap",
        image_folder="/data/job/colmap/images",
        output_dir="/data/job/openmvs",
        profile="high",
    )

    names = [stage["name"] for stage in plan["stages"]]
    assert names == [
        "InterfaceCOLMAP",
        "DensifyPointCloud",
        "ReconstructMesh",
        "RefineMesh",
        "TextureMesh",
    ]
    assert plan["stages"][-1]["input"].endswith(
        "scene_dense_mesh_refine.mvs"
    )


def test_interface_colmap_uses_explicit_absolute_image_folder() -> None:
    plan = plan_openmvs_pipeline(
        colmap_workspace="/data/job/colmap",
        image_folder="/data/job/colmap/images",
        output_dir="/data/job/openmvs",
    )
    command = plan["stages"][0]["command"]

    assert command == [
        "InterfaceCOLMAP",
        "-i",
        "/data/job/colmap",
        "-o",
        "/data/job/openmvs/scene.mvs",
        "--image-folder",
        "/data/job/colmap/images",
    ]


def test_relative_paths_are_rejected() -> None:
    with pytest.raises(ValueError, match="absolute"):
        plan_openmvs_pipeline(
            colmap_workspace="relative/colmap",
            image_folder="/data/job/colmap/images",
            output_dir="/data/job/openmvs",
        )


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported OpenMVS profile"):
        plan_openmvs_pipeline(
            colmap_workspace="/data/job/colmap",
            image_folder="/data/job/colmap/images",
            output_dir="/data/job/openmvs",
            profile="ultra",
        )


def test_sfm_blocked_prevents_mvs() -> None:
    readiness = evaluate_mvs_readiness(
        {
            "status": "blocked",
            "issues": [{"code": "SFM_NO_SPARSE_POINTS"}],
            "images": {"registered": 10},
            "sparse_points": {"count": 0},
        }
    )

    assert readiness["status"] == "blocked"
    assert readiness["reason"] == "sfm_qa_blocked"


def test_sfm_warning_is_preserved_but_mvs_remains_available() -> None:
    readiness = evaluate_mvs_readiness(
        {
            "status": "warning",
            "issues": [{"code": "SFM_LOW_REGISTRATION_RATIO"}],
            "images": {"registered": 20},
            "sparse_points": {"count": 1000},
        }
    )

    assert readiness["status"] == "warning"
    assert readiness["reason"] is None
    assert readiness["registered_images"] == 20
    assert readiness["sparse_points"] == 1000


def test_version_contract_is_pinned() -> None:
    assert OPENMVS_VERSION == "2.4.0"
