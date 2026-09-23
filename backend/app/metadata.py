from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


_RTK_STATUS = {
    0: "none",
    16: "single",
    34: "float",
    50: "fixed",
    52: "gnss_plus",
}


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in ("", None):
            return data[key]
    return None


def _dji_first(data: dict[str, Any], *tags: str) -> Any:
    keys: list[str] = []
    for tag in tags:
        keys.extend((f"XMP-drone-dji:{tag}", f"XMP:{tag}"))
    return _first(data, *keys)


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
