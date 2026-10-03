from __future__ import annotations

import pytest

from app.photogrammetry_metadata import (
    build_photogrammetry_metadata,
    candidate,
)


def test_file_sources_use_field_specific_priority_and_keep_provenance():
    result = build_photogrammetry_metadata(
        [
            candidate(
                "position.latitude_deg",
                49.1234567,
                source_kind="fh2_dji_media",
                source_key="GpsLatitude",
                source_id="fh2:asset-1",
            ),
            candidate(
                "position.latitude_deg",
                49.1234567,
                source_kind="file_exif",
                source_key="GPS:GPSLatitude",
                source_id="file:DJI_0001.JPG",
            ),
            candidate(
                "capture.capture_uuid",
                "uuid-fh2",
                source_kind="fh2_dji_media",
                source_key="CaptureUUID",
                source_id="fh2:asset-1",
            ),
            candidate(
                "capture.capture_uuid",
                "uuid-file",
                source_kind="file_dji_xmp",
                source_key="XMP-drone-dji:CaptureUUID",
                source_id="file:DJI_0001.JPG",
            ),
        ]
    )

    assert result["position"]["latitude_deg"] == 49.1234567
    assert result["capture"]["capture_uuid"] == "uuid-file"
    assert (
        result["source_provenance"]["position.latitude_deg"]["selected"]["source_kind"]
        == "file_exif"
    )
    assert (
        result["source_provenance"]["capture.capture_uuid"]["selected"]["source_kind"]
        == "file_dji_xmp"
    )


def test_fh2_supplements_missing_file_metadata_without_overwriting():
    result = build_photogrammetry_metadata(
        [
            candidate(
                "capture.utc_at_exposure",
                None,
                source_kind="file_dji_xmp",
                source_key="XMP-drone-dji:UTCAtExposure",
            ),
            candidate(
                "capture.utc_at_exposure",
                "2026-09-23T16:42:10.123Z",
                source_kind="fh2_dji_media",
                source_key="UTCAtExposure",
            ),
            candidate(
                "camera_geometry.focal_length_mm",
                12.29,
                source_kind="fh2_dji_media",
                source_key="FocalLength",
            ),
        ]
    )

    assert result["capture"]["utc_at_exposure"] == "2026-09-23T16:42:10.123Z"
    assert result["camera_geometry"]["focal_length_mm"] == 12.29
    assert result["conflicts"] == []


def test_conflicting_positions_are_structured_and_critical():
    result = build_photogrammetry_metadata(
        [
            candidate(
                "position.longitude_deg",
                8.456789,
                source_kind="file_exif",
                source_key="GPS:GPSLongitude",
            ),
            candidate(
                "position.longitude_deg",
                8.457500,
                source_kind="fh2_dji_media",
                source_key="GpsLongitude",
            ),
        ]
    )

    assert result["position"]["longitude_deg"] == 8.456789
    assert result["conflicts"] == [
        {
            "field": "position.longitude_deg",
            "kind": "value_mismatch",
            "severity": "critical",
            "selected": {
                "source_kind": "file_exif",
                "source_key": "GPS:GPSLongitude",
                "source_id": None,
                "value": 8.456789,
            },
            "alternatives": [
                {
                    "source_kind": "fh2_dji_media",
                    "source_key": "GpsLongitude",
                    "source_id": None,
                    "value": 8.4575,
                }
            ],
        }
    ]


def test_small_numeric_differences_inside_tolerance_do_not_create_conflict():
    result = build_photogrammetry_metadata(
        [
            candidate(
                "position.absolute_altitude_m",
                142.30,
                source_kind="file_dji_xmp",
                source_key="XMP-drone-dji:AbsoluteAltitude",
            ),
            candidate(
                "position.absolute_altitude_m",
                142.35,
                source_kind="fh2_dji_media",
                source_key="AbsoluteAltitude",
            ),
        ]
    )

    assert result["position"]["absolute_altitude_m"] == 142.30
    assert result["conflicts"] == []


