from __future__ import annotations

from app.photogrammetry_pointcloud import (
    PDAL_VERSION,
    parse_pdal_stats,
    parse_pdal_summary,
    pdal_stats_command,
    pdal_summary_command,
)


def test_pdal_commands_are_stable():
    assert PDAL_VERSION == "2.10.2"
    assert pdal_summary_command("cloud.laz") == [
        "pdal", "info", "--summary", "cloud.laz"
    ]
    assert pdal_stats_command("cloud.laz") == [
        "pdal",
        "info",
        "--stats",
        "--dimensions=X,Y,Z,Classification",
        "--enumerate=Classification",
        "cloud.laz",
    ]


def test_parse_summary_produces_metric_density_and_structured_srs():
    result = parse_pdal_summary(
        {
            "reader": "readers.las",
            "pdal_version": "2.10.2 (git-version: Release)",
            "summary": {
                "bounds": {
                    "minx": 500000.0,
                    "miny": 5400000.0,
                    "minz": 100.0,
                    "maxx": 500100.0,
                    "maxy": 5400100.0,
                    "maxz": 140.0,
                },
                "dimensions": "X, Y, Z, Classification, Red, Green, Blue",
                "num_points": 100000,
                "srs": {
                    "wkt": "EPSG:32632",
                    "compoundwkt": "EPSG:32632",
                    "proj4": "+proj=utm +zone=32 +datum=WGS84 +units=m +no_defs",
                    "units": {"horizontal": "metre", "vertical": ""},
                },
            },
        }
    )

    assert result["status"] == "ready"
    assert result["point_count"] == 100000
    assert result["srs"]["identifier"] == "EPSG:32632"
    assert result["srs"]["epsg"] == 32632
    assert result["srs"]["projected"] is True
    assert result["density_xy"] == 10.0
    assert result["density_unit"] == "points_per_square_metre"
    assert "Classification" in result["dimensions"]


def test_summary_srs_mapping_is_not_stringified():
    result = parse_pdal_summary(
        {
            "summary": {
                "bounds": {
                    "minx": 0, "miny": 0, "minz": 0,
                    "maxx": 10, "maxy": 10, "maxz": 5,
                },
                "num_points": 100,
                "srs": {
                    "wkt": "EPSG:32632",
                    "units": {"horizontal": "metre"},
                },
            }
        }
    )

    assert isinstance(result["srs"], dict)
    assert result["srs"]["identifier"] == "EPSG:32632"


def test_missing_srs_is_warning_not_blocker():
    result = parse_pdal_summary(
        {
            "summary": {
                "bounds": {
                    "minx": 0, "miny": 0, "minz": 0,
                    "maxx": 10, "maxy": 10, "maxz": 5,
                },
                "num_points": 100,
            }
        }
    )

    assert result["status"] == "warning"
    assert result["density_unit"] == "points_per_square_crs_unit"
    assert any(
        issue["code"] == "POINTCLOUD_CRS_MISSING"
        for issue in result["issues"]
    )


def test_geographic_srs_warns_and_density_is_not_labelled_per_metre():
    result = parse_pdal_summary(
        {
            "summary": {
                "bounds": {
                    "minx": 8.0, "miny": 49.0, "minz": 100,
                    "maxx": 8.1, "maxy": 49.1, "maxz": 120,
                },
                "num_points": 100,
                "srs": {
                    "wkt": "EPSG:4326",
                    "units": {"horizontal": "degree"},
                },
            }
        }
    )

    assert result["status"] == "warning"
    assert result["srs"]["geographic"] is True
    assert result["density_unit"] == "points_per_square_crs_unit"
    assert any(
        issue["code"] == "POINTCLOUD_CRS_NOT_PROJECTED"
        for issue in result["issues"]
    )


def test_degenerate_xy_extent_blocks():
    result = parse_pdal_summary(
        {
            "summary": {
                "bounds": {
                    "minx": 1, "miny": 1, "minz": 0,
                    "maxx": 1, "maxy": 2, "maxz": 5,
                },
                "num_points": 10,
                "srs": {"wkt": "EPSG:32632"},
            }
        }
    )

    assert result["status"] == "blocked"
    assert any(
        issue["code"] == "POINTCLOUD_XY_EXTENT_DEGENERATE"
        for issue in result["issues"]
    )


