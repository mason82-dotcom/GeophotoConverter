from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import uuid
from pathlib import Path
from typing import Any, Iterator

import laspy
import httpx
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import (
    DATA_ROOT,
    PDAL_SERVICE_URL,
    PDAL_TIMEOUT_SECONDS,
    POINTCLOUD_CACHE_ROOT,
)
from .photogrammetry_pdal_pipeline import (
    build_reprojection_contract,
    reprojection_provenance,
)
from .photogrammetry_pointcloud import parse_pdal_stats, parse_pdal_summary
from .queue import enqueue, ping as redis_ping
from .storage import store

router = APIRouter(prefix="/api/v1", tags=["pointcloud"])

_POINTCLOUD_SUFFIXES = {".las", ".laz", ".ply"}
_PDAL_PROCESSING_ENGINE = "pdal-processing"
_MAX_PLY_HEADER_BYTES = 1024 * 1024
_PLY_TYPES = {
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
    "short": "i2",
    "int16": "i2",
    "ushort": "u2",
    "uint16": "u2",
    "int": "i4",
    "int32": "i4",
    "uint": "u4",
    "uint32": "u4",
    "float": "f4",
    "float32": "f4",
    "double": "f8",
    "float64": "f8",
}


class PointcloudReprojectRequest(BaseModel):
    target_crs: str = Field(min_length=1, max_length=8192)
    coordinate_scale_m: float = Field(default=0.001, ge=1e-6, le=0.1)


_PREVIEW_DTYPE = np.dtype(
    [
        ("x", "<f4"),
        ("y", "<f4"),
        ("z", "<f4"),
        ("r", "u1"),
        ("g", "u1"),
        ("b", "u1"),
        ("a", "u1"),
    ],
    align=False,
)


def _is_pointcloud_artifact(artifact: dict[str, Any]) -> bool:
    name = str(artifact.get("name") or "").lower()
    kind = str(artifact.get("type") or "").lower()
    suffix = Path(name).suffix.lower()
    if suffix not in _POINTCLOUD_SUFFIXES:
        return False
    if "gsplat" in kind or "gaussian" in kind:
        return False
    if suffix in {".las", ".laz"}:
        return True
    return "point_cloud" in kind or kind in {"pointcloud", "ply"}


def _job_or_404(job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden")
    return job


def _artifact_or_404(
    job_id: str,
    artifact_index: int,
) -> tuple[dict[str, Any], Path]:
    job = _job_or_404(job_id)
    artifacts = job.get("artifacts") or []
    if artifact_index < 0 or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="Artefakt nicht gefunden")
    artifact = artifacts[artifact_index]
    if not _is_pointcloud_artifact(artifact):
        raise HTTPException(
            status_code=422,
            detail="Artefakt ist keine unterstützte klassische Punktwolke.",
        )

    relative = artifact.get("relative_path")
    if not relative:
        raise HTTPException(status_code=404, detail="Artefaktpfad ist nicht verfügbar")
    path = (DATA_ROOT / str(relative)).resolve()
    root = DATA_ROOT.resolve()
    if path != root and root not in path.parents:
        raise HTTPException(status_code=403, detail="Ungültiger Artefaktpfad")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Punktwolkendatei nicht gefunden")
    return artifact, path




def _source_crs_input(path: Path, metadata: dict[str, Any]) -> str:
    info = metadata.get("crs")
    if isinstance(info, dict):
        identifier = info.get("identifier")
        if isinstance(identifier, str) and identifier.strip():
            return identifier.strip()
        authority = info.get("authority")
        code = info.get("code")
        if authority and code:
            return f"{authority}:{code}"
        wkt = info.get("wkt")
        if isinstance(wkt, str) and wkt.strip():
            return wkt.strip()

    # Existing metadata caches may predate identifier/WKT fields. Re-read only
    # the LAS/LAZ header rather than accepting a user-supplied source CRS.
    with laspy.open(path) as reader:
        crs = reader.header.parse_crs()
    if crs is None:
        raise ValueError("Punktwolke enthält kein explizites Source-CRS.")
    authority = crs.to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else crs.to_wkt()


