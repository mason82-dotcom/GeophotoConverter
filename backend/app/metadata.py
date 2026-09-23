from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


_RTK_STATUS = {
    0: "failed",
    16: "single",
    50: "fixed",
}


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in ("", None):
            return data[key]
    return None


def _dji_first_with_key(
    data: dict[str, Any],
    *tags: str,
) -> tuple[Any, str | None]:
    for tag in tags:
        for key in (f"XMP-drone-dji:{tag}", f"XMP:{tag}"):
            if key in data and data[key] not in ("", None):
                return data[key], key
    return None, None


def _dji_first(data: dict[str, Any], *tags: str) -> Any:
    value, _ = _dji_first_with_key(data, *tags)
    return value


def _numeric_list(value: Any) -> list[float] | None:
    if isinstance(value, (list, tuple)):
        try:
            values = [float(item) for item in value]
        except (TypeError, ValueError):
            return None
        return values or None
    if not isinstance(value, str):
        return None
    parts = [part for part in re.split(r"[\s,;]+", value.strip()) if part]
    if not parts:
        return None
    try:
        return [float(part) for part in parts]
    except ValueError:
        return None


def _int_code(value: Any) -> int | None:
    if value in ("", None):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _rtk_status(value: Any) -> str | None:
    code = _int_code(value)
    if code is None:
        return None
    if 32 <= code <= 49:
        return "float"
    return _RTK_STATUS.get(code, "unknown")


def _surveying_recommended(value: Any) -> bool | None:
    code = _int_code(value)
    if code == 1:
        return True
    if code == 0:
        return False
    return None


def _parse_dewarp_data(value: Any) -> dict[str, Any] | None:
    if value in ("", None):
        return None

    raw = str(value).strip().strip('"')
    if not raw:
        return None

    calibration_date: str | None = None
    values_text = raw
    if ";" in raw:
        prefix, values_text = raw.split(";", 1)
        prefix = prefix.strip()
        if prefix:
            calibration_date = prefix

    parts = [
        part
        for part in re.split(r"[\s,]+", values_text.strip())
        if part
    ]
    if len(parts) < 9:
        return None

    try:
        values = [float(part) for part in parts[:9]]
    except ValueError:
        return None

    result: dict[str, Any] = {
        "fx": values[0],
        "fy": values[1],
        "cx": values[2],
        "cy": values[3],
        "k1": values[4],
        "k2": values[5],
        "p1": values[6],
        "p2": values[7],
        "k3": values[8],
    }
    if calibration_date:
        result["calibration_date"] = calibration_date
    return result


