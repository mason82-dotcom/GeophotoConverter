from __future__ import annotations

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any


DATA_ROOT = Path(os.getenv("PDAL_DATA_ROOT", "/data")).resolve()
PORT = int(os.getenv("PDAL_QA_PORT", "8080"))
TIMEOUT_SECONDS = float(os.getenv("PDAL_QA_TIMEOUT_SECONDS", "120"))
MAX_REQUEST_BYTES = int(os.getenv("PDAL_QA_MAX_REQUEST_BYTES", "16384"))
ALLOWED_SUFFIXES = {".las", ".laz", ".ply"}
PINNED_PDAL_VERSION = "2.10.2"


class RequestError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _resolve_artifact(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise RequestError(400, "artifact_path must be a non-empty relative path")

    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise RequestError(400, "artifact_path must stay below /data")

    path = (DATA_ROOT / Path(*candidate.parts)).resolve()
    if path == DATA_ROOT or DATA_ROOT not in path.parents:
        raise RequestError(403, "artifact_path escapes /data")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise RequestError(422, "unsupported point-cloud format")
    if not path.is_file():
        raise RequestError(404, "point-cloud artifact not found")
    return path


def _pdal_version() -> str:
    try:
        completed = subprocess.run(
            ["pdal", "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RequestError(503, "PDAL runtime is unavailable") from exc
    return (completed.stdout or completed.stderr or "").strip()


def _run_json(args: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RequestError(504, "PDAL command timed out") from exc
    except OSError as exc:
        raise RequestError(503, "PDAL execution failed") from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        detail = stderr[-1000:] if stderr else "PDAL command failed"
        raise RequestError(422, detail)

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RequestError(502, "PDAL returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RequestError(502, "PDAL returned a non-object JSON payload")
    return payload


def qa_artifact(artifact_path: Any) -> dict[str, Any]:
    path = _resolve_artifact(artifact_path)
    version = _pdal_version()
    if PINNED_PDAL_VERSION not in version:
        raise RequestError(
            503,
            f"unexpected PDAL runtime: {version or 'unknown'}; expected {PINNED_PDAL_VERSION}",
        )

    summary = _run_json(["pdal", "info", "--summary", str(path)])
    stats = _run_json(
        [
            "pdal",
            "info",
            "--stats",
            "--dimensions=X,Y,Z,Classification",
            "--enumerate=Classification",
            str(path),
        ]
    )
    summary.setdefault("pdal_version", version)
    stats.setdefault("pdal_version", version)
    return {
        "artifact_path": path.relative_to(DATA_ROOT).as_posix(),
        "pdal_version": version,
        "summary": summary,
        "stats": stats,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "GeoPhotoPDALQA/1.0"

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc: RequestError) -> None:
        self._json(exc.status, {"error": exc.message})

    def do_GET(self) -> None:
        if self.path != "/health":
            self._json(404, {"error": "not found"})
            return
        try:
            version = _pdal_version()
            status = "ok" if PINNED_PDAL_VERSION in version else "degraded"
            self._json(
                200 if status == "ok" else 503,
                {
                    "status": status,
                    "pdal_version": version,
                    "expected_pdal_version": PINNED_PDAL_VERSION,
                },
            )
        except RequestError as exc:
            self._error(exc)

    def do_POST(self) -> None:
        if self.path != "/qa":
            self._json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "invalid content length"})
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._json(413, {"error": "request body size is invalid"})
            return

        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"error": "request must be a JSON object"})
            return

        try:
            self._json(200, qa_artifact(payload.get("artifact_path")))
        except RequestError as exc:
            self._error(exc)

    def log_message(self, format: str, *args: Any) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