def _source_signature(path: Path) -> str:
    stat = path.stat()
    raw = f"{path}:{stat.st_size}:{stat.st_mtime_ns}".encode()
    return hashlib.sha256(raw).hexdigest()


def _cache_dir(path: Path) -> Path:
    directory = POINTCLOUD_CACHE_ROOT / _source_signature(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        temp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _bounds(minimum: np.ndarray, maximum: np.ndarray) -> dict[str, list[float]]:
    center = (minimum + maximum) / 2.0
    extent = maximum - minimum
    return {
        "min": [float(value) for value in minimum],
        "max": [float(value) for value in maximum],
        "center": [float(value) for value in center],
        "extent": [float(value) for value in extent],
    }


def _dimension_names(values: Any) -> list[str]:
    return [str(value) for value in values]


def _inspect_las(path: Path) -> dict[str, Any]:
    with laspy.open(path) as reader:
        header = reader.header
        dimensions = _dimension_names(header.point_format.dimension_names)
        names = {name.lower() for name in dimensions}
        minimum = np.asarray(header.mins, dtype=np.float64)
        maximum = np.asarray(header.maxs, dtype=np.float64)
        if not np.all(np.isfinite(minimum)) or not np.all(np.isfinite(maximum)):
            raise ValueError(
                "LAS/LAZ enthält ungültige oder nicht endliche Bounds."
            )

        crs_info: dict[str, Any] | None = None
        crs = header.parse_crs()
        if crs is not None:
            authority = crs.to_authority()
            identifier = (
                f"{authority[0]}:{authority[1]}"
                if authority
                else None
            )
            crs_info = {
                "name": crs.name,
                "epsg": crs.to_epsg(),
                "authority": authority[0] if authority else None,
                "code": authority[1] if authority else None,
                "identifier": identifier,
                "wkt": crs.to_wkt(),
                "projected": bool(crs.is_projected),
                "geographic": bool(crs.is_geographic),
            }

        return {
            "format": path.suffix.lower().lstrip("/."),
            "point_count": int(header.point_count),
            "has_rgb": {"red", "green", "blue"}.issubset(names),
            "dimensions": dimensions,
            "bounds": _bounds(minimum, maximum),
            "source_size_bytes": path.stat().st_size,
            "las_version": str(header.version),
            "point_format": int(header.point_format.id),
            "scales": [float(value) for value in header.scales],
            "offsets": [float(value) for value in header.offsets],
            "crs": crs_info,
        }


def _read_ply_header(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        first = handle.readline().decode("ascii", errors="strict").strip()
        if first != "ply":
            raise ValueError("Ungültiger PLY-Header.")

        fmt: str | None = None
        elements: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        header_bytes = len(first) + 1
        while True:
            raw = handle.readline()
            if not raw:
                raise ValueError("PLY-Header endet unerwartet.")
            header_bytes += len(raw)
            if header_bytes > _MAX_PLY_HEADER_BYTES:
                raise ValueError(
                    "PLY-Header überschreitet das zulässige Limit von 1 MiB."
                )
            line = raw.decode("ascii", errors="strict").strip()
            if not line or line.startswith("comment") or line.startswith("obj_info"):
                continue
            parts = line.split()
            if parts[0] == "format" and len(parts) >= 2:
                fmt = parts[1]
            elif parts[0] == "element" and len(parts) == 3:
                count = int(parts[2])
                if count < 0:
                    raise ValueError("PLY-Elementanzahl darf nicht negativ sein.")
                current = {
                    "name": parts[1],
                    "count": count,
                    "properties": [],
                }
                elements.append(current)
            elif parts[0] == "property" and current is not None:
                if len(parts) >= 2 and parts[1] == "list":
                    current["properties"].append(
                        {"name": parts[-1], "list": True}
                    )
                elif len(parts) == 3:
                    current["properties"].append(
                        {"name": parts[2], "type": parts[1], "list": False}
                    )
            elif parts[0] == "end_header":
                break

        if fmt not in {"ascii", "binary_little_endian", "binary_big_endian"}:
            raise ValueError(f"Nicht unterstütztes PLY-Format: {fmt}")
        vertex_index = next(
            (index for index, item in enumerate(elements) if item["name"] == "vertex"),
            None,
        )
        if vertex_index is None:
            raise ValueError("PLY enthält kein vertex-Element.")
        if vertex_index != 0:
            raise ValueError(
                "PLY mit Elementen vor dem vertex-Block wird nicht unterstützt."
            )
        vertex = elements[vertex_index]
        if any(prop.get("list") for prop in vertex["properties"]):
            raise ValueError("Listen-Eigenschaften im PLY-vertex-Block werden nicht unterstützt.")

        names = [prop["name"] for prop in vertex["properties"]]
        for required in ("x", "y", "z"):
            if required not in names:
                raise ValueError(f"PLY-vertex-Block enthält kein {required}.")
        for prop in vertex["properties"]:
            if prop["type"] not in _PLY_TYPES:
                raise ValueError(f"Nicht unterstützter PLY-Datentyp: {prop['type']}")

        return {
            "format": fmt,
            "elements": elements,
            "vertex": vertex,
            "data_offset": handle.tell(),
        }


def _ply_color_names(names: set[str]) -> tuple[str, str, str] | None:
    if {"red", "green", "blue"}.issubset(names):
        return ("red", "green", "blue")
    if {"r", "g", "b"}.issubset(names):
        return ("r", "g", "b")
    return None


def _to_u8(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values)
    if np.issubdtype(array.dtype, np.floating):
        finite = np.nan_to_num(array.astype(np.float64), nan=0.0)
        if finite.size and float(np.max(finite)) <= 1.0:
            finite *= 255.0
        return np.clip(finite, 0.0, 255.0).astype(np.uint8)
    if np.issubdtype(array.dtype, np.integer) and array.dtype.itemsize > 1:
        maximum = np.iinfo(array.dtype).max
        return np.clip(
            np.rint(array.astype(np.float64) * (255.0 / maximum)),
            0,
            255,
        ).astype(np.uint8)
    return np.clip(array, 0, 255).astype(np.uint8)


def _binary_ply_array(path: Path, header: dict[str, Any]) -> np.memmap:
    endian = "<" if header["format"] == "binary_little_endian" else ">"
    fields = [
        (prop["name"], endian + _PLY_TYPES[prop["type"]])
        for prop in header["vertex"]["properties"]
    ]
    dtype = np.dtype(fields, align=False)
    return np.memmap(
        path,
        dtype=dtype,
        mode="r",
        offset=int(header["data_offset"]),
        shape=(int(header["vertex"]["count"]),),
    )


def _inspect_ply(path: Path) -> dict[str, Any]:
    header = _read_ply_header(path)
    properties = [prop["name"] for prop in header["vertex"]["properties"]]
    names = set(properties)
    point_count = int(header["vertex"]["count"])

    if point_count == 0:
        minimum = maximum = np.zeros(3, dtype=np.float64)
    elif header["format"].startswith("binary_"):
        vertices = _binary_ply_array(path, header)
        minimum = np.asarray(
            [
                np.min(vertices["x"]),
                np.min(vertices["y"]),
                np.min(vertices["z"]),
            ],
            dtype=np.float64,
        )
        maximum = np.asarray(
            [
                np.max(vertices["x"]),
                np.max(vertices["y"]),
                np.max(vertices["z"]),
            ],
            dtype=np.float64,
        )
    else:
        indices = {name: index for index, name in enumerate(properties)}
        minimum = np.full(3, np.inf, dtype=np.float64)
        maximum = np.full(3, -np.inf, dtype=np.float64)
        with path.open("rb") as handle:
            handle.seek(int(header["data_offset"]))
            for _ in range(point_count):
                raw = handle.readline()
                if not raw:
                    raise ValueError("PLY-vertex-Daten enden unerwartet.")
                parts = raw.decode("ascii", errors="strict").split()
                required_index = max(
                    indices["x"],
                    indices["y"],
                    indices["z"],
                )
                if len(parts) <= required_index:
                    raise ValueError(
                        "PLY-vertex-Zeile enthält zu wenige Werte."
                    )
                point = np.asarray(
                    [
                        float(parts[indices["x"]]),
                        float(parts[indices["y"]]),
                        float(parts[indices["z"]]),
                    ],
                    dtype=np.float64,
                )
                if not np.all(np.isfinite(point)):
                    raise ValueError(
                        "PLY enthält ungültige oder nicht endliche Koordinaten."
                    )
                minimum = np.minimum(minimum, point)
                maximum = np.maximum(maximum, point)

    return {
        "format": "ply",
        "ply_encoding": header["format"],
        "point_count": point_count,
        "has_rgb": _ply_color_names(names) is not None,
        "dimensions": properties,
        "bounds": _bounds(minimum, maximum),
        "source_size_bytes": path.stat().st_size,
    }


def inspect_pointcloud(path: Path) -> dict[str, Any]:
    cache = _cache_dir(path) / "metadata.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache.unlink(missing_ok=True)

    suffix = path.suffix.lower()
    if suffix in {".las", ".laz"}:
        metadata = _inspect_las(path)
    elif suffix == ".ply":
        metadata = _inspect_ply(path)
    else:
        raise ValueError(f"Nicht unterstütztes Punktwolkenformat: {suffix}")

    _atomic_json(cache, metadata)
    return metadata


def _sample_las(path: Path, max_points: int) -> tuple[np.ndarray, np.ndarray | None]:
    with laspy.open(path) as reader:
        total = int(reader.header.point_count)
        if total <= 0:
            return np.empty((0, 3), dtype=np.float64), None
        step = max(1, math.ceil(total / max_points))
        names = {str(value).lower() for value in reader.header.point_format.dimension_names}
        has_rgb = {"red", "green", "blue"}.issubset(names)
        positions: list[np.ndarray] = []
        colors: list[np.ndarray] = []
        global_offset = 0
        selected_total = 0

        for points in reader.chunk_iterator(500_000):
            count = len(points)
            local = np.arange(count, dtype=np.int64)
            mask = ((local + global_offset) % step) == 0
            selected = np.flatnonzero(mask)
            remaining = max_points - selected_total
            if remaining <= 0:
                break
            selected = selected[:remaining]
            if selected.size:
                positions.append(
                    np.column_stack(
                        (
                            np.asarray(points.x)[selected],
                            np.asarray(points.y)[selected],
                            np.asarray(points.z)[selected],
                        )
                    ).astype(np.float64, copy=False)
                )
                if has_rgb:
                    colors.append(
                        np.column_stack(
                            (
                                _to_u8(np.asarray(points.red)[selected]),
                                _to_u8(np.asarray(points.green)[selected]),
                                _to_u8(np.asarray(points.blue)[selected]),
                            )
                        )
                    )
                selected_total += int(selected.size)
            global_offset += count

        position_array = (
            np.concatenate(positions, axis=0)
            if positions
            else np.empty((0, 3), dtype=np.float64)
        )
        color_array = np.concatenate(colors, axis=0) if colors else None
        return position_array, color_array


def _sample_ascii_ply(
    path: Path,
    header: dict[str, Any],
    max_points: int,
) -> tuple[np.ndarray, np.ndarray | None]:
    properties = [prop["name"] for prop in header["vertex"]["properties"]]
    indices = {name: index for index, name in enumerate(properties)}
    color_names = _ply_color_names(set(properties))
    total = int(header["vertex"]["count"])
    step = max(1, math.ceil(total / max_points)) if total else 1
    positions: list[list[float]] = []
    colors: list[list[float]] = []

    with path.open("rb") as handle:
        handle.seek(int(header["data_offset"]))
        for index in range(total):
            raw = handle.readline()
            if not raw:
                raise ValueError("PLY-vertex-Daten enden unerwartet.")
            if index % step != 0 or len(positions) >= max_points:
                continue
            parts = raw.decode("ascii", errors="strict").split()
            required_names = ["x", "y", "z"]
            if color_names:
                required_names.extend(color_names)
            required_index = max(indices[name] for name in required_names)
            if len(parts) <= required_index:
                raise ValueError(
                    "PLY-vertex-Zeile enthält zu wenige Werte."
                )
            point = [
                float(parts[indices["x"]]),
                float(parts[indices["y"]]),
                float(parts[indices["z"]]),
            ]
            if not all(math.isfinite(value) for value in point):
                raise ValueError(
                    "PLY enthält ungültige oder nicht endliche Koordinaten."
                )
            positions.append(point)
            if color_names:
                colors.append(
                    [
                        float(parts[indices[color_names[0]]]),
                        float(parts[indices[color_names[1]]]),
                        float(parts[indices[color_names[2]]]),
                    ]
                )

    pos = np.asarray(positions, dtype=np.float64).reshape((-1, 3))
    color = _to_u8(np.asarray(colors)).reshape((-1, 3)) if colors else None
    return pos, color


def _sample_binary_ply(
    path: Path,
    header: dict[str, Any],
    max_points: int,
) -> tuple[np.ndarray, np.ndarray | None]:
    vertices = _binary_ply_array(path, header)
    total = len(vertices)
    step = max(1, math.ceil(total / max_points)) if total else 1
    selected = vertices[::step][:max_points]
    positions = np.column_stack(
        (selected["x"], selected["y"], selected["z"])
    ).astype(np.float64, copy=False)
    names = set(selected.dtype.names or ())
    color_names = _ply_color_names(names)
    if not color_names:
        return positions, None
    colors = np.column_stack(
        (
            _to_u8(selected[color_names[0]]),
            _to_u8(selected[color_names[1]]),
            _to_u8(selected[color_names[2]]),
        )
    )
    return positions, colors


def _sample_ply(path: Path, max_points: int) -> tuple[np.ndarray, np.ndarray | None]:
    header = _read_ply_header(path)
    if header["format"] == "ascii":
        return _sample_ascii_ply(path, header, max_points)
    return _sample_binary_ply(path, header, max_points)


def _preview_bytes(
    path: Path,
    metadata: dict[str, Any],
    max_points: int,
) -> tuple[Path, int]:
    cache_dir = _cache_dir(path)
    target = cache_dir / f"preview-{max_points}.bin"
    info_path = cache_dir / f"preview-{max_points}.json"
    if target.is_file() and info_path.is_file():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
            return target, int(info["point_count"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            target.unlink(missing_ok=True)
            info_path.unlink(missing_ok=True)

    if path.suffix.lower() in {".las", ".laz"}:
        positions, colors = _sample_las(path, max_points)
    else:
        positions, colors = _sample_ply(path, max_points)

    center = np.asarray(metadata["bounds"]["center"], dtype=np.float64)
    relative = (positions - center).astype(np.float32)
    preview = np.empty(len(relative), dtype=_PREVIEW_DTYPE)
    if len(relative):
        preview["x"] = relative[:, 0]
        preview["y"] = relative[:, 1]
        preview["z"] = relative[:, 2]
    if colors is not None and len(colors) == len(relative):
        preview["r"] = colors[:, 0]
        preview["g"] = colors[:, 1]
        preview["b"] = colors[:, 2]
    else:
        preview["r"] = 255
        preview["g"] = 255
        preview["b"] = 255
    preview["a"] = 255

    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
    try:
        temp.write_bytes(preview.tobytes(order="C"))
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    _atomic_json(info_path, {"point_count": int(len(preview))})
    return target, int(len(preview))


@router.get("/jobs/{job_id}/pointclouds")
def list_job_pointclouds(job_id: str) -> dict[str, Any]:
    job = _job_or_404(job_id)
    pointclouds = []
    for index, artifact in enumerate(job.get("artifacts") or []):
        if not _is_pointcloud_artifact(artifact):
            continue
        pointclouds.append(
            {
                "artifact_index": index,
                "name": artifact.get("name"),
                "type": artifact.get("type"),
                "size_bytes": artifact.get("size_bytes"),
                "metadata_url": (
                    f"/api/v1/jobs/{job_id}/pointclouds/{index}"
                ),
                "preview_url": (
                    f"/api/v1/jobs/{job_id}/pointclouds/{index}/preview"
                ),
                "qa_url": (
                    f"/api/v1/jobs/{job_id}/pointclouds/{index}/qa"
                ),
                "reproject_url": (
                    f"/api/v1/jobs/{job_id}/pointclouds/{index}/reproject"
                ),
                "download_url": f"/api/v1/jobs/{job_id}/artifacts/{index}",
            }
        )
    return {"job_id": job_id, "pointclouds": pointclouds}


@router.get("/jobs/{job_id}/pointclouds/{artifact_index}")
def pointcloud_metadata(job_id: str, artifact_index: int) -> dict[str, Any]:
    artifact, path = _artifact_or_404(job_id, artifact_index)
    try:
        metadata = inspect_pointcloud(path)
    except (OSError, ValueError, laspy.errors.LaspyException) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Punktwolke konnte nicht gelesen werden: {exc}",
        ) from exc

    return {
        "job_id": job_id,
        "artifact_index": artifact_index,
        "name": artifact.get("name") or path.name,
        "type": artifact.get("type"),
        **metadata,
        "preview_url": (
            f"/api/v1/jobs/{job_id}/pointclouds/{artifact_index}/preview"
        ),
        "qa_url": (
            f"/api/v1/jobs/{job_id}/pointclouds/{artifact_index}/qa"
        ),
        "reproject_url": (
            f"/api/v1/jobs/{job_id}/pointclouds/{artifact_index}/reproject"
        ),
        "download_url": f"/api/v1/jobs/{job_id}/artifacts/{artifact_index}",
    }


@router.post(
    "/jobs/{job_id}/pointclouds/{artifact_index}/reproject",
    status_code=201,
)
def reproject_pointcloud(
    job_id: str,
    artifact_index: int,
    body: PointcloudReprojectRequest,
) -> dict[str, Any]:
    source_job = _job_or_404(job_id)
    artifact, path = _artifact_or_404(job_id, artifact_index)
    if path.suffix.lower() not in {".las", ".laz"}:
        raise HTTPException(
            status_code=422,
            detail="Reprojection unterstützt in B1 ausschließlich LAS/LAZ/COPC-LAZ.",
        )

    try:
        metadata = inspect_pointcloud(path)
        source_crs = _source_crs_input(path, metadata)
    except (OSError, ValueError, laspy.errors.LaspyException) as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Source-CRS ist nicht belastbar verfügbar: {exc}",
        ) from exc

    if not redis_ping():
        raise HTTPException(
            status_code=503,
            detail="Pointcloud-Processing-Warteschlange ist nicht verfügbar.",
        )

    processing_job_id = store.new_id()
    source_relative = str(artifact.get("relative_path") or "")
    output_relative = (
        f"jobs/{processing_job_id}/derived/reprojected.laz"
    )
    try:
        contract = build_reprojection_contract(
            source_relative_path=source_relative,
            output_relative_path=output_relative,
            source_crs=source_crs,
            target_crs=body.target_crs,
            coordinate_scale_m=body.coordinate_scale_m,
        )
        provenance = reprojection_provenance(
            contract,
            source_job_id=job_id,
            source_artifact_index=artifact_index,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    options = {
        "operation": "horizontal_reprojection",
        "source_job_id": job_id,
        "source_artifact_index": artifact_index,
        "contract": contract,
        "provenance": provenance,
    }
    processing_job = store.create_job(
        source_job["dataset_id"],
        _PDAL_PROCESSING_ENGINE,
        "derived",
        "pointcloud_reprojection",
        options,
        job_id=processing_job_id,
    )
    enqueue(
        _PDAL_PROCESSING_ENGINE,
        {
            "job_id": processing_job_id,
            "dataset_id": source_job["dataset_id"],
            "engine": _PDAL_PROCESSING_ENGINE,
            "profile": "derived",
            "workflow": "pointcloud_reprojection",
            "options": options,
        },
    )
    return processing_job





@router.get("/jobs/{job_id}/pointclouds/{artifact_index}/qa")
def pointcloud_qa(job_id: str, artifact_index: int) -> dict[str, Any]:
    artifact, _ = _artifact_or_404(job_id, artifact_index)
    relative_path = artifact.get("relative_path")
    if not relative_path:
        raise HTTPException(status_code=404, detail="Artefaktpfad ist nicht verfügbar")

    try:
        response = httpx.post(
            f"{PDAL_SERVICE_URL}/qa",
            json={"relative_path": str(relative_path)},
            timeout=httpx.Timeout(float(PDAL_TIMEOUT_SECONDS + 10), connect=2.0),
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="PDAL-QA hat das Zeitlimit überschritten.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="PDAL-QA-Service ist nicht verfügbar.",
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="PDAL-QA-Service lieferte ungültiges JSON.",
        ) from exc

    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if response.status_code == 504:
            status = 504
        elif response.status_code in {404, 422}:
            status = 422
        else:
            status = 502
        raise HTTPException(
            status_code=status,
            detail=detail or "PDAL-QA fehlgeschlagen.",
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502,
            detail="PDAL-QA-Service lieferte kein JSON-Objekt.",
        )

    raw_summary = payload.get("summary")
    raw_stats = payload.get("stats")
    if not isinstance(raw_summary, dict) or not isinstance(raw_stats, dict):
        raise HTTPException(
            status_code=502,
            detail="PDAL-QA-Service lieferte unvollständige QA-Daten.",
        )

    return {
        "job_id": job_id,
        "artifact_index": artifact_index,
        "name": artifact.get("name"),
        "type": artifact.get("type"),
        "summary": parse_pdal_summary(raw_summary),
        "stats": parse_pdal_stats(raw_stats),
        "service": payload.get("service"),
    }

@router.get("/jobs/{job_id}/pointclouds/{artifact_index}/preview")
def pointcloud_preview(
    job_id: str,
    artifact_index: int,
    max_points: int = Query(default=100_000, ge=1_000, le=500_000),
) -> FileResponse:
    _, path = _artifact_or_404(job_id, artifact_index)
    try:
        metadata = inspect_pointcloud(path)
        preview_path, point_count = _preview_bytes(path, metadata, max_points)
    except (OSError, ValueError, laspy.errors.LaspyException) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Punktwolkenvorschau konnte nicht erzeugt werden: {exc}",
        ) from exc

    signature = _source_signature(path)
    center = metadata["bounds"]["center"]
    return FileResponse(
        preview_path,
        media_type="application/vnd.geophoto.pointcloud",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{signature}-{max_points}"',
            "X-Point-Count": str(point_count),
            "X-Point-Stride": str(_PREVIEW_DTYPE.itemsize),
            "X-Point-Origin": ",".join(str(value) for value in center),
            "X-Point-Has-RGB": "1" if metadata["has_rgb"] else "0",
        },
    )
