from __future__ import annotations

import pytest

from app.photogrammetry_pdal_pipeline import build_reprojection_contract


def test_build_reprojection_contract_is_deterministic():
    contract = build_reprojection_contract(
        source_relative_path="jobs/source/results/cloud.laz",
        output_relative_path="jobs/source/derived/cloud-32633.laz",
        source_crs="EPSG:32632",
        target_crs="EPSG:32633",
    )

    assert contract["operation"] == "horizontal_reprojection"
    assert contract["source"]["crs"] == "EPSG:32632"
    assert contract["output"]["crs"] == "EPSG:32633"
    assert contract["vertical_transform"] is False
    assert contract["coordinate_scale_m"] == 0.001

    stages = contract["pipeline"]["pipeline"]
    assert stages[0] == {
        "type": "readers.las",
        "filename": "/data/jobs/source/results/cloud.laz",
    }
    assert stages[1] == {
        "type": "filters.reprojection",
        "in_srs": "EPSG:32632",
        "out_srs": "EPSG:32633",
    }

    writer = stages[2]
    assert writer["type"] == "writers.las"
    assert writer["filename"].endswith("/derived/cloud-32633.laz")
    assert writer["a_srs"] == "EPSG:32633"
    assert writer["compression"] is True
    assert writer["forward"] == "header,vlr"
    assert writer["extra_dims"] == "all"
    assert writer["scale_x"] == 0.001
    assert writer["scale_y"] == 0.001
    assert writer["scale_z"] == 0.001
    assert writer["offset_x"] == "auto"
    assert writer["offset_y"] == "auto"
    assert writer["offset_z"] == "auto"


def test_geographic_source_to_metric_projected_target_is_allowed():
    contract = build_reprojection_contract(
        source_relative_path="jobs/a/cloud.las",
        output_relative_path="jobs/a/cloud-utm.laz",
        source_crs="EPSG:4326",
        target_crs="EPSG:32632",
    )

    stage = contract["pipeline"]["pipeline"][1]
    assert stage["in_srs"] == "EPSG:4326"
    assert stage["out_srs"] == "EPSG:32632"


@pytest.mark.parametrize(
    "source,target,error",
    [
        ("EPSG:32632", "EPSG:4326", "projected"),
        ("EPSG:32632", "EPSG:2277", "metre"),
        ("EPSG:4979", "EPSG:32632", "horizontal 2D"),
        ("EPSG:32632", "EPSG:32632", "must differ"),
    ],
)
def test_reprojection_rejects_unsafe_crs_contracts(source, target, error):
    with pytest.raises(ValueError, match=error):
        build_reprojection_contract(
            source_relative_path="jobs/a/cloud.laz",
            output_relative_path="jobs/a/derived.laz",
            source_crs=source,
            target_crs=target,
        )


@pytest.mark.parametrize(
    "source_path,output_path,error",
    [
        ("../cloud.laz", "jobs/a/out.laz", "unsafe"),
        ("/data/cloud.laz", "jobs/a/out.laz", "relative"),
        ("jobs/a/cloud.ply", "jobs/a/out.laz", "LAS or LAZ"),
        ("jobs/a/cloud.laz", "../out.laz", "unsafe"),
        ("jobs/a/cloud.laz", "jobs/a/out.las", ".laz suffix"),
        ("jobs/a/cloud.laz", "jobs/a/cloud.laz", "new artifact"),
    ],
)
def test_reprojection_rejects_unsafe_paths(source_path, output_path, error):
    with pytest.raises(ValueError, match=error):
        build_reprojection_contract(
            source_relative_path=source_path,
            output_relative_path=output_path,
            source_crs="EPSG:32632",
            target_crs="EPSG:32633",
        )


@pytest.mark.parametrize("scale", [0, -0.001, 1.0, float("inf"), float("nan")])
def test_reprojection_rejects_invalid_coordinate_scale(scale):
    with pytest.raises(ValueError, match="Coordinate scale"):
        build_reprojection_contract(
            source_relative_path="jobs/a/cloud.laz",
            output_relative_path="jobs/a/out.laz",
            source_crs="EPSG:32632",
            target_crs="EPSG:32633",
            coordinate_scale_m=scale,
        )


def test_reprojection_accepts_configurable_submillimetre_scale():
    contract = build_reprojection_contract(
        source_relative_path="jobs/a/cloud.laz",
        output_relative_path="jobs/a/out.laz",
        source_crs="EPSG:32632",
        target_crs="EPSG:32633",
        coordinate_scale_m=0.0001,
    )

    assert contract["coordinate_scale_m"] == 0.0001
    assert contract["pipeline"]["pipeline"][2]["scale_x"] == 0.0001