def _normalize_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    dji_latitude = _dji_first(raw, "GPSLatitude", "GpsLatitude", "Latitude")
    dji_longitude = _dji_first(
        raw,
        "GPSLongitude",
        "GpsLongitude",
        "GPSLongtitude",
        "GpsLongtitude",
        "Longitude",
    )

    latitude = _first(
        raw,
        "GPS:GPSLatitude",
        "EXIF:GPSLatitude",
        "Composite:GPSLatitude",
    )
    if latitude is None:
        latitude = dji_latitude

    longitude = _first(
        raw,
        "GPS:GPSLongitude",
        "EXIF:GPSLongitude",
        "Composite:GPSLongitude",
    )
    if longitude is None:
        longitude = dji_longitude

    absolute_altitude = _dji_first(raw, "AbsoluteAltitude")
    relative_altitude = _dji_first(raw, "RelativeAltitude")
    altitude = _first(raw, "GPS:GPSAltitude", "EXIF:GPSAltitude")
    if altitude is None:
        altitude = absolute_altitude if absolute_altitude is not None else relative_altitude

    utc_at_exposure = _dji_first(raw, "UTCAtExposure")
    rtk_flag = _dji_first(raw, "RtkFlag", "RTKFlag")
    dewarp_data = _dji_first(raw, "DewarpData")
    camera_serial = _first(
        raw,
        "XMP-drone-dji:CameraSerialNumber",
        "XMP:CameraSerialNumber",
        "ExifIFD:BodySerialNumber",
        "ExifIFD:SerialNumber",
        "EXIF:SerialNumber",
        "XMP-aux:SerialNumber",
        "XMP:SerialNumber",
    )
    lens_serial = _first(
        raw,
        "XMP-drone-dji:LensSerialNumber",
        "XMP:LensSerialNumber",
        "ExifIFD:LensSerialNumber",
        "XMP-aux:LensSerialNumber",
    )
    drone_model = _dji_first(raw, "DroneModel")
    drone_serial = _dji_first(raw, "DroneSerialNumber", "DroneID")

    source_keys: dict[str, str] = {}

    def m3m_value(name: str, *aliases: str) -> Any:
        value, source_key = _dji_first_with_key(raw, name, *aliases)
        if source_key is not None:
            source_keys[name] = source_key
        return value

    image_source = m3m_value("ImageSource")
    band_name = m3m_value("BandName")
    band_frequency = m3m_value("BandFreq")
    central_wavelength_nm = m3m_value("CentralWavelength")
    sensor_index = m3m_value("SensorIndex")
    irradiance = m3m_value("Irradiance")
    sunlight_sensor_status = m3m_value("LS_status")
    raw_sunlight_sensor_raw = m3m_value("RawData")
    sensor_gain = m3m_value("SensorGain")
    sensor_gain_adjustment = m3m_value("SensorGainAdjustment")
    multispectral_exposure_time = m3m_value("ExposureTime")
    black_level = m3m_value("BlackLevel", "BlackCurrent")
    vignetting_data = m3m_value("VignettingData")
    calibrated_h_matrix = m3m_value("CalibratedHMatrix")

    return {
        "capture_time": _first(
            raw,
            "ExifIFD:DateTimeOriginal",
            "EXIF:DateTimeOriginal",
            "XMP-xmp:CreateDate",
            "XMP:CreateDate",
            "ExifIFD:CreateDate",
            "EXIF:CreateDate",
        )
        or utc_at_exposure,
        "utc_at_exposure": utc_at_exposure,
        "camera": {
            "make": _first(
                raw,
                "IFD0:Make",
                "EXIF:Make",
                "XMP-tiff:Make",
                "XMP:Make",
            ),
            "model": _first(
                raw,
                "IFD0:Model",
                "EXIF:Model",
                "XMP-tiff:Model",
                "XMP:Model",
            ),
            "serial": camera_serial,
            "lens": _first(
                raw,
                "ExifIFD:LensModel",
                "EXIF:LensModel",
                "XMP-aux:Lens",
                "XMP:Lens",
            ),
            "lens_serial": lens_serial,
            "shutter_type": _dji_first(raw, "ShutterType"),
            "shutter_count": _dji_first(raw, "ShutterCount"),
        },
        "image": {
            "width": _first(
                raw,
                "File:ImageWidth",
                "ExifIFD:ExifImageWidth",
                "EXIF:ExifImageWidth",
                "IFD0:ImageWidth",
            ),
            "height": _first(
                raw,
                "File:ImageHeight",
                "ExifIFD:ExifImageHeight",
                "EXIF:ExifImageHeight",
                "IFD0:ImageHeight",
            ),
            "iso": _first(raw, "ExifIFD:ISO", "EXIF:ISO"),
            "f_number": _first(raw, "ExifIFD:FNumber", "EXIF:FNumber"),
            "focal_length": _first(raw, "ExifIFD:FocalLength", "EXIF:FocalLength"),
            "focal_length_35mm": _first(
                raw,
                "ExifIFD:FocalLengthIn35mmFormat",
                "EXIF:FocalLengthIn35mmFormat",
                "ExifIFD:FocalLengthIn35mmFilm",
                "EXIF:FocalLengthIn35mmFilm",
            ),
            "exposure_time": _first(raw, "ExifIFD:ExposureTime", "EXIF:ExposureTime"),
        },
        "gps": {
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude,
            "status": _dji_first(raw, "GpsStatus", "GPSStatus"),
            "altitude_type": _dji_first(raw, "AltitudeType"),
        },
        "dji": {
            "absolute_altitude": absolute_altitude,
            "relative_altitude": relative_altitude,
            "flight_yaw": _dji_first(raw, "FlightYawDegree"),
            "flight_pitch": _dji_first(raw, "FlightPitchDegree"),
            "flight_roll": _dji_first(raw, "FlightRollDegree"),
            "flight_speed_x": _dji_first(raw, "FlightXSpeed"),
            "flight_speed_y": _dji_first(raw, "FlightYSpeed"),
            "flight_speed_z": _dji_first(raw, "FlightZSpeed"),
            "gimbal_yaw": _dji_first(raw, "GimbalYawDegree"),
            "gimbal_pitch": _dji_first(raw, "GimbalPitchDegree"),
            "gimbal_roll": _dji_first(raw, "GimbalRollDegree"),
            "cam_reverse": _dji_first(raw, "CamReverse"),
            "gimbal_reverse": _dji_first(raw, "GimbalReverse"),
            "capture_uuid": _dji_first(raw, "CaptureUUID"),
            "image_source": image_source,
            "band_name": band_name,
            "band_frequency": band_frequency,
            "central_wavelength_nm": central_wavelength_nm,
            "sensor_index": sensor_index,
            "rtk_flag": rtk_flag,
            "rtk_status": _rtk_status(rtk_flag),
            "rtk_fixed": _rtk_status(rtk_flag) == "fixed" if rtk_flag is not None else None,
            "rtk_std_lon": _dji_first(raw, "RtkStdLon"),
            "rtk_std_lat": _dji_first(raw, "RtkStdLat"),
            "rtk_std_hgt": _dji_first(raw, "RtkStdHgt"),
            "rtk_diff_age": _dji_first(raw, "RtkDiffAge"),
            "surveying_mode": _dji_first(raw, "SurveyingMode"),
            "surveying_recommended": _surveying_recommended(
                _dji_first(raw, "SurveyingMode")
            ),
            "dewarp_flag": _dji_first(raw, "DewarpFlag"),
            "dewarp_data": dewarp_data,
            "dewarp_calibration": _parse_dewarp_data(dewarp_data),
            "calibrated_focal_length": _dji_first(raw, "CalibratedFocalLength"),
            "calibrated_optical_center_x": _dji_first(
                raw,
                "CalibratedOpticalCenterX",
            ),
            "calibrated_optical_center_y": _dji_first(
                raw,
                "CalibratedOpticalCenterY",
            ),
            "radiometry": {
                "irradiance": irradiance,
                "sunlight_sensor_status": sunlight_sensor_status,
                "raw_sunlight_sensor": _numeric_list(raw_sunlight_sensor_raw),
                "sensor_gain": sensor_gain,
                "sensor_gain_adjustment": sensor_gain_adjustment,
                "exposure_time": multispectral_exposure_time,
                "black_level": black_level,
                "vignetting_data": vignetting_data,
                "calibrated_h_matrix": calibrated_h_matrix,
            },
            "source_keys": source_keys,
            "product_name": _dji_first(raw, "ProductName", "AircraftType", "DroneModel")
            or _first(raw, "MakerNotes:AircraftType"),
            "aircraft_type": _dji_first(raw, "AircraftType", "DroneModel")
            or _first(raw, "MakerNotes:AircraftType"),
            "drone_model": drone_model,
            "drone_serial_number": drone_serial,
        },
    }


def read_metadata(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["exiftool", "-json", "-n", "-G1", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    payload = json.loads(proc.stdout)
    if not payload:
        raise ValueError("ExifTool hat keine Metadaten zurückgegeben")
    return _normalize_metadata(payload[0])
