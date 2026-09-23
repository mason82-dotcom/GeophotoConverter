from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in ("", None):
            return data[key]
    return None


def _first_with_key(data: dict[str, Any], *keys: str) -> tuple[Any, str | None]:
    for key in keys:
        if key in data and data[key] not in ("", None):
            return data[key], key
    return None, None


def normalize_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    source_keys: dict[str, str] = {}

    def dji(name: str, *aliases: str) -> Any:
        names = (name, *aliases)
        keys = tuple(
            key
            for tag in names
            for key in (f"XMP-drone-dji:{tag}", f"XMP:{tag}")
        )
        value, source_key = _first_with_key(raw, *keys)
        if source_key is not None:
            source_keys[name] = source_key
        return value

    utc_at_exposure = dji("UTCAtExposure")
    dji_latitude = dji("GpsLatitude")
    dji_longitude = dji("GpsLongitude")
    absolute_altitude = dji("AbsoluteAltitude")
    relative_altitude = dji("RelativeAltitude")
    camera_serial = dji("CameraSerialNumber")

    latitude = _first(
        raw,
        "GPS:GPSLatitude",
        "EXIF:GPSLatitude",
        "Composite:GPSLatitude",
    )
    longitude = _first(
        raw,
        "GPS:GPSLongitude",
        "EXIF:GPSLongitude",
        "Composite:GPSLongitude",
    )
    if dji_latitude is not None:
        latitude = dji_latitude
    if dji_longitude is not None:
        longitude = dji_longitude

    altitude = _first(raw, "GPS:GPSAltitude")
    if altitude is None:
        altitude = absolute_altitude if absolute_altitude is not None else relative_altitude

    radiometry = {
        "irradiance": dji("Irradiance"),
        "sunlight_sensor_status": dji("LS_status"),
        "raw_sunlight_sensor": dji("RawData"),
        "sensor_gain": dji("SensorGain"),
        "sensor_gain_adjustment": dji("SensorGainAdjustment"),
        "exposure_time": dji("ExposureTime"),
        "black_level": dji("BlackLevel", "BlackCurrent"),
        "vignetting_data": dji("VignettingData"),
        "dewarp_data": dji("DewarpData"),
        "calibrated_h_matrix": dji("CalibratedHMatrix"),
    }

    return {
        "capture_time": utc_at_exposure
        or _first(
            raw,
            "EXIF:DateTimeOriginal",
            "XMP:CreateDate",
        ),
        "camera": {
            "make": _first(raw, "EXIF:Make", "XMP:Make"),
            "model": _first(raw, "EXIF:Model", "XMP:Model"),
            "serial": camera_serial
            or _first(raw, "EXIF:SerialNumber", "XMP:SerialNumber"),
            "lens": _first(raw, "EXIF:LensModel", "XMP:Lens"),
        },
        "image": {
            "width": _first(raw, "File:ImageWidth", "EXIF:ExifImageWidth"),
            "height": _first(raw, "File:ImageHeight", "EXIF:ExifImageHeight"),
            "iso": _first(raw, "EXIF:ISO"),
            "f_number": _first(raw, "EXIF:FNumber"),
            "focal_length": _first(raw, "EXIF:FocalLength"),
            "exposure_time": _first(raw, "EXIF:ExposureTime"),
        },
        "gps": {
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude,
        },
        "dji": {
            "absolute_altitude": absolute_altitude,
            "relative_altitude": relative_altitude,
            "flight_yaw": dji("FlightYawDegree"),
            "flight_pitch": dji("FlightPitchDegree"),
            "flight_roll": dji("FlightRollDegree"),
            "gimbal_yaw": dji("GimbalYawDegree"),
            "gimbal_pitch": dji("GimbalPitchDegree"),
            "gimbal_roll": dji("GimbalRollDegree"),
            "rtk_flag": dji("RtkFlag", "RTKFlag"),
            "gps_status": dji("GpsStatus"),
            "capture_uuid": dji("CaptureUUID"),
            "image_source": dji("ImageSource"),
            "band_name": dji("BandName"),
            "band_frequency": dji("BandFreq"),
            "central_wavelength_nm": dji("CentralWavelength"),
            "sensor_index": dji("SensorIndex"),
            "camera_serial_number": camera_serial,
            "drone_serial_number": dji("DroneSerialNumber"),
            "drone_id": dji("DroneID"),
            "product_name": dji("ProductName", "AircraftType")
            or _first(raw, "MakerNotes:AircraftType"),
            "aircraft_type": dji("AircraftType")
            or _first(raw, "MakerNotes:AircraftType"),
            "radiometry": radiometry,
            "source_keys": source_keys,
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
    return normalize_metadata(payload[0])
