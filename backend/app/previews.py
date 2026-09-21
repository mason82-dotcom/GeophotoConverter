from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import CACHE_ROOT, DATASETS_ROOT
from .storage import store

router = APIRouter(prefix="/api/v1/datasets", tags=["previews"])


def _safe_source(dataset_id: str, stored_path: str) -> Path:
    root = (DATASETS_ROOT / dataset_id / "images").resolve()
    source = Path(stored_path).resolve()
    if root not in source.parents:
        raise HTTPException(status_code=403, detail="Invalid image path")
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Image file not found")
    return source


def _render_dng(source: Path, work_dir: Path) -> Path:
    target = work_dir / "decoded.tif"
    proc = subprocess.run(
        [
            "dcraw_emu",
            "-w",
            "-T",
            "-q",
            "3",
            "-Z",
            str(target),
            str(source),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0 or not target.is_file():
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"LibRaw preview decode failed: {detail}")
    return target


def _generate_preview(source: Path, target: Path, size: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(
            prefix=".preview-",
            dir=target.parent,
        ) as temp_name:
            open_path = source
            if source.suffix.lower() == ".dng":
                open_path = _render_dng(source, Path(temp_name))

            with Image.open(open_path) as image:
                rendered = ImageOps.exif_transpose(image)
                if rendered.mode not in {"RGB", "L"}:
                    rendered = rendered.convert("RGB")
                elif rendered.mode == "L":
                    rendered = rendered.convert("RGB")
                rendered.thumbnail(
                    (size, size),
                    Image.Resampling.LANCZOS,
                )

                tmp = target.with_name(f".{target.name}.{os.getpid()}.part")
                try:
                    rendered.save(
                        tmp,
                        format="WEBP",
                        quality=82,
                        method=4,
                    )
                    os.replace(tmp, target)
                finally:
                    tmp.unlink(missing_ok=True)
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status_code=415,
            detail="Image format cannot be decoded for preview",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Preview generation failed: {exc}",
        ) from exc


@router.get("/{dataset_id}/files/{file_id}/preview")
def file_preview(
    dataset_id: str,
    file_id: str,
    size: int = Query(default=1024, ge=128, le=2048),
) -> FileResponse:
    record = store.get_file(dataset_id, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Dataset image not found")

    source = _safe_source(dataset_id, record["stored_path"])
    cache_key = record.get("sha256") or record["id"]
    target = (
        CACHE_ROOT
        / "previews"
        / dataset_id
        / f"{cache_key}-{size}.webp"
    )

    if not target.is_file():
        _generate_preview(source, target, size)

    return FileResponse(
        target,
        media_type="image/webp",
        headers={
            "Cache-Control": "private, max-age=86400, immutable",
            "ETag": f'"{cache_key}-{size}"',
        },
    )
