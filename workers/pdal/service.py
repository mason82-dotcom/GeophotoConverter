from __future__ import annotations

import json
import os
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

DATA_ROOT = Path(os.getenv("GEOPHOTO_DATA_ROOT", "/data")).resolve()
PORT = int(os.getenv("GEOPHOTO_PDAL_PORT", "8090"))
TIMEOUT_SECONDS = max(
    5,
    int(os.getenv("GEOPHOTO_PDAL_TIMEOUT_SECONDS", "120")),
)
MAX_REQUEST_BYTES = 16 * 1024
ALLOWED_SUFFIXES = {".las", ".laz", ".ply"}


class ServiceError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _json_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: Mapping[str, Any],
) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _resolve_relative_path(value: Any) -> tuple[str, Path]:
    if not isinstance(value, str) or not value.strip():
        raise ServiceError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "relative_path_required",
            "relative_path muss ein nichtleerer String sein.",
        )

    raw = value.replace("\\", "/").strip()
    if raw.startswith("/"):
        raise ServiceError(
            HTTPStatus.FORBIDDEN,
            "invalid_relative_path",
            "Absolute Artefaktpfade sind nicht erlaubt.",
        )
    normalized = raw.strip("/")
    relative = PurePosixPath(normalized)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ServiceError(
            HTTPStatus.FORBIDDEN,
            "invalid_relative_path",
            "Ungültiger relativer Artefaktpfad.",
        )

    target = (DATA_ROOT / Path(*relative.parts)).resolve()
    if target != DATA_ROOT and DATA_ROOT not in target.parents:
        raise ServiceError(
            HTTPStatus.FORBIDDEN,
            "path_outside_data_root",
            "Artefaktpfad liegt außerhalb des Datenverzeichnisses.",
        )
    if not target.is_file():
        raise ServiceError(
            HTTPStatus.NOT_FOUND,
            "pointcloud_not_found",
            "Punktwolkenartefakt wurde nicht gefunden.",
        )
    if target.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ServiceError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "unsupported_pointcloud_format",
            f"Nicht unterstütztes Punktwolkenformat: {target.suffix.lower() or 'keins'}",
        )
    return relative.as_posix(), target


def _run_pdal_json(arguments: list[str]) -> dict[str, Any]:
    try:
        process = subprocess.run(
            ["pdal", *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ServiceError(
            HTTPStatus.GATEWAY_TIMEOUT,
            "pdal_timeout",
            f"PDAL überschritt das Zeitlimit von {TIMEOUT_SECONDS} Sekunden.",
        ) from exc
    except OSError as exc:
        raise ServiceError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "pdal_unavailable",
            "PDAL konnte nicht gestartet werden.",
        ) from exc

    if process.returncode != 0:
        stderr = (process.stderr or "").strip()
        raise ServiceError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "pdal_failed",
            stderr[-2000:] or f"PDAL beendete sich mit Code {process.returncode}.",
        )

    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ServiceError(
            HTTPStatus.BAD_GATEWAY,
            "pdal_invalid_json",
            "PDAL lieferte kein gültiges JSON.",
        ) from exc
    if not isinstance(payload, dict):
        raise ServiceError(
            HTTPStatus.BAD_GATEWAY,
            "pdal_invalid_payload",
            "PDAL lieferte kein JSON-Objekt.",
        )
    return payload


def _summary_dimensions(summary_payload: Mapping[str, Any]) -> list[str]:
    summary = summary_payload.get("summary")
    if not isinstance(summary, Mapping):
        return []
    raw = summary.get("dimensions")
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, list):
        return [str(value).strip() for value in raw if str(value).strip()]
    return []


def _qa(relative_path: Any) -> dict[str, Any]:
    relative, target = _resolve_relative_path(relative_path)

    summary = _run_pdal_json(["info", "--summary", str(target)])
    dimensions = _summary_dimensions(summary)
    by_lower = {name.lower(): name for name in dimensions}

    requested = [
        by_lower[name]
        for name in ("x", "y", "z")
        if name in by_lower
    ]
    classification = by_lower.get("classification")
    if classification is not None:
        requested.append(classification)

    stats: dict[str, Any]
    if requested:
        command = [
            "info",
            "--stats",
            f"--dimensions={','.join(requested)}",
        ]
        if classification is not None:
            command.append(f"--enumerate={classification}")
        command.append(str(target))
        stats = _run_pdal_json(command)
    else:
        stats = {"stats": {"statistic": []}}

    return {
        "relative_path": relative,
        "summary": summary,
        "stats": stats,
        "service": {
            "pdal_expected_version": "2.10.2",
            "timeout_seconds": TIMEOUT_SECONDS,
        },
    }


def _pdal_version() -> str:
    try:
        process = subprocess.run(
            ["pdal", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    output = ((process.stdout or "") + " " + (process.stderr or "")).strip()
    return output if process.returncode == 0 and output else "unavailable"


PDAL_VERSION_TEXT = _pdal_version()


class Handler(BaseHTTPRequestHandler):
    server_version = "GeoPhoto-PDAL/1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(
            f"{self.address_string()} - {fmt % args}",
            flush=True,
        )

    def do_GET(self) -> None:
        if self.path != "/health":
            _json_response(
                self,
                HTTPStatus.NOT_FOUND,
                {"status": "not_found"},
            )
            return
        healthy = "2.10.2" in PDAL_VERSION_TEXT
        _json_response(
            self,
            HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE,
            {
                "status": "ok" if healthy else "degraded",
                "pdal": PDAL_VERSION_TEXT,
                "expected_version": "2.10.2",
                "data_root": str(DATA_ROOT),
            },
        )

    def do_POST(self) -> None:
        if self.path != "/qa":
            _json_response(
                self,
                HTTPStatus.NOT_FOUND,
                {"status": "not_found"},
            )
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_REQUEST_BYTES:
            _json_response(
                self,
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {
                    "error": "invalid_request_size",
                    "detail": "Ungültige Request-Größe.",
                },
            )
            return

        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request must be an object")
            result = _qa(payload.get("relative_path"))
        except ServiceError as exc:
            _json_response(
                self,
                exc.status,
                {"error": exc.code, "detail": exc.message},
            )
            return
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            _json_response(
                self,
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "invalid_json",
                    "detail": "Request muss ein gültiges JSON-Objekt sein.",
                },
            )
            return
        except Exception as exc:
            _json_response(
                self,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": "internal_error",
                    "detail": type(exc).__name__,
                },
            )
            return

        _json_response(self, HTTPStatus.OK, result)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(
        f"GeoPhoto PDAL QA service listening on 0.0.0.0:{PORT}; "
        f"PDAL={PDAL_VERSION_TEXT}",
        flush=True,
    )
    server.serve_forever()
