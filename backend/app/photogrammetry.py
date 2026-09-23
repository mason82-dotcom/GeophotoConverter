from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any


FIELD_PRIORITIES: dict[str, tuple[str, ...]] = {
    "position.latitude_deg": ("fh2_media", "file_metadata"),
    "position.longitude_deg": ("fh2_media", "file_metadata"),
    "height.ellipsoid_m": ("fh2_media", "file_metadata"),
    "height.relative_m": ("fh2_media", "file_metadata"),
    "orientation.aircraft_yaw_deg": ("fh2_media", "file_metadata"),
    "orientation.aircraft_pitch_deg": ("fh2_media", "file_metadata"),
    "orientation.aircraft_roll_deg": ("fh2_media", "file_metadata"),
    "orientation.gimbal_yaw_deg": ("fh2_media", "file_metadata"),
    "orientation.gimbal_pitch_deg": ("fh2_media", "file_metadata"),
    "orientation.gimbal_roll_deg": ("fh2_media", "file_metadata"),
    "time.utc_at_exposure_ms": ("fh2_media", "file_metadata"),
    "rtk.fixed": ("fh2_media", "file_metadata"),
    "capture_uuid": ("fh2_media", "file_metadata"),
}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _latitude(value: Any) -> float | None:
    parsed = _finite_number(value)
    if parsed is None or not -90.0 <= parsed <= 90.0:
        return None
    return parsed


def _longitude(value: Any) -> float | None:
    parsed = _finite_number(value)
    if parsed is None or not -180.0 <= parsed <= 180.0:
        return None
    return parsed


def _angle(value: Any) -> float | None:
    parsed = _finite_number(value)
    if parsed is None:
        return None
    normalized = (parsed + 180.0) % 360.0 - 180.0
    return 0.0 if normalized == -0.0 else normalized


