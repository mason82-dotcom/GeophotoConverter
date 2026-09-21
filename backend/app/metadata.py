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
        raise ValueError("ExifTool returned no metadata")
    raw = payload[0]

    latitude = _first(raw, "GPS:GPSLatitude", "EXIF:GPSLatitude", "Composite:GPSLatitude")
    longitude = _first(raw, "GPS:GPSLongitude", "EXIF:GPSLongitude", "Composite:GPSLongitude")
    altitude = _first(raw, "GPS:GPSAltitude", "XMP:AbsoluteAltitude", "XMP:RelativeAltitude")

    return {
        "capture_time": _first(
            raw,
            "EXIF:DateTimeOriginal",
            "XMP:CreateDate",
            "XMP:UTCAtExposure",
        ),
        "camera": {
            "make": _first(raw, "EXIF:Make", "XMP:Make"),
            "model": _first(raw, "EXIF:Model", "XMP:Model"),
            "serial": _first(raw, "EXIF:SerialNumber", "XMP:SerialNumber"),
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
            "absolute_altitude": _first(raw, "XMP:AbsoluteAltitude"),
            "relative_altitude": _first(raw, "XMP:RelativeAltitude"),
            "flight_yaw": _first(raw, "XMP:FlightYawDegree"),
            "flight_pitch": _first(raw, "XMP:FlightPitchDegree"),
            "flight_roll": _first(raw, "XMP:FlightRollDegree"),
            "gimbal_yaw": _first(raw, "XMP:GimbalYawDegree"),
            "gimbal_pitch": _first(raw, "XMP:GimbalPitchDegree"),
            "gimbal_roll": _first(raw, "XMP:GimbalRollDegree"),
            "rtk_flag": _first(raw, "XMP:RtkFlag", "XMP:RTKFlag"),
            "product_name": _first(
                raw,
                "XMP:ProductName",
                "XMP:AircraftType",
                "MakerNotes:AircraftType",
            ),
            "aircraft_type": _first(
                raw,
                "XMP:AircraftType",
                "MakerNotes:AircraftType",
            ),
        },
    }
