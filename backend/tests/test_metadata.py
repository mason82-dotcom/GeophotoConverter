from __future__ import annotations

from app.classifier import classify_media
from app.metadata import normalize_metadata


def test_normalize_metadata_reads_dji_group1_namespace() -> None:
    metadata = normalize_metadata(
        {
            "EXIF:Make": "DJI",
            "EXIF:Model": "Mavic 3 Multispectral",
            "XMP-drone-dji:UTCAtExposure": "2026:09:23 18:42:12.123456",
            "XMP-drone-dji:GpsLatitude": 49.123,
            "XMP-drone-dji:GpsLongitude": 8.456,
            "XMP-drone-dji:AbsoluteAltitude": 123.4,
            "XMP-drone-dji:RelativeAltitude": 40.1,
            "XMP-drone-dji:FlightYawDegree": 12.5,
            "XMP-drone-dji:GimbalPitchDegree": -90.0,
            "XMP-drone-dji:RtkFlag": 50,
            "XMP-drone-dji:CaptureUUID": "3377fb05-b357-448f-b87b-7023daebbaed",
            "XMP-drone-dji:ImageSource": "MS_RED_CAMERA",
            "XMP-drone-dji:BandName": "Red",
            "XMP-drone-dji:BandFreq": "650(+/-16)nm",
            "XMP-drone-dji:SensorIndex": 2,
            "XMP-drone-dji:Irradiance": 2000,
            "XMP-drone-dji:CameraSerialNumber": "CAM-1",
            "XMP-drone-dji:DroneSerialNumber": "M3M-001",
        }
    )

    assert metadata["capture_time"] == "2026:09:23 18:42:12.123456"
    assert metadata["gps"]["latitude"] == 49.123
    assert metadata["gps"]["longitude"] == 8.456
    assert metadata["dji"]["absolute_altitude"] == 123.4
    assert metadata["dji"]["relative_altitude"] == 40.1
    assert metadata["dji"]["rtk_flag"] == 50
    assert metadata["dji"]["rtk_fixed"] is True
    assert metadata["dji"]["capture_uuid"] == "3377fb05-b357-448f-b87b-7023daebbaed"
    assert metadata["dji"]["band_name"] == "Red"
    assert metadata["dji"]["sensor_index"] == 2
    assert metadata["dji"]["radiometry"]["irradiance"] == 2000
    assert metadata["camera"]["serial"] == "CAM-1"
    assert metadata["dji"]["drone_serial_number"] == "M3M-001"
    assert (
        metadata["dji"]["source_keys"]["CaptureUUID"]
        == "XMP-drone-dji:CaptureUUID"
    )


def test_normalize_metadata_keeps_legacy_xmp_fallback() -> None:
    metadata = normalize_metadata(
        {
            "XMP:AbsoluteAltitude": 88.0,
            "XMP:GimbalYawDegree": 17.5,
            "XMP:RtkFlag": 1,
        }
    )

    assert metadata["dji"]["absolute_altitude"] == 88.0
    assert metadata["dji"]["gimbal_yaw"] == 17.5
    assert metadata["dji"]["rtk_flag"] == 1
    assert metadata["dji"]["rtk_fixed"] is False


def test_capture_uuid_overrides_filename_grouping() -> None:
    metadata = normalize_metadata(
        {
            "XMP-drone-dji:CaptureUUID": "capture-a",
            "XMP-drone-dji:BandName": "Red",
        }
    )

    classification = classify_media("M3M/DJI_0001_MS_R.TIF", metadata)

    assert classification.platform == "M3M"
    assert classification.media_kind == "MS_RED"
    assert classification.media_kind_source == "authoritative"
    assert classification.capture_group == "dji:capture-a"
    assert classification.capture_group_source == "authoritative"
    assert classification.conflicts == ()


def test_authoritative_band_beats_conflicting_filename() -> None:
    metadata = normalize_metadata(
        {
            "XMP-drone-dji:CaptureUUID": "capture-b",
            "XMP-drone-dji:BandName": "Red",
        }
    )

    classification = classify_media("M3M/DJI_0002_MS_NIR.TIF", metadata)

    assert classification.media_kind == "MS_RED"
    assert classification.media_kind_source == "authoritative"
    assert classification.capture_group == "dji:capture-b"
    assert classification.conflicts == ("band_metadata_filename_conflict",)


def test_rgb_file_uses_authoritative_capture_uuid_for_grouping() -> None:
    metadata = normalize_metadata(
        {
            "XMP-drone-dji:CaptureUUID": "capture-c",
            "XMP-drone-dji:ProductName": "Mavic 3 Multispectral",
        }
    )

    classification = classify_media("M3M/DJI_0003_D.JPG", metadata)

    assert classification.platform == "M3M"
    assert classification.media_kind == "RGB"
    assert classification.media_kind_source == "heuristic"
    assert classification.capture_group == "dji:capture-c"
    assert classification.capture_group_source == "authoritative"
