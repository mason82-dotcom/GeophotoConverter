from __future__ import annotations

import struct
from pathlib import Path

import laspy
import numpy as np
from pyproj import CRS

from app.config import DATA_ROOT
from app.storage import store


def _job_with_artifacts(artifacts: list[dict]) -> dict:
    dataset = store.create_dataset("Point Cloud Test", None)
    job = store.create_job(dataset["id"], "odm", "preview")
    store.update_job(
        job["id"],
        status="completed",
        progress=100,
        artifacts=artifacts,
    )
    return store.get_job(job["id"])


def _las_file(
    path: Path,
    *,
    compressed: bool,
    crs_epsg: int | None = None,
) -> None:
    header = laspy.LasHeader(point_format=3, version="1.2")
    if crs_epsg is not None:
        header.add_crs(CRS.from_epsg(crs_epsg))
    las = laspy.LasData(header)
    count = 8
    las.x = np.linspace(100.0, 107.0, count)
    las.y = np.linspace(200.0, 214.0, count)
    las.z = np.linspace(50.0, 57.0, count)
    las.red = np.arange(count, dtype=np.uint16) * 9000
    las.green = np.arange(count, dtype=np.uint16)[::-1] * 9000
    las.blue = np.full(count, 32768, dtype=np.uint16)
    las.write(path, do_compress=compressed)


def _ascii_ply(path: Path) -> None:
    path.write_text(
        """ply
format ascii 1.0
element vertex 4
property float x
property float y
property float z
property uchar red
property uchar green
property uchar blue
end_header
0 0 0 255 0 0
1 0 1 0 255 0
0 2 2 0 0 255
2 2 3 255 255 255
""",
        encoding="ascii",
    )


def test_pointcloud_list_excludes_gsplat_ply(client):
    root = DATA_ROOT / "jobs" / "pc-list"
    root.mkdir(parents=True, exist_ok=True)
    las_path = root / "cloud.las"
    _las_file(las_path, compressed=False)
    gsplat_path = root / "splats.ply"
    _ascii_ply(gsplat_path)

    job = _job_with_artifacts(
        [
            {
                "type": "point_cloud_laz",
                "name": "cloud.las",
                "relative_path": las_path.relative_to(DATA_ROOT).as_posix(),
                "size_bytes": las_path.stat().st_size,
            },
            {
                "type": "gaussian_splat_ply",
                "name": "splats.ply",
                "relative_path": gsplat_path.relative_to(DATA_ROOT).as_posix(),
                "size_bytes": gsplat_path.stat().st_size,
            },
        ]
    )

    response = client.get(f"/api/v1/jobs/{job['id']}/pointclouds")
    assert response.status_code == 200
    items = response.json()["pointclouds"]
    assert len(items) == 1
    assert items[0]["artifact_index"] == 0
    assert items[0]["name"] == "cloud.las"


def test_las_metadata_and_binary_preview(client):
    root = DATA_ROOT / "jobs" / "pc-las"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "cloud.las"
    _las_file(path, compressed=False)

    job = _job_with_artifacts(
        [
            {
                "type": "point_cloud_laz",
                "name": path.name,
                "relative_path": path.relative_to(DATA_ROOT).as_posix(),
                "size_bytes": path.stat().st_size,
            }
        ]
    )

    metadata = client.get(f"/api/v1/jobs/{job['id']}/pointclouds/0")
    assert metadata.status_code == 200
    body = metadata.json()
    assert body["format"] == "las"
    assert body["point_count"] == 8
    assert body["has_rgb"] is True
    assert body["bounds"]["min"] == [100.0, 200.0, 50.0]
    assert body["bounds"]["max"] == [107.0, 214.0, 57.0]

    preview = client.get(
        f"/api/v1/jobs/{job['id']}/pointclouds/0/preview",
        params={"max_points": 1000},
    )
    assert preview.status_code == 200
    assert preview.headers["x-point-count"] == "8"
    assert preview.headers["x-point-stride"] == "16"
    assert preview.headers["x-point-has-rgb"] == "1"
    assert len(preview.content) == 8 * 16
    x, y, z = struct.unpack_from("<fff", preview.content, 0)
    assert x < 0
    assert y < 0
    assert z < 0


def test_laz_preview_respects_sampling_limit(client):
    root = DATA_ROOT / "jobs" / "pc-laz"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "cloud.laz"
    _las_file(path, compressed=True)

    job = _job_with_artifacts(
        [
            {
                "type": "point_cloud_laz",
                "name": path.name,
                "relative_path": path.relative_to(DATA_ROOT).as_posix(),
                "size_bytes": path.stat().st_size,
            }
        ]
    )

    metadata = client.get(f"/api/v1/jobs/{job['id']}/pointclouds/0")
    assert metadata.status_code == 200
    assert metadata.json()["format"] == "laz"

    preview = client.get(
        f"/api/v1/jobs/{job['id']}/pointclouds/0/preview",
        params={"max_points": 1000},
    )
    assert preview.status_code == 200
    assert int(preview.headers["x-point-count"]) <= 1000


