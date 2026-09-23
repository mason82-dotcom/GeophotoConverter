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


def test_parse_summary_produces_density_and_bounds():
    result = parse_pdal_summary({
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
            "srs": "EPSG:32632",
        },
    })

    assert result["status"] == "ready"
    assert result["point_count"] == 100000
    assert result["srs"] == "EPSG:32632"
    assert result["density_points_per_square_unit"] == 10.0
    assert "Classification" in result["dimensions"]


def test_missing_srs_is_warning_not_blocker():
    result = parse_pdal_summary({
        "summary": {
            "bounds": {
                "minx": 0, "miny": 0, "minz": 0,
                "maxx": 10, "maxy": 10, "maxz": 5,
            },
            "num_points": 100,
        }
    })

    assert result["status"] == "warning"
    assert any(i["code"] == "POINTCLOUD_CRS_MISSING" for i in result["issues"])


def test_degenerate_xy_extent_blocks():
    result = parse_pdal_summary({
        "summary": {
            "bounds": {
                "minx": 1, "miny": 1, "minz": 0,
                "maxx": 1, "maxy": 2, "maxz": 5,
            },
            "num_points": 10,
            "srs": "EPSG:32632",
        }
    })

    assert result["status"] == "blocked"
    assert any(
        i["code"] == "POINTCLOUD_XY_EXTENT_DEGENERATE"
        for i in result["issues"]
    )


def test_parse_stats_extracts_z_range_and_class_counts():
    result = parse_pdal_stats({
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
    })

    assert result["status"] == "ready"
    assert result["z_range"] == 35.0
    assert result["dimensions"]["Classification"]["counts"][1]["count"] == 200


def test_missing_xyz_stat_dimension_is_warning():
    result = parse_pdal_stats({
        "stats": {
            "statistic": [
                {"name": "Z", "minimum": 1, "maximum": 2},
            ]
        }
    })

    assert result["status"] == "warning"
    missing = {
        i["dimension"]
        for i in result["issues"]
        if i["code"] == "POINTCLOUD_STATS_DIMENSION_MISSING"
    }
    assert missing == {"X", "Y"}
