from __future__ import annotations

import pytest

from app.photogrammetry_pdal_ground import (
    DEFAULT_HAG,
    DEFAULT_SMRF,
    build_ground_hag_contract,
    ground_hag_provenance,
)


def test_ground_hag_contract_is_deterministic_and_preserves_raw_z():
    contract = build_ground_hag_contract(
        source_relative_path="jobs/source/results/cloud.laz",
        output_relative_path="jobs/derived/ground-hag.laz",
        source_crs="EPSG:32632",
    )

    assert contract["operation"] == "ground_hag"
    assert contract["source"]["crs"] == "EPSG:32632"
    assert contract["output"]["crs"] == "EPSG:32632"
    assert contract["output"]["las_minor_version"] == 4
    assert contract["classification_reset"] == 0
    assert contract["vertical_reference"]["status"] == "source_z_unchanged"
    assert contract["hag"]["dimension"] == "HeightAboveGround"

    stages = contract["pipeline"]["pipeline"]
    assert [stage["type"] for stage in stages] == [
        "readers.las",
        "filters.assign",
        "filters.smrf",
        "filters.hag_nn",
        "writers.las",
    ]
    assert stages[1]["value"] == "Classification=0"
    assert stages[2]["cell"] == DEFAULT_SMRF["cell"]
    assert stages[2]["returns"] == DEFAULT_SMRF["returns"]
    assert stages[2]["ground_class"] == 2
    assert stages[2]["other_class"] == 1
    assert stages[3]["count"] == DEFAULT_HAG["count"]
    assert stages[3]["allow_extrapolation"] is False
    assert stages[3]["class"] == 2

    writer = stages[4]
    assert writer["a_srs"] == "EPSG:32632"
    assert writer["compression"] is True
    assert writer["minor_version"] == 4
    assert writer["forward"] == "header,vlr"
    assert writer["extra_dims"] == "all"
    assert writer["scale_x"] == 0.001
    assert writer["scale_y"] == 0.001
    assert writer["scale_z"] == 0.001
    assert writer["offset_x"] == "auto"
    assert writer["offset_y"] == "auto"
    assert writer["offset_z"] == "auto"

    # HAG remains an extra dimension; the pipeline must not ferry it into Z.
    assert all(stage["type"] != "filters.ferry" for stage in stages)


def test_ground_hag_copc_uses_copc_reader():
    contract = build_ground_hag_contract(
        source_relative_path="jobs/a/cloud.copc.laz",
        output_relative_path="jobs/a/ground-hag.laz",
        source_crs="EPSG:25832",
    )

    assert contract["source"]["reader"] == "readers.copc"
    assert contract["pipeline"]["pipeline"][0]["type"] == "readers.copc"


@pytest.mark.parametrize(
    "source_crs,error",
    [
        ("EPSG:4326", "projected"),
        ("EPSG:4979", "horizontal 2D"),
        ("EPSG:32632+7837", "horizontal 2D"),
        ("EPSG:2277", "metre"),
    ],
)
def test_ground_hag_requires_metric_projected_2d_source(source_crs, error):
    with pytest.raises(ValueError, match=error):
        build_ground_hag_contract(
            source_relative_path="jobs/a/cloud.laz",
            output_relative_path="jobs/a/ground-hag.laz",
            source_crs=source_crs,
        )


@pytest.mark.parametrize(
    "source_path,output_path,error",
    [
        ("../cloud.laz", "jobs/a/out.laz", "unsafe"),
        ("/data/cloud.laz", "jobs/a/out.laz", "relative"),
        ("jobs/a/cloud.ply", "jobs/a/out.laz", "LAS"),
        ("jobs/a/cloud.laz", "../out.laz", "unsafe"),
        ("jobs/a/cloud.laz", "jobs/a/out.las", ".laz suffix"),
        ("jobs/a/cloud.laz", "jobs/a/cloud.laz", "new artifact"),
    ],
)
def test_ground_hag_rejects_unsafe_paths(source_path, output_path, error):
    with pytest.raises(ValueError, match=error):
        build_ground_hag_contract(
            source_relative_path=source_path,
            output_relative_path=output_path,
            source_crs="EPSG:32632",
        )


