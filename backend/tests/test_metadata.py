from __future__ import annotations

from app.classifier import classify_media, reconcile_group_platforms
from app.metadata import _normalize_metadata, _rtk_status


def test_normalize_m3e_family1_metadata():
    raw = {
        "IFD0:Make": "DJI",
        "IFD0:Model": "Mavic 3 Enterprise",
        "ExifIFD:DateTimeOriginal": "2026:09:23 18:42:10",
        "ExifIFD:ISO": 100,
        "ExifIFD:FNumber": 5.6,
        "ExifIFD:FocalLength": 12.29,
        "ExifIFD:FocalLengthIn35mmFormat": 24,
        "ExifIFD:ExposureTime": 0.001,
        "File:ImageWidth": 5280,
        "File:ImageHeight": 3956,
        "XMP-drone-dji:GPSLatitude": 49.123456,
        "XMP-drone-dji:GPSLongitude": 8.456789,
        "XMP-drone-dji:GpsStatus": "Normal",
        "XMP-drone-dji:AltitudeType": "GpsFusionAlt",
        "XMP-drone-dji:AbsoluteAltitude": 142.32,
        "XMP-drone-dji:RelativeAltitude": 75.10,
        "XMP-drone-dji:GimbalRollDegree": 0.1,
        "XMP-drone-dji:GimbalYawDegree": 15.2,
        "XMP-drone-dji:GimbalPitchDegree": -89.8,
        "XMP-drone-dji:FlightRollDegree": 0.4,
        "XMP-drone-dji:FlightYawDegree": 15.0,
        "XMP-drone-dji:FlightPitchDegree": -1.2,
        "XMP-drone-dji:FlightXSpeed": 4.2,
        "XMP-drone-dji:FlightYSpeed": -0.3,
        "XMP-drone-dji:FlightZSpeed": 0.1,
        "XMP-drone-dji:CamReverse": "0",
        "XMP-drone-dji:GimbalReverse": "0",
        "XMP-drone-dji:CaptureUUID": "3377fb05-b357-448f-b87b-7023daebbaed",
        "XMP-drone-dji:RtkFlag": 50,
        "XMP-drone-dji:RtkStdLon": 0.012,
        "XMP-drone-dji:RtkStdLat": 0.014,
        "XMP-drone-dji:RtkStdHgt": 0.022,
        "XMP-drone-dji:RtkDiffAge": 0.8,
        "XMP-drone-dji:SurveyingMode": 1,
        "XMP-drone-dji:DewarpFlag": 0,
        "XMP-drone-dji:DewarpData": (
            "2026-09-23;3663.48,3661.22,0.12,-0.34,"
            "-0.10,0.01,0.001,-0.002,0.0003"
        ),
        "XMP-drone-dji:UTCAtExposure": "2026-09-23T16:42:10.123Z",
        "XMP-drone-dji:ShutterType": "Mechanical",
        "XMP-drone-dji:ShutterCount": 12345,
        "XMP-drone-dji:CameraSerialNumber": "CAM-M3E-001",
        "XMP-drone-dji:LensSerialNumber": "LENS-M3E-001",
        "XMP-drone-dji:DroneModel": "Mavic 3 Enterprise",
        "XMP-drone-dji:DroneSerialNumber": "DRONE-M3E-001",
        "XMP-drone-dji:CalibratedFocalLength": 3662.35,
        "XMP-drone-dji:CalibratedOpticalCenterX": 0.12,
        "XMP-drone-dji:CalibratedOpticalCenterY": -0.34,
    }

    metadata = _normalize_metadata(raw)

    assert metadata["capture_time"] == "2026:09:23 18:42:10"
    assert metadata["utc_at_exposure"] == "2026-09-23T16:42:10.123Z"
    assert metadata["camera"]["make"] == "DJI"
    assert metadata["camera"]["model"] == "Mavic 3 Enterprise"
    assert metadata["camera"]["serial"] == "CAM-M3E-001"
    assert metadata["camera"]["lens_serial"] == "LENS-M3E-001"
    assert metadata["camera"]["shutter_type"] == "Mechanical"
    assert metadata["camera"]["shutter_count"] == 12345
    assert metadata["image"]["focal_length"] == 12.29
    assert metadata["image"]["focal_length_35mm"] == 24

    assert metadata["gps"]["latitude"] == 49.123456
    assert metadata["gps"]["longitude"] == 8.456789
    assert metadata["gps"]["altitude"] == 142.32
    assert metadata["gps"]["status"] == "Normal"
    assert metadata["gps"]["altitude_type"] == "GpsFusionAlt"

    dji = metadata["dji"]
    assert dji["drone_model"] == "Mavic 3 Enterprise"
    assert dji["drone_serial_number"] == "DRONE-M3E-001"
    assert dji["product_name"] == "Mavic 3 Enterprise"
    assert dji["capture_uuid"] == "3377fb05-b357-448f-b87b-7023daebbaed"
    assert dji["gimbal_reverse"] == "0"
    assert dji["rtk_flag"] == 50
    assert dji["rtk_status"] == "fixed"
    assert dji["rtk_fixed"] is True
    assert dji["rtk_std_lon"] == 0.012
    assert dji["rtk_std_lat"] == 0.014
    assert dji["rtk_std_hgt"] == 0.022
    assert dji["rtk_diff_age"] == 0.8
    assert dji["surveying_mode"] == 1
    assert dji["surveying_recommended"] is True
    assert dji["flight_speed_x"] == 4.2
    assert dji["flight_speed_y"] == -0.3
    assert dji["flight_speed_z"] == 0.1
    assert dji["dewarp_calibration"] == {
        "fx": 3663.48,
        "fy": 3661.22,
        "cx": 0.12,
        "cy": -0.34,
        "k1": -0.10,
        "k2": 0.01,
        "p1": 0.001,
        "p2": -0.002,
        "k3": 0.0003,
        "calibration_date": "2026-09-23",
    }


