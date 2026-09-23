from __future__ import annotations

import pytest

from app.pointcloud_processing import (
    build_reprojection_pipeline,
    reprojection_provenance,
)


def test_build_reprojection_pipeline_uses_safe_laz_writer():
    result = build_reprojection_pipeline(
        "input.laz",
        "output.laz",
        source_crs="EPSG:4326",
        target_crs="EPSG:32632",
    )

    assert result["source"]["reader"] == "readers.las"
    assert result["source"]["crs"] == "EPSG:4326"
    assert result["target"]["crs"] == "EPSG:32632"
    assert result["vertical_reference"]["status"] == "unchanged_unspecified"

    stages = result["pipeline"]["pipeline"]
    assert stages[1] == {
        "type": "filters.reprojection",
        "in_srs": "EPSG:4326",
        "out_srs": "EPSG:32632",
    }

    writer = stages[2]
    assert writer["type"] == "writers.las"
    assert writer["compression"] is True
    assert writer["a_srs"] == "EPSG:32632"
    assert writer["forward"] == "header"
    assert writer["scale_x"] == "auto"
    assert writer["scale_y"] == "auto"
    assert writer["scale_z"] == "auto"
    assert writer["offset_x"] == "auto"
    assert writer["offset_y"] == "auto"
    assert writer["offset_z"] == "auto"
    assert writer.get("forward") != "all"


def test_copc_input_uses_copc_reader():
    result = build_reprojection_pipeline(
        "source.copc.laz",
        "target.laz",
        source_crs="EPSG:25832",
        target_crs="EPSG:32632",
    )
    assert result["source"]["reader"] == "readers.copc"


@pytest.mark.parametrize("target", ["EPSG:4326", "EPSG:2230"])
def test_target_must_be_metric_projected(target):
    with pytest.raises(ValueError, match="projected with metre axes"):
        build_reprojection_pipeline(
            "source.laz",
            "target.laz",
            source_crs="EPSG:4326",
            target_crs=target,
        )


def test_compound_crs_is_rejected_to_avoid_vertical_datum_claims():
    with pytest.raises(ValueError, match="horizontal CRS"):
        build_reprojection_pipeline(
            "source.laz",
            "target.laz",
            source_crs="EPSG:32632+7837",
            target_crs="EPSG:32632",
        )


def test_identical_crs_is_rejected():
    with pytest.raises(ValueError, match="identical"):
        build_reprojection_pipeline(
            "source.laz",
            "target.laz",
            source_crs="EPSG:32632",
            target_crs="EPSG:32632",
        )


def test_output_must_be_new_laz_path():
    with pytest.raises(ValueError, match="must use .laz"):
        build_reprojection_pipeline(
            "source.laz",
            "target.las",
            source_crs="EPSG:4326",
            target_crs="EPSG:32632",
        )

    with pytest.raises(ValueError, match="must differ"):
        build_reprojection_pipeline(
            "source.laz",
            "source.laz",
            source_crs="EPSG:4326",
            target_crs="EPSG:32632",
        )


def test_provenance_archives_pipeline_and_source_identity():
    contract = build_reprojection_pipeline(
        "source.laz",
        "target.laz",
        source_crs="EPSG:4326",
        target_crs="EPSG:32632",
    )

    provenance = reprojection_provenance(
        contract,
        source_job_id="job-123",
        source_artifact_index=4,
        source_sha256="abc123",
    )

    assert provenance["operation"] == "reproject"
    assert provenance["source_job_id"] == "job-123"
    assert provenance["source_artifact_index"] == 4
    assert provenance["source_sha256"] == "abc123"
    assert provenance["source_crs"] == "EPSG:4326"
    assert provenance["target_crs"] == "EPSG:32632"
    assert provenance["software"] == {
        "engine": "pdal",
        "version_contract": "2.10.2",
    }
    assert provenance["pipeline"] == contract["pipeline"]