def test_time_axes_and_height_references_remain_separate():
    result = build_photogrammetry_metadata(
        [
            candidate(
                "capture.date_time_original",
                "2026:09:23 18:42:10",
                source_kind="file_exif",
                source_key="ExifIFD:DateTimeOriginal",
            ),
            candidate(
                "capture.utc_at_exposure",
                "2026-09-23T16:42:31Z",
                source_kind="file_dji_xmp",
                source_key="XMP-drone-dji:UTCAtExposure",
            ),
            candidate(
                "position.gps_altitude_m",
                143.0,
                source_kind="file_exif",
                source_key="GPS:GPSAltitude",
            ),
            candidate(
                "position.absolute_altitude_m",
                142.3,
                source_kind="file_dji_xmp",
                source_key="XMP-drone-dji:AbsoluteAltitude",
            ),
            candidate(
                "position.relative_height_m",
                75.1,
                source_kind="file_dji_xmp",
                source_key="XMP-drone-dji:RelativeAltitude",
            ),
        ]
    )

    assert result["capture"]["date_time_original"] == "2026:09:23 18:42:10"
    assert result["capture"]["utc_at_exposure"] == "2026-09-23T16:42:31Z"
    assert result["position"] == {
        "latitude_deg": None,
        "longitude_deg": None,
        "gps_altitude_m": 143.0,
        "absolute_altitude_m": 142.3,
        "relative_height_m": 75.1,
    }


def test_angles_are_normalized_without_changing_source_provenance():
    result = build_photogrammetry_metadata(
        [
            candidate(
                "pose.aircraft_yaw_deg",
                370,
                source_kind="file_dji_xmp",
                source_key="XMP-drone-dji:FlightYawDegree",
            ),
            candidate(
                "pose.gimbal_roll_deg",
                -181,
                source_kind="file_dji_xmp",
                source_key="XMP-drone-dji:GimbalRollDegree",
            ),
        ]
    )

    assert result["pose"]["aircraft_yaw_deg"] == 10.0
    assert result["pose"]["gimbal_roll_deg"] == 179.0


@pytest.mark.parametrize(
    ("flag", "expected_fixed", "expected_classification"),
    [
        (50, True, "rtk_fixed"),
        (34, False, "rtk_unknown_quality"),
        (16, False, "gnss_non_rtk"),
        (0, False, "unknown"),
        (52, False, "rtk_unknown_quality"),
        (None, None, "unknown"),
    ],
)
def test_rtk_semantics_are_derived_from_raw_flag(
    flag,
    expected_fixed,
    expected_classification,
):
    items = []
    if flag is not None:
        items.append(
            candidate(
                "gnss.rtk_flag_raw",
                flag,
                source_kind="file_dji_xmp",
                source_key="XMP-drone-dji:RtkFlag",
            )
        )

    result = build_photogrammetry_metadata(items)

    assert result["gnss"]["rtk_fixed"] is expected_fixed
    assert result["gnss"]["classification"] == expected_classification


def test_gps_status_rtk_without_flag_is_not_treated_as_fixed():
    result = build_photogrammetry_metadata(
        [
            candidate(
                "gnss.gps_status",
                "RTK",
                source_kind="fh2_dji_media",
                source_key="GpsStatus",
            )
        ]
    )

    assert result["gnss"]["rtk_fixed"] is None
    assert result["gnss"]["classification"] == "rtk_unknown_quality"


def test_invalid_position_candidate_is_not_selected_when_valid_fallback_exists():
    result = build_photogrammetry_metadata(
        [
            candidate(
                "position.latitude_deg",
                120,
                source_kind="file_exif",
                source_key="GPS:GPSLatitude",
            ),
            candidate(
                "position.latitude_deg",
                49.1,
                source_kind="fh2_dji_media",
                source_key="GpsLatitude",
            ),
        ]
    )

    assert result["position"]["latitude_deg"] == 49.1
    assert result["conflicts"][0]["kind"] == "invalid_value"
    assert result["conflicts"][0]["severity"] == "critical"


def test_unknown_canonical_field_is_rejected():
    with pytest.raises(ValueError, match="Unbekanntes kanonisches"):
        build_photogrammetry_metadata(
            [
                candidate(
                    "position.magic",
                    1,
                    source_kind="file_exif",
                    source_key="Magic",
                )
            ]
        )
