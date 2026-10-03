from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

import app.previews as previews_module


def test_image_preview_returns_cached_webp(client):
    dataset = client.post(
        "/api/v1/datasets",
        json={"name": "Preview"},
    ).json()

    source = BytesIO()
    Image.new("RGB", (640, 480), (120, 80, 40)).save(
        source,
        format="JPEG",
        quality=90,
    )

    uploaded = client.post(
        f"/api/v1/datasets/{dataset['id']}/files",
        files=[
            (
                "files",
                ("DJI_9001.JPG", source.getvalue(), "image/jpeg"),
            )
        ],
    )
    assert uploaded.status_code == 200
    file_id = uploaded.json()["accepted"][0]["id"]

    response = client.get(
        f"/api/v1/datasets/{dataset['id']}/files/{file_id}/preview",
        params={"size": 128},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/webp")
    assert response.headers["etag"]

    with Image.open(BytesIO(response.content)) as preview:
        assert preview.format == "WEBP"
        assert max(preview.size) <= 128

    second = client.get(
        f"/api/v1/datasets/{dataset['id']}/files/{file_id}/preview",
        params={"size": 128},
    )
    assert second.status_code == 200
    assert second.content == response.content


def test_preview_rejects_unknown_file(client):
    dataset = client.post(
        "/api/v1/datasets",
        json={"name": "Preview Missing"},
    ).json()
    response = client.get(
        f"/api/v1/datasets/{dataset['id']}/files/not-found/preview"
    )
    assert response.status_code == 404


def test_dng_renderer_uses_configured_dcraw_binary(monkeypatch, tmp_path: Path):
    source = tmp_path / "capture.dng"
    source.write_bytes(b"dng")
    work = tmp_path / "work"
    work.mkdir()
    seen = {}

    class Result:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(command, **kwargs):
        seen["command"] = command
        target = Path(command[command.index("-Z") + 1])
        target.write_bytes(b"decoded")
        return Result()

    monkeypatch.setattr(
        previews_module,
        "DCRAW_BIN",
        r"C:\Tools\LibRaw\dcraw_emu.exe",
    )
    monkeypatch.setattr(previews_module.subprocess, "run", fake_run)

    rendered = previews_module._render_dng(source, work)

    assert seen["command"][0] == r"C:\Tools\LibRaw\dcraw_emu.exe"
    assert rendered.is_file()