def test_parse_stats_extracts_z_range_and_class_counts():
    result = parse_pdal_stats(
        {
            "stats": {
                "statistic": [
                    {"name": "X", "minimum": 0, "maximum": 10, "average": 5},
                    {"name": "Y", "minimum": 0, "maximum": 10, "average": 5},
                    {"name": "Z", "minimum": 100, "maximum": 135, "average": 112},
                    {
                        "name": "Classification",
                        "minimum": 1,
                        "maximum": 2,
                        "counts": [
                            {"value": 1, "count": 800},
                            {"value": 2, "count": 200},
                        ],
                    },
                ]
            }
        }
    )

    assert result["status"] == "ready"
    assert result["z_range"] == 35.0
    assert result["classification_counts"] == [
        {"value": 1, "count": 800},
        {"value": 2, "count": 200},
    ]


def test_missing_xyz_stat_dimension_is_warning():
    result = parse_pdal_stats(
        {
            "stats": {
                "statistic": [
                    {"name": "Z", "minimum": 1, "maximum": 2},
                ]
            }
        }
    )

    assert result["status"] == "warning"
    missing = {
        issue["dimension"]
        for issue in result["issues"]
        if issue["code"] == "POINTCLOUD_STATS_DIMENSION_MISSING"
    }
    assert missing == {"X", "Y"}



def test_unparseable_srs_is_warning_not_ready():
    result = parse_pdal_summary(
        {
            "summary": {
                "bounds": {
                    "minx": 0, "miny": 0, "minz": 0,
                    "maxx": 10, "maxy": 10, "maxz": 5,
                },
                "num_points": 100,
                "srs": {
                    "wkt": "NOT_A_VALID_CRS",
                    "units": {"horizontal": "metre"},
                },
            }
        }
    )

    assert result["status"] == "warning"
    assert result["srs"]["identifier"] is None
    assert result["density_unit"] == "points_per_square_crs_unit"
    assert any(
        issue["code"] == "POINTCLOUD_CRS_UNRESOLVED"
        for issue in result["issues"]
    )



def test_invalid_xyz_stat_range_is_warning():
    result = parse_pdal_stats(
        {
            "stats": {
                "statistic": [
                    {"name": "X", "minimum": 0, "maximum": 10},
                    {"name": "Y", "minimum": 0, "maximum": 10},
                    {"name": "Z", "minimum": 20, "maximum": 10},
                ]
            }
        }
    )

    assert result["status"] == "warning"
    assert result["z_range"] is None
    assert any(
        issue["code"] == "POINTCLOUD_STATS_DIMENSION_INVALID"
        and issue["dimension"] == "Z"
        for issue in result["issues"]
    )


def test_incomplete_xyz_stat_record_is_warning():
    result = parse_pdal_stats(
        {
            "stats": {
                "statistic": [
                    {"name": "X", "minimum": 0, "maximum": 10},
                    {"name": "Y", "average": 5},
                    {"name": "Z", "minimum": 1, "maximum": 2},
                ]
            }
        }
    )

    assert result["status"] == "warning"
    assert any(
        issue["code"] == "POINTCLOUD_STATS_DIMENSION_INVALID"
        and issue["dimension"] == "Y"
        for issue in result["issues"]
    )


def test_lowercase_ply_dimensions_are_canonicalized():
    summary = parse_pdal_summary(
        {
            "reader": "readers.ply",
            "summary": {
                "bounds": {
                    "minx": 0, "miny": 0, "minz": 0,
                    "maxx": 2, "maxy": 2, "maxz": 3,
                },
                "dimensions": "x, y, z",
                "num_points": 4,
            },
        }
    )
    stats = parse_pdal_stats(
        {
            "stats": {
                "statistic": [
                    {"name": "x", "minimum": 0, "maximum": 2},
                    {"name": "y", "minimum": 0, "maximum": 2},
                    {"name": "z", "minimum": 0, "maximum": 3},
                ]
            }
        }
    )

    assert summary["dimensions"] == ["X", "Y", "Z"]
    assert stats["status"] == "ready"
    assert set(stats["dimensions"]) == {"X", "Y", "Z"}
    assert stats["z_range"] == 3.0
