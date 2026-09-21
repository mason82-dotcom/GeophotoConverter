from __future__ import annotations

from typing import Any

import httpx
from fastapi import Request

from .config import (
    DRONEDB_BASE_URL,
    DRONEDB_PUBLIC_PORT,
    DRONEDB_PUBLIC_URL,
    OPENWEBUI_INTERNAL_URL,
    OPENWEBUI_PUBLIC_PORT,
    OPENWEBUI_PUBLIC_URL,
)


def _probe_service(base_url: str, health_path: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{health_path.lstrip('/')}"
    try:
        response = httpx.get(
            url,
            timeout=httpx.Timeout(0.75, connect=0.5),
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        return {
            "status": "offline",
            "reachable": False,
            "health_status_code": None,
            "error": type(exc).__name__,
        }

    code = response.status_code
    if 200 <= code < 400 or code in {401, 403}:
        status = "online"
    elif code < 500:
        status = "reachable"
    else:
        status = "degraded"

    return {
        "status": status,
        "reachable": True,
        "health_status_code": code,
        "error": None,
    }


def _fallback_launch_url(request: Request, public_port: int) -> str | None:
    hostname = request.url.hostname
    if not hostname:
        return None
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    return f"http://{hostname}:{public_port}"


def _launch_url(
    request: Request,
    configured_public_url: str,
    public_port: int,
) -> str | None:
    if configured_public_url:
        return configured_public_url
    return _fallback_launch_url(request, public_port)


def external_services(request: Request) -> dict[str, dict[str, Any]]:
    dronedb = _probe_service(DRONEDB_BASE_URL, "/quickhealth")
    dronedb.update(
        {
            "profile": "dronedb",
            "public_port": DRONEDB_PUBLIC_PORT,
            "launch_url": _launch_url(
                request,
                DRONEDB_PUBLIC_URL,
                DRONEDB_PUBLIC_PORT,
            ),
            "publish_endpoint": "/api/v1/jobs/{job_id}/publish/dronedb",
        }
    )

    open_webui = _probe_service(OPENWEBUI_INTERNAL_URL, "/health")
    open_webui.update(
        {
            "profile": "ai",
            "public_port": OPENWEBUI_PUBLIC_PORT,
            "launch_url": _launch_url(
                request,
                OPENWEBUI_PUBLIC_URL,
                OPENWEBUI_PUBLIC_PORT,
            ),
            "role": "optional_ai_assistant",
        }
    )

    return {
        "dronedb": dronedb,
        "open_webui": open_webui,
    }