def _integer(value: Any) -> int | None:
    parsed = _finite_number(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _utc_millis(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = _finite_number(value)
        return int(round(parsed)) if parsed is not None else None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    if (
        len(text) >= 19
        and text[4:5] == ":"
        and text[7:8] == ":"
        and text[10:11] == " "
    ):
        text = f"{text[:4]}-{text[5:7]}-{text[8:]}"

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return int(round(parsed.timestamp() * 1000.0))


def _rtk_fixed_from_file(dji: dict[str, Any]) -> bool | None:
    explicit = dji.get("rtk_fixed")
    if isinstance(explicit, bool):
        return explicit

    code = _integer(dji.get("rtk_flag"))
    if code is None:
        return None
    return code == 50


def _fh2_parts(
    fh2_media: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fh2 = _mapping(fh2_media)
    asset = _mapping(fh2.get("asset"))
    capture = _mapping(asset.get("capture"))
    source_keys = _mapping(fh2.get("sourceKeys") or fh2.get("source_keys"))
    return capture, source_keys


def _source_key(source_keys: dict[str, Any], key: str) -> str | None:
    value = source_keys.get(key)
    return value if isinstance(value, str) and value else None


def _candidate(
    value: Any,
    *,
    source: str,
    path: str,
    source_key: str | None = None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    result: dict[str, Any] = {
        "value": value,
        "source": source,
        "path": path,
    }
    if source_key:
        result["source_key"] = source_key
    return result


def _different(left: Any, right: Any, tolerance: float | None) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left != right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if tolerance is None:
            return left != right
        return abs(float(left) - float(right)) > tolerance
    return left != right


def _select(
    field: str,
    candidates: list[dict[str, Any] | None],
    provenance: dict[str, dict[str, Any]],
    conflicts: list[dict[str, Any]],
    *,
    tolerance: float | None = None,
) -> Any:
    available = [candidate for candidate in candidates if candidate is not None]
    if not available:
        return None

    selected = available[0]
    provenance[field] = {
        key: value
        for key, value in selected.items()
        if key != "value"
    }

    for other in available[1:]:
        if not _different(selected["value"], other["value"], tolerance):
            continue
        conflict: dict[str, Any] = {
            "field": field,
            "kind": "value_mismatch",
            "selected": selected,
            "other": other,
        }
        if tolerance is not None:
            conflict["tolerance"] = tolerance
        conflicts.append(conflict)

    return selected["value"]


def fuse_photogrammetry_metadata(
    file_metadata: dict[str, Any] | None,
    fh2_media: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fuse normalized file metadata with optional FH2/DJI media metadata.

    The function is pure and never mutates its inputs. Generic GPS altitude is
    kept separate and is never inferred to be ellipsoid/absolute height.
    """

    file_data = _mapping(file_metadata)
    gps = _mapping(file_data.get("gps"))
    dji = _mapping(file_data.get("dji"))
    file_source_keys = _mapping(dji.get("source_keys"))
    fh2_capture, fh2_source_keys = _fh2_parts(fh2_media)
    fh2 = _mapping(fh2_media)

    provenance: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []

    latitude_deg = _select(
        "position.latitude_deg",
        [
            _candidate(
                _latitude(fh2_capture.get("latitudeDeg")),
                source="fh2_media",
                path="asset.capture.latitudeDeg",
                source_key=_source_key(fh2_source_keys, "GpsLatitude"),
            ),
            _candidate(
                _latitude(gps.get("latitude")),
                source="file_metadata",
                path="gps.latitude",
            ),
        ],
        provenance,
        conflicts,
        tolerance=1e-6,
    )
    longitude_deg = _select(
        "position.longitude_deg",
        [
            _candidate(
                _longitude(fh2_capture.get("longitudeDeg")),
                source="fh2_media",
                path="asset.capture.longitudeDeg",
                source_key=_source_key(fh2_source_keys, "GpsLongitude"),
            ),
            _candidate(
                _longitude(gps.get("longitude")),
                source="file_metadata",
                path="gps.longitude",
            ),
        ],
        provenance,
        conflicts,
        tolerance=1e-6,
    )
    ellipsoid_m = _select(
        "height.ellipsoid_m",
        [
            _candidate(
                _finite_number(fh2_capture.get("ellipsoidHeightM")),
                source="fh2_media",
                path="asset.capture.ellipsoidHeightM",
                source_key=_source_key(fh2_source_keys, "AbsoluteAltitude"),
            ),
            _candidate(
                _finite_number(dji.get("absolute_altitude")),
                source="file_metadata",
                path="dji.absolute_altitude",
                source_key=_source_key(file_source_keys, "AbsoluteAltitude"),
            ),
        ],
        provenance,
        conflicts,
        tolerance=0.05,
    )
    relative_m = _select(
        "height.relative_m",
        [
            _candidate(
                _finite_number(fh2_capture.get("relativeHeightM")),
                source="fh2_media",
                path="asset.capture.relativeHeightM",
                source_key=_source_key(fh2_source_keys, "RelativeAltitude"),
            ),
            _candidate(
                _finite_number(dji.get("relative_altitude")),
                source="file_metadata",
                path="dji.relative_altitude",
                source_key=_source_key(file_source_keys, "RelativeAltitude"),
            ),
        ],
        provenance,
        conflicts,
        tolerance=0.05,
    )

    gps_altitude_m = _finite_number(gps.get("altitude"))
    if gps_altitude_m is not None:
        provenance["height.gps_altitude_m"] = {
            "source": "file_metadata",
            "path": "gps.altitude",
        }

    orientation_fields = {
        "aircraft_yaw_deg": ("aircraftYawDeg", "flight_yaw", "FlightYawDegree"),
        "aircraft_pitch_deg": ("aircraftPitchDeg", "flight_pitch", "FlightPitchDegree"),
        "aircraft_roll_deg": ("aircraftRollDeg", "flight_roll", "FlightRollDegree"),
        "gimbal_yaw_deg": ("gimbalYawDeg", "gimbal_yaw", "GimbalYawDegree"),
        "gimbal_pitch_deg": ("gimbalPitchDeg", "gimbal_pitch", "GimbalPitchDegree"),
        "gimbal_roll_deg": ("gimbalRollDeg", "gimbal_roll", "GimbalRollDegree"),
    }
    orientation: dict[str, float | None] = {}
    for output_name, (fh2_name, file_name, source_name) in orientation_fields.items():
        field = f"orientation.{output_name}"
        orientation[output_name] = _select(
            field,
            [
                _candidate(
                    _angle(fh2_capture.get(fh2_name)),
                    source="fh2_media",
                    path=f"asset.capture.{fh2_name}",
                    source_key=_source_key(fh2_source_keys, source_name),
                ),
                _candidate(
                    _angle(dji.get(file_name)),
                    source="file_metadata",
                    path=f"dji.{file_name}",
                    source_key=_source_key(file_source_keys, source_name),
                ),
            ],
            provenance,
            conflicts,
            tolerance=0.1,
        )

    utc_at_exposure_ms = _select(
        "time.utc_at_exposure_ms",
        [
            _candidate(
                _utc_millis(fh2_capture.get("capturedAt")),
                source="fh2_media",
                path="asset.capture.capturedAt",
                source_key=_source_key(fh2_source_keys, "UTCAtExposure"),
            ),
            _candidate(
                _utc_millis(file_data.get("utc_at_exposure")),
                source="file_metadata",
                path="utc_at_exposure",
                source_key=_source_key(file_source_keys, "UTCAtExposure"),
            ),
        ],
        provenance,
        conflicts,
        tolerance=5.0,
    )

    capture_time = _text(file_data.get("capture_time"))
    if capture_time is not None:
        provenance["time.capture_time"] = {
            "source": "file_metadata",
            "path": "capture_time",
        }

    fh2_fixed = fh2_capture.get("rtkFixed")
    if not isinstance(fh2_fixed, bool):
        fh2_fixed = None
    rtk_fixed = _select(
        "rtk.fixed",
        [
            _candidate(
                fh2_fixed,
                source="fh2_media",
                path="asset.capture.rtkFixed",
                source_key=_source_key(fh2_source_keys, "RtkFlag"),
            ),
            _candidate(
                _rtk_fixed_from_file(dji),
                source="file_metadata",
                path="dji.rtk_fixed",
                source_key=_source_key(file_source_keys, "RtkFlag"),
            ),
        ],
        provenance,
        conflicts,
    )

    rtk_flag = _integer(dji.get("rtk_flag"))
    if rtk_flag is not None:
        provenance["rtk.raw_flag"] = {
            "source": "file_metadata",
            "path": "dji.rtk_flag",
            **(
                {"source_key": _source_key(file_source_keys, "RtkFlag")}
                if _source_key(file_source_keys, "RtkFlag")
                else {}
            ),
        }

    capture_uuid = _select(
        "capture_uuid",
        [
            _candidate(
                _text(fh2.get("captureUuid") or fh2.get("capture_uuid")),
                source="fh2_media",
                path="captureUuid",
                source_key=_source_key(fh2_source_keys, "CaptureUUID"),
            ),
            _candidate(
                _text(dji.get("capture_uuid")),
                source="file_metadata",
                path="dji.capture_uuid",
                source_key=_source_key(file_source_keys, "CaptureUUID"),
            ),
        ],
        provenance,
        conflicts,
    )

    return {
        "position": {
            "latitude_deg": latitude_deg,
            "longitude_deg": longitude_deg,
        },
        "height": {
            "ellipsoid_m": ellipsoid_m,
            "relative_m": relative_m,
            "gps_altitude_m": gps_altitude_m,
            "gps_altitude_semantics": (
                "generic_file_altitude" if gps_altitude_m is not None else None
            ),
        },
        "orientation": orientation,
        "time": {
            "utc_at_exposure_ms": utc_at_exposure_ms,
            "capture_time": capture_time,
        },
        "rtk": {
            "fixed": rtk_fixed,
            "raw_flag": rtk_flag,
        },
        "capture_uuid": capture_uuid,
        "provenance": provenance,
        "conflicts": conflicts,
    }
