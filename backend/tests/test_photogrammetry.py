from __future__ import annotations

from copy import deepcopy

from app.photogrammetry import fuse_photogrammetry_metadata


def _file_metadata() -> dict:
    return {
        "capture_time": "2026:09:23 12:00:00",
        "utc_at_exposure": "2026:09:23 12:00:00.123",
        "gps": {
            "latitude": 49.100001,
            "longitude": 8.500001,
            "altitude": 123.4,
        },
        "dji": {
            "absolute_altitude": 223.4,
            "relative_altitude": 83.4,
            "flight_yaw": 10.0,
            "flight_pitch": -2.0,
            "flight_roll": 1.0,
            "gimbal_yaw": 9.9,
            "gimbal_pitch": -89.8,
            "gimbal_roll": 0.2,
            "rtk_flag": 50,
            "rtk_fixed": True,
            "capture_uuid": "capture-file",
        },
    }


def _fh2_media() -> dict:
    return {
        "captureUuid": "capture-file",
        "asset": {
            "capture": {
                "capturedAt": 1790164800123,
                "latitudeDeg": 49.100001,
                "longitudeDeg": 8.500001,
                "ellipsoidHeightM": 223.4,
                "relativeHeightM": 83.4,
                "aircraftYawDeg": 10.0,
                "aircraftPitchDeg": -2.0,
                "aircraftRollDeg": 1.0,
                "gimbalYawDeg": 9.9,
                "gimbalPitchDeg": -89.8,
                "gimbalRollDeg": 0.2,
                "rtkFixed": True,
            }
        },
        "sourceKeys": {
            "GpsLatitude": "XMP-drone-dji:GpsLatitude",
            "GpsLongitude": "XMP-drone-dji:GpsLongitude",
            "AbsoluteAltitude": "XMP-drone-dji:AbsoluteAltitude",
            "RelativeAltitude": "XMP-drone-dji:RelativeAltitude",
            "FlightYawDegree": "XMP-drone-dji:FlightYawDegree",
            "UTCAtExposure": "XMP-drone-dji:UTCAtExposure",
            "RtkFlag": "XMP-drone-dji:RtkFlag",
            "CaptureUUID": "XMP-drone-dji:CaptureUUID",
        },
    }


def test_fusion_prefers_fh2_capture_context_with_provenance():
    file_metadata = _file_metadata()
    fh2_media = _fh2_media()

    result = fuse_photogrammetry_metadata(file_metadata, fh2_media)

    assert result["position"] == {
        "latitude_deg": 49.100001,
        "longitude_deg": 8.500001,
    }
    assert result["height"]["ellipsoid_m"] == 223.4
    assert result["height"]["relative_m"] == 83.4
    assert result["rtk"]["fixed"] is True
    assert result["capture_uuid"] == "capture-file"
    assert result["conflicts"] == []

    latitude_source = result["provenance"]["position.latitude_deg"]
    assert latitude_source["source"] == "fh2_media"
    assert latitude_source["path"] == "asset.capture.latitudeDeg"
    assert latitude_source["source_key"] == "XMP-drone-dji:GpsLatitude"


def test_position_conflict_is_reported_without_silent_overwrite():
    file_metadata = _file_metadata()
    fh2_media = _fh2_media()
    fh2_media["asset"]["capture"]["latitudeDeg"] = 49.2

    result = fuse_photogrammetry_metadata(file_metadata, fh2_media)

    assert result["position"]["latitude_deg"] == 49.2
    conflict = next(
        item
        for item in result["conflicts"]
        if item["field"] == "position.latitude_deg"
    )
    assert conflict["kind"] == "value_mismatch"
    assert conflict["selected"]["source"] == "fh2_media"
    assert conflict["other"]["source"] == "file_metadata"
    assert conflict["tolerance"] == 1e-6


def test_generic_gps_altitude_is_not_promoted_to_ellipsoid_height():
    result = fuse_photogrammetry_metadata(
        {
            "gps": {
                "latitude": 49.0,
                "longitude": 8.0,
                "altitude": 150.0,
            },
            "dji": {},
        }
    )

    assert result["height"]["ellipsoid_m"] is None
    assert result["height"]["relative_m"] is None
    assert result["height"]["gps_altitude_m"] == 150.0
    assert result["height"]["gps_altitude_semantics"] == "generic_file_altitude"
    assert result["provenance"]["height.gps_altitude_m"] == {
        "source": "file_metadata",
        "path": "gps.altitude",
    }


def test_absolute_relative_and_generic_height_remain_separate():
    result = fuse_photogrammetry_metadata(
        {
            "gps": {"altitude": 130.0},
            "dji": {
                "absolute_altitude": 231.5,
                "relative_altitude": 81.5,
            },
        }
    )

    assert result["height"] == {
        "ellipsoid_m": 231.5,
        "relative_m": 81.5,
        "gps_altitude_m": 130.0,
        "gps_altitude_semantics": "generic_file_altitude",
    }


def test_capture_uuid_and_utc_exposure_are_separate_from_capture_time():
    file_metadata = _file_metadata()
    file_metadata["dji"]["capture_uuid"] = "capture-file-old"
    fh2_media = _fh2_media()
    fh2_media["captureUuid"] = "capture-fh2"

    result = fuse_photogrammetry_metadata(file_metadata, fh2_media)

    assert result["capture_uuid"] == "capture-fh2"
    assert result["time"]["utc_at_exposure_ms"] == 1790164800123
    assert result["time"]["capture_time"] == "2026:09:23 12:00:00"
    assert result["provenance"]["capture_uuid"]["source"] == "fh2_media"
    assert result["provenance"]["time.capture_time"]["source"] == "file_metadata"

    conflict_fields = {item["field"] for item in result["conflicts"]}
    assert "capture_uuid" in conflict_fields


def test_angles_are_normalized_before_conflict_comparison():
    file_metadata = {
        "dji": {
            "flight_yaw": 181.0,
        }
    }
    fh2_media = {
        "asset": {
            "capture": {
                "aircraftYawDeg": -179.0,
            }
        }
    }

    result = fuse_photogrammetry_metadata(file_metadata, fh2_media)

    assert result["orientation"]["aircraft_yaw_deg"] == -179.0
    assert not any(
        item["field"] == "orientation.aircraft_yaw_deg"
        for item in result["conflicts"]
    )


def test_invalid_values_do_not_override_valid_fallbacks():
    result = fuse_photogrammetry_metadata(
        {
            "gps": {"latitude": 49.0, "longitude": 8.0},
            "dji": {"rtk_flag": 50},
        },
        {
            "asset": {
                "capture": {
                    "latitudeDeg": 999,
                    "longitudeDeg": "not-a-number",
                    "rtkFixed": "yes",
                }
            }
        },
    )

    assert result["position"]["latitude_deg"] == 49.0
    assert result["position"]["longitude_deg"] == 8.0
    assert result["rtk"]["fixed"] is True
    assert result["rtk"]["raw_flag"] == 50


def test_fusion_does_not_mutate_inputs():
    file_metadata = _file_metadata()
    fh2_media = _fh2_media()
    file_before = deepcopy(file_metadata)
    fh2_before = deepcopy(fh2_media)

    fuse_photogrammetry_metadata(file_metadata, fh2_media)

    assert file_metadata == file_before
    assert fh2_media == fh2_before