def test_ascii_ply_metadata_and_preview(client):
    root = DATA_ROOT / "jobs" / "pc-ply"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "dense.ply"
    _ascii_ply(path)

    job = _job_with_artifacts(
        [
            {
                "type": "dense_point_cloud",
                "name": path.name,
                "relative_path": path.relative_to(DATA_ROOT).as_posix(),
                "size_bytes": path.stat().st_size,
            }
        ]
    )

    metadata = client.get(f"/api/v1/jobs/{job['id']}/pointclouds/0")
    assert metadata.status_code == 200
    body = metadata.json()
    assert body["format"] == "ply"
    assert body["ply_encoding"] == "ascii"
    assert body["point_count"] == 4
    assert body["has_rgb"] is True
    assert body["bounds"]["max"] == [2.0, 2.0, 3.0]

    preview = client.get(
        f"/api/v1/jobs/{job['id']}/pointclouds/0/preview",
        params={"max_points": 1000},
    )
    assert preview.status_code == 200
    assert preview.headers["x-point-count"] == "4"
    assert len(preview.content) == 64


def test_binary_little_endian_ply(client):
    root = DATA_ROOT / "jobs" / "pc-binary-ply"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "sparse.ply"
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "element vertex 2\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
    ).encode("ascii")
    path.write_bytes(
        header
        + struct.pack("<fff", 1.0, 2.0, 3.0)
        + struct.pack("<fff", 4.0, 5.0, 6.0)
    )

    job = _job_with_artifacts(
        [
            {
                "type": "sparse_point_cloud",
                "name": path.name,
                "relative_path": path.relative_to(DATA_ROOT).as_posix(),
                "size_bytes": path.stat().st_size,
            }
        ]
    )
    response = client.get(f"/api/v1/jobs/{job['id']}/pointclouds/0")
    assert response.status_code == 200
    assert response.json()["point_count"] == 2
    assert response.json()["has_rgb"] is False


def test_non_pointcloud_artifact_is_rejected(client):
    root = DATA_ROOT / "jobs" / "pc-invalid"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "result.txt"
    path.write_text("x", encoding="utf-8")
    job = _job_with_artifacts(
        [
            {
                "type": "report",
                "name": path.name,
                "relative_path": path.relative_to(DATA_ROOT).as_posix(),
                "size_bytes": path.stat().st_size,
            }
        ]
    )

    response = client.get(f"/api/v1/jobs/{job['id']}/pointclouds/0")
    assert response.status_code == 422



def test_truncated_ascii_ply_returns_422(client):
    root = DATA_ROOT / "jobs" / "pc-truncated-ply"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "broken.ply"
    path.write_text(
        "ply\n"
        "format ascii 1.0\n"
        "element vertex 1\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
        "1.0 2.0\n",
        encoding="ascii",
    )
    job = _job_with_artifacts([{
        "type": "dense_point_cloud",
        "name": path.name,
        "relative_path": path.relative_to(DATA_ROOT).as_posix(),
        "size_bytes": path.stat().st_size,
    }])
    response = client.get(f"/api/v1/jobs/{job['id']}/pointclouds/0")
    assert response.status_code == 422
    assert "zu wenige Werte" in response.json()["detail"]


def test_non_finite_ascii_ply_returns_422(client):
    root = DATA_ROOT / "jobs" / "pc-nan-ply"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "nan.ply"
    path.write_text(
        "ply\n"
        "format ascii 1.0\n"
        "element vertex 1\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
        "nan 2.0 3.0\n",
        encoding="ascii",
    )
    job = _job_with_artifacts([{
        "type": "dense_point_cloud",
        "name": path.name,
        "relative_path": path.relative_to(DATA_ROOT).as_posix(),
        "size_bytes": path.stat().st_size,
    }])
    response = client.get(f"/api/v1/jobs/{job['id']}/pointclouds/0")
    assert response.status_code == 422
    assert "nicht endliche Koordinaten" in response.json()["detail"]


def test_ply_header_larger_than_limit_returns_422(client):
    root = DATA_ROOT / "jobs" / "pc-large-header"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "huge-header.ply"
    with path.open("wb") as handle:
        handle.write(b"ply\nformat ascii 1.0\n")
        handle.write(b"comment " + b"x" * (1024 * 1024) + b"\n")
        handle.write(
            b"element vertex 0\n"
            b"property float x\n"
            b"property float y\n"
            b"property float z\n"
            b"end_header\n"
        )
    job = _job_with_artifacts([{
        "type": "dense_point_cloud",
        "name": path.name,
        "relative_path": path.relative_to(DATA_ROOT).as_posix(),
        "size_bytes": path.stat().st_size,
    }])
    response = client.get(f"/api/v1/jobs/{job['id']}/pointclouds/0")
    assert response.status_code == 422
    assert "1 MiB" in response.json()["detail"]



def test_las_crs_and_header_metadata(client):
    root = DATA_ROOT / "jobs" / "pc-crs-las"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "utm32.las"
    _las_file(path, compressed=False, crs_epsg=32632)

    job = _job_with_artifacts([{
        "type": "point_cloud_laz",
        "name": path.name,
        "relative_path": path.relative_to(DATA_ROOT).as_posix(),
        "size_bytes": path.stat().st_size,
    }])

    response = client.get(f"/api/v1/jobs/{job['id']}/pointclouds/0")
    assert response.status_code == 200
    body = response.json()
    assert body["las_version"] == "1.2"
    assert body["point_format"] == 3
    assert body["crs"]["epsg"] == 32632
    assert body["crs"]["projected"] is True
    assert len(body["scales"]) == 3
    assert len(body["offsets"]) == 3
