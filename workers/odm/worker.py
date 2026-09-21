from __future__ import annotations

import re
import shutil
from pathlib import Path

from common.runtime import DATA_ROOT, consume, run_process, update_job

ENGINE = "odm"
SUPPORTED = {".jpg", ".jpeg", ".tif", ".tiff", ".dng", ".rjpeg"}

PROFILES = {
    "preview": [
        "--fast-orthophoto",
        "--skip-3dmodel",
        "--pc-quality",
        "lowest",
        "--orthophoto-resolution",
        "10",
    ],
    "standard": [
        "--dsm",
        "--dtm",
        "--pc-quality",
        "medium",
        "--orthophoto-resolution",
        "5",
    ],
    "high": [
        "--dsm",
        "--dtm",
        "--pc-quality",
        "high",
        "--orthophoto-resolution",
        "2",
    ],
}

ARTIFACTS = [
    ("orthophoto", "odm_orthophoto/odm_orthophoto.tif"),
    ("dsm", "odm_dem/dsm.tif"),
    ("dtm", "odm_dem/dtm.tif"),
    ("point_cloud_laz", "odm_georeferencing/odm_georeferenced_model.laz"),
    ("mesh_obj", "odm_texturing/odm_textured_model.obj"),
    ("report_pdf", "odm_report/report.pdf"),
]


def _stage_images(dataset_id: str, project_dir: Path) -> int:
    source = DATA_ROOT / "datasets" / dataset_id / "images"
    if not source.exists():
        raise FileNotFoundError(f"Dataset image directory not found: {source}")

    target = project_dir / "images"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    count = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        count += 1
        dest = target / f"{count:06d}_{path.name}"
        try:
            dest.symlink_to(path)
        except OSError:
            shutil.copy2(path, dest)
    if count < 2:
        raise ValueError("ODM requires at least two supported images.")
    return count


def _progress(line: str) -> float | None:
    match = re.search(r"(?:progress|completed)\D+(\d{1,3})(?:\.\d+)?%", line, re.IGNORECASE)
    if match:
        return float(match.group(1))
    stages = [
        ("opensfm", 20.0),
        ("openmvs", 45.0),
        ("odm_filterpoints", 60.0),
        ("odm_meshing", 70.0),
        ("odm_texturing", 80.0),
        ("odm_georeferencing", 88.0),
        ("odm_dem", 93.0),
        ("odm_orthophoto", 97.0),
    ]
    lowered = line.lower()
    for token, value in stages:
        if token in lowered:
            return value
    return None


def _collect_artifacts(project_dir: Path, job_id: str) -> list[dict]:
    result: list[dict] = []
    for kind, relative in ARTIFACTS:
        path = project_dir / relative
        if path.is_file():
            result.append(
                {
                    "type": kind,
                    "name": path.name,
                    "relative_path": f"jobs/{job_id}/project/{relative}",
                    "size_bytes": path.stat().st_size,
                }
            )
    return result


def handle(payload: dict) -> None:
    job_id = payload["job_id"]
    dataset_id = payload["dataset_id"]
    profile = payload.get("profile", "standard")
    options = PROFILES.get(profile)
    if options is None:
        raise ValueError(f"Unsupported ODM profile: {profile}")

    job_root = DATA_ROOT / "jobs" / job_id
    project_dir = job_root / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    log_path = job_root / "worker.log"

    update_job(job_id, status="running", progress=1, phase="staging", message="Preparing ODM project.")
    image_count = _stage_images(dataset_id, project_dir)
    update_job(
        job_id,
        progress=5,
        phase="processing",
        message=f"ODM processing {image_count} images using profile '{profile}'.",
    )

    command = [
        "python3",
        "/code/run.py",
        "--project-path",
        str(job_root),
        "project",
        *options,
    ]
    code = run_process(
        job_id,
        command,
        cwd=Path("/code"),
        log_path=log_path,
        progress_probe=_progress,
    )
    if code == 130:
        return
    if code != 0:
        raise RuntimeError(f"ODM exited with code {code}. See {log_path}")

    artifacts = _collect_artifacts(project_dir, job_id)
    update_job(
        job_id,
        status="completed",
        progress=100,
        phase="completed",
        message=f"ODM completed with {len(artifacts)} detected artifacts.",
        artifacts=artifacts,
    )


if __name__ == "__main__":
    consume(ENGINE, handle)
