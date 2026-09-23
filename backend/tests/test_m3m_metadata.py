from __future__ import annotations

from app.classifier import classify_media
from app.metadata import _normalize_metadata


def test_m3m_metadata_fields_and_radiometry_are_normalized():
    metadata = _normalize_metadata(
        {
            "IFD0:Make": "DJI",
            "IFD0:Model": "Mavic 3 Multispectral",
            "XMP-drone-dji:CaptureUUID": "capture-a",
            "XMP-drone-dji:ImageSource": "MS_RED_CAMERA",
            "XMP-drone-dji:BandName": "Red",
            "XMP-drone-dji:BandFreq": "650(+/-16)nm",
            "XMP-drone-dji:CentralWavelength": 650,
            "XMP-drone-dji:SensorIndex": 2,
            "XMP-drone-dji:Irradiance": 2000,
            "XMP-drone-dji:LS_status": 2,
            "XMP-drone-dji:RawData": "11682 10389 12836 9945",
            "XMP-drone-dji:SensorGain": 1.044,
            "XMP-drone-dji:SensorGainAdjustment": 0.998,
            "XMP-drone-dji:ExposureTime": 1000,
            "XMP-drone-dji:BlackCurrent": 3200,
            "XMP-drone-dji:VignettingData": "-0.1,0.2",
            "XMP-drone-dji:CalibratedHMatrix": "1,0,0,0,1,0,0,0,1",
        }
    )

    dji = metadata["dji"]
    assert dji["capture_uuid"] == "capture-a"
    assert dji["image_source"] == "MS_RED_CAMERA"
    assert dji["band_name"] == "Red"
    assert dji["band_frequency"] == "650(+/-16)nm"
    assert dji["central_wavelength_nm"] == 650
    assert dji["sensor_index"] == 2
    assert dji["radiometry"]["irradiance"] == 2000
    assert dji["radiometry"]["raw_sunlight_sensor"] == [
        11682.0,
        10389.0,
        12836.0,
        9945.0,
    ]
    assert dji["radiometry"]["black_level"] == 3200
    assert dji["source_keys"]["BandName"] == "XMP-drone-dji:BandName"


def test_authoritative_band_name_overrides_filename_band_and_reports_conflict():
    metadata = _normalize_metadata(
        {
            "IFD0:Model": "Mavic 3 Multispectral",
            "XMP-drone-dji:CaptureUUID": "capture-b",
            "XMP-drone-dji:BandName": "Red",
        }
    )

    result = classify_media("M3M/DJI_0001_MS_NIR.TIF", metadata)

    assert result.platform == "M3M"
    assert result.media_kind == "MS_RED"
    assert result.media_kind_source == "authoritative"
    assert result.capture_group == "dji:capture-b"
    assert result.capture_group_source == "authoritative"
    assert result.conflicts == ("band_metadata_filename_conflict",)


def test_filename_band_is_fallback_when_band_name_is_missing():
    metadata = _normalize_metadata(
        {
            "IFD0:Model": "Mavic 3 Multispectral",
            "XMP-drone-dji:CaptureUUID": "capture-c",
        }
    )

    result = classify_media("M3M/DJI_0002_MS_RE.TIF", metadata)

    assert result.media_kind == "MS_RED_EDGE"
    assert result.media_kind_source == "heuristic"
    assert result.capture_group == "dji:capture-c"
    assert result.capture_group_source == "authoritative"


def test_band_metadata_can_identify_m3m_even_when_camera_model_conflicts():
    metadata = _normalize_metadata(
        {
            "IFD0:Model": "Mavic 3 Enterprise",
            "XMP-drone-dji:CaptureUUID": "capture-d",
            "XMP-drone-dji:BandName": "Green",
        }
    )

    result = classify_media("DJI_0003_MS_G.TIF", metadata)

    assert result.platform == "M3M"
    assert result.media_kind == "MS_GREEN"
    assert "band_platform_conflict" in result.conflicts