def test_ground_hag_records_explicit_tuning_parameters():
    contract = build_ground_hag_contract(
        source_relative_path="jobs/a/cloud.laz",
        output_relative_path="jobs/a/ground-hag.laz",
        source_crs="EPSG:32632",
        coordinate_scale_m=0.0005,
        smrf_cell_m=0.5,
        smrf_cut_m=5.0,
        smrf_returns="first,last,only",
        smrf_scalar=1.4,
        smrf_slope=0.2,
        smrf_threshold_m=0.35,
        smrf_window_m=12.0,
        ground_class=2,
        other_class=1,
        hag_count=4,
        hag_max_distance_m=20.0,
        hag_allow_extrapolation=True,
    )

    assert contract["coordinate_scale_m"] == 0.0005
    assert contract["smrf"] == {
        "cell_m": 0.5,
        "cut_m": 5.0,
        "returns": "first,last,only",
        "scalar": 1.4,
        "slope": 0.2,
        "threshold_m": 0.35,
        "window_m": 12.0,
        "ground_class": 2,
        "other_class": 1,
        "only_ground": False,
    }
    assert contract["hag"] == {
        "method": "nearest_neighbor",
        "count": 4,
        "max_distance_m": 20.0,
        "allow_extrapolation": True,
        "ground_class": 2,
        "dimension": "HeightAboveGround",
    }
    hag_stage = contract["pipeline"]["pipeline"][3]
    assert hag_stage["max_distance"] == 20.0


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"smrf_cell_m": 0}, "smrf_cell_m"),
        ({"smrf_window_m": 0.5, "smrf_cell_m": 1.0}, "greater than or equal"),
        ({"smrf_scalar": 0}, "smrf_scalar"),
        ({"smrf_slope": -0.1}, "smrf_slope"),
        ({"smrf_threshold_m": -0.1}, "smrf_threshold_m"),
        ({"smrf_returns": "banana"}, "unsupported return"),
        ({"smrf_returns": "last,last"}, "unique"),
        ({"ground_class": 2, "other_class": 2}, "must differ"),
        ({"hag_count": 0}, "hag_count"),
        ({"hag_count": 65}, "hag_count"),
        ({"hag_max_distance_m": 0}, "hag_max_distance_m"),
        ({"hag_allow_extrapolation": 1}, "boolean"),
        ({"coordinate_scale_m": 1.0}, "coordinate_scale_m"),
    ],
)
def test_ground_hag_rejects_invalid_parameters(kwargs, error):
    with pytest.raises(ValueError, match=error):
        build_ground_hag_contract(
            source_relative_path="jobs/a/cloud.laz",
            output_relative_path="jobs/a/ground-hag.laz",
            source_crs="EPSG:32632",
            **kwargs,
        )


def test_ground_hag_provenance_binds_source_and_parameters():
    contract = build_ground_hag_contract(
        source_relative_path="jobs/source/cloud.laz",
        output_relative_path="jobs/derived/ground-hag.laz",
        source_crs="EPSG:32632",
        hag_count=3,
    )

    provenance = ground_hag_provenance(
        contract,
        source_job_id="job-123",
        source_artifact_index=4,
        source_sha256="cd" * 32,
    )

    assert provenance["operation"] == "ground_hag"
    assert provenance["source_job_id"] == "job-123"
    assert provenance["source_artifact_index"] == 4
    assert provenance["source_sha256"] == "cd" * 32
    assert provenance["crs"] == "EPSG:32632"
    assert provenance["smrf"] == contract["smrf"]
    assert provenance["hag"] == contract["hag"]
    assert provenance["hag"]["count"] == 3
    assert provenance["vertical_reference"]["status"] == "source_z_unchanged"
    assert provenance["pipeline"] == contract["pipeline"]
    assert provenance["software"] == {
        "engine": "pdal",
        "version_contract": "2.10.2",
    }


@pytest.mark.parametrize(
    "job_id,index,checksum,error",
    [
        ("", 0, None, "source_job_id"),
        ("job", -1, None, "source_artifact_index"),
        ("job", True, None, "source_artifact_index"),
        ("job", 0, "not-sha256", "source_sha256"),
    ],
)
def test_ground_hag_provenance_rejects_invalid_source_identity(
    job_id,
    index,
    checksum,
    error,
):
    contract = build_ground_hag_contract(
        source_relative_path="jobs/a/cloud.laz",
        output_relative_path="jobs/a/ground-hag.laz",
        source_crs="EPSG:32632",
    )

    with pytest.raises(ValueError, match=error):
        ground_hag_provenance(
            contract,
            source_job_id=job_id,
            source_artifact_index=index,
            source_sha256=checksum,
        )