def test_normalize_legacy_xmp_aliases_remain_supported():
    metadata = _normalize_metadata(
        {
            "EXIF:Make": "DJI",
            "EXIF:Model": "M3E",
            "XMP:AbsoluteAltitude": 100.0,
            "XMP:RelativeAltitude": 50.0,
            "XMP:RtkFlag": "34",
            "XMP:FlightYawDegree": 90.0,
            "XMP:GimbalPitchDegree": -90.0,
        }
    )

    assert metadata["dji"]["absolute_altitude"] == 100.0
    assert metadata["dji"]["relative_altitude"] == 50.0
    assert metadata["dji"]["rtk_flag"] == "34"
    assert metadata["dji"]["rtk_status"] == "float"
    assert metadata["dji"]["rtk_fixed"] is False
    assert metadata["dji"]["flight_yaw"] == 90.0
    assert metadata["dji"]["gimbal_pitch"] == -90.0


def test_m3e_classification_uses_drone_model_metadata():
    metadata = {
        "camera": {"make": "DJI", "model": None},
        "dji": {"drone_model": "Mavic 3 Enterprise"},
    }

    wide = classify_media("flight/DJI_0001_W.JPG", metadata)
    zoom = classify_media("flight/DJI_0001_Z.JPG", None)

    reconciled = reconcile_group_platforms(
        [
            ("flight/DJI_0001_W.JPG", wide),
            ("flight/DJI_0001_Z.JPG", zoom),
        ]
    )

    assert wide.platform == "M3E"
    assert wide.media_kind == "WIDE"
    assert reconciled["flight/DJI_0001_Z.JPG"].platform == "M3E"
    assert reconciled["flight/DJI_0001_Z.JPG"].media_kind == "ZOOM"



def test_m3e_rtk_status_mapping():
    assert _rtk_status(0) == "failed"
    assert _rtk_status(16) == "single"
    assert _rtk_status(32) == "float"
    assert _rtk_status(34) == "float"
    assert _rtk_status(49) == "float"
    assert _rtk_status(50) == "fixed"
    assert _rtk_status(51) == "unknown"
    assert _rtk_status(52) == "unknown"
    assert _rtk_status(999) == "unknown"
    assert _rtk_status(None) is None



def test_capture_uuid_is_preferred_grouping_key():
    metadata = {
        "camera": {"make": "DJI", "model": "Mavic 3 Enterprise"},
        "dji": {"capture_uuid": "  capture-123  "},
    }

    wide = classify_media("flight/DJI_0001_W.JPG", metadata)
    generic = classify_media("flight/DJI_9999.JPG", metadata)

    assert wide.capture_group == "dji:capture-123"
    assert generic.capture_group == "dji:capture-123"


def test_capture_group_falls_back_to_filename_without_capture_uuid():
    metadata = {
        "camera": {"make": "DJI", "model": "Mavic 3 Multispectral"},
        "dji": {},
    }

    rgb = classify_media("M3M/DJI_0002_D.JPG", metadata)
    nir = classify_media("M3M/DJI_0002_MS_NIR.TIF", metadata)

    assert rgb.capture_group == "M3M/DJI_0002"
    assert nir.capture_group == "M3M/DJI_0002"
