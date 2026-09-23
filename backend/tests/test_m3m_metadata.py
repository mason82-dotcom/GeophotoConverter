from __future__ import annotations

from app.classifier import classify_media
from app.metadata import _normalize_metadata


def test_m3m_normalization_includes_capture_uuid_and_radiometry():
    metadata = _normalize_metadata(
        {
            "IFD0:Make": "DJI",
            "IFD0:Model": "Mavic 3 Multispectral",
            "XMP-drone-dji:CaptureUUID": "3377fb05-b357-448f-b87b-7023daebbaed",
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
            "XMP-drone-dji:RtkFlag": 50,
        }
    )

    dji = metadata["dji"]
    assert dji["capture_uuid"] == "3377fb05-b357-448f-b87b-7023daebbaed"
    assert dji["band_name"] == "Red"
    assert dji["band_frequency"] == "650(+/-16)nm"
    assert dji["central_wavelength_nm"] == 650
    assert dji["sensor_index"] == 2
    assert dji["rtk_status"] == "fixed"
    assert dji["rtk_fixed"] is True
    assert dji["radiometry"]["irradiance"] == 2000
    assert dji["radiometry"]["raw_sunlight_sensor"] == [
        11682.0, 10389.0, 12836.0, 9945.0
    ]
    assert dji["source_keys"]["CaptureUUID"] == "XMP-drone-dji:CaptureUUID"


def test_capture_uuid_is_authoritative_for_m3m_grouping():
    metadata = _normalize_metadata(
        {
            "IFD0:Model": "Mavic 3 Multispectral",
            "XMP-drone-dji:CaptureUUID": "capture-a",
            "XMP-drone-dji:BandName": "Red",
        }
    )

    classification = classify_media("M3M/DJI_0001_MS_NIR.TIF", metadata)

    assert classification.platform == "M3M"
    assert classification.media_kind == "MS_RED"
    assert classification.media_kind_source == "authoritative"
    assert classification.capture_group == "dji:capture-a"
    assert classification.capture_group_source == "authoritative"
    assert classification.conflicts == ("band_metadata_filename_conflict",)


def test_capture_uuid_groups_rgb_and_multispectral_assets_together():
    rgb_metadata = _normalize_metadata(
        {
            "IFD0:Model": "Mavic 3 Multispectral",
            "XMP-drone-dji:CaptureUUID": "capture-b",
        }
    )
    nir_metadata = _normalize_metadata(
        {
            "IFD0:Model": "Mavic 3 Multispectral",
            "XMP-drone-dji:CaptureUUID": "capture-b",
            "XMP-drone-dji:BandName": "NIR",
        }
    )

    rgb = classify_media("M3M/DJI_0002_D.JPG", rgb_metadata)
    nir = classify_media("M3M/DJI_0002_MS_NIR.TIF", nir_metadata)

    assert rgb.capture_group == "dji:capture-b"
    assert nir.capture_group == "dji:capture-b"
    assert rgb.capture_group_source == "authoritative"
    assert nir.capture_group_source == "authoritative"


def test_filename_grouping_remains_fallback_without_capture_uuid():
    metadata = _normalize_metadata(
        {
            "IFD0:Model": "Mavic 3 Multispectral",
            "XMP-drone-dji:BandName": "NIR",
        }
    )

    classification = classify_media("M3M/DJI_0004_MS_NIR.TIF", metadata)

    assert classification.capture_group == "M3M/DJI_0004"
    assert classification.capture_group_source == "heuristic"


def test_capture_uuid_applies_to_generic_dji_media():
    metadata = _normalize_metadata(
        {
            "IFD0:Model": "Mavic 3 Enterprise",
            "XMP-drone-dji:CaptureUUID": "capture-generic",
        }
    )

    classification = classify_media("flight/DJI_9999.JPG", metadata)

    assert classification.capture_group == "dji:capture-generic"
    assert classification.capture_group_source == "authoritative"
