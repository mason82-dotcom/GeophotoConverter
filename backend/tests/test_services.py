from __future__ import annotations

from starlette.requests import Request

from app import services


def _request(host: str = "192.168.178.45:8088") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/services",
            "raw_path": b"/api/v1/services",
            "query_string": b"",
            "headers": [(b"host", host.encode())],
            "server": ("192.168.178.45", 8088),
            "client": ("192.168.178.10", 50000),
        }
    )


def test_external_services_derive_lan_launch_urls(monkeypatch):
    monkeypatch.setattr(services, "DRONEDB_PUBLIC_URL", "")
    monkeypatch.setattr(services, "DRONEDB_PUBLIC_PORT", 5000)
    monkeypatch.setattr(services, "OPENWEBUI_PUBLIC_URL", "")
    monkeypatch.setattr(services, "OPENWEBUI_PUBLIC_PORT", 3001)

    def fake_probe(base_url: str, health_path: str):
        return {
            "status": "online",
            "reachable": True,
            "health_status_code": 200,
            "error": None,
        }

    monkeypatch.setattr(services, "_probe_service", fake_probe)

    result = services.external_services(_request())
    assert result["dronedb"]["launch_url"] == "http://192.168.178.45:5000"
    assert result["open_webui"]["launch_url"] == "http://192.168.178.45:3001"
    assert result["dronedb"]["publish_endpoint"].endswith("/publish/dronedb")


def test_external_services_honor_configured_public_urls(monkeypatch):
    monkeypatch.setattr(services, "DRONEDB_PUBLIC_URL", "/dronedb/")
    monkeypatch.setattr(services, "OPENWEBUI_PUBLIC_URL", "/assistant/")
    monkeypatch.setattr(
        services,
        "_probe_service",
        lambda *_args: {
            "status": "offline",
            "reachable": False,
            "health_status_code": None,
            "error": "ConnectError",
        },
    )

    result = services.external_services(_request())
    assert result["dronedb"]["launch_url"] == "/dronedb/"
    assert result["open_webui"]["launch_url"] == "/assistant/"
    assert result["open_webui"]["status"] == "offline"
