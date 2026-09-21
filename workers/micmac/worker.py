from __future__ import annotations

import shutil
from pathlib import Path

from common.runtime import DATA_ROOT, consume, run_process, update_job

ENGINE = "micmac"
SUPPORTED = {".jpg", ".jpeg", ".tif", ".tiff"}
PATTERN = r"IMG_[0-9]{6}\..*"

PROFILES = {
    "preview": {
        "tie_size": "1000",
        "calibration": "RadialBasic",
        "dense_mode": None,
    },
    "standard": {
        "tie_size": "1600",
        "calibration": "RadialStd",
        "dense_mode": "QuickMac",
    },
    "high": {
        "tie_size": "2400",
        "calibration": "RadialStd",
        "dense_mode": "BigMac",
    },
}


def _stage_images(dataset_id: str, work_dir: Path) -> int:
    source = DATA_ROOT / "datasets" / dataset_id / "images"
    if not source.exists():
        raise FileNotFoundError(f"Dataset image directory not found: {source}")

    work_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        count += 1
        suffix = path.suffix.upper()
        target = work_dir / f"IMG_{count:06d}{suffix}"
        try:
            target.symlink_to(path)
        except OSError:
            shutil.copy2(path, target)

    if count < 3:
        raise ValueError(
            "MicMac currently requires at least three JPEG/TIFF images. "
            "DNG/R-JPEG conversion is not enabled in this worker yet."
        )
    return count


def _run(job_id: str, work_dir: Path, log_path: Path, command: list[str]) -> bool:
    code = run_process(job_id, command, cwd=work_dir, log_path=log_path)
    if code == 130:
        return False
    if code != 0:
        raise RuntimeError(f"MicMac command exited with code {code}: {' '.join(command)}")
    return True


def _artifact(path: Path, job_id: str, work_dir: Path, kind: str) -> dict:
    rel = path.relative_to(work_dir).as_posix()
    return {
        "type": kind,
        "name": path.name,
        "relative_path": f"jobs/{job_id}/micmac/{rel}",
        "size_bytes": path.stat().st_size,
    }


def _collect_artifacts(work_dir: Path, job_id: str) -> list[dict]:
    result: list[dict] = []
    preferred = [
        (work_dir / "Sparse.ply", "sparse_point_cloud"),
        (work_dir / "Dense.ply", "dense_point_cloud"),
    ]
    seen: set[Path] = set()

    for path, kind in preferred:
        if path.is_file():
            result.append(_artifact(path, job_id, work_dir, kind))
            seen.add(path.resolve())

    for path in sorted(work_dir.glob("*.ply")):
        if path.resolve() in seen:
            continue
        result.append(_artifact(path, job_id, work_dir, "point_cloud"))

    return result


def handle(payload: dict) -> None:
    job_id = payload["job_id"]
    dataset_id = payload["dataset_id"]
    profile_name = payload.get("profile", "standard")
    profile = PROFILES.get(profile_name)
    if profile is None:
        raise ValueError(f"Unsupported MicMac profile: {profile_name}")

    job_root = DATA_ROOT / "jobs" / job_id
    work_dir = job_root / "micmac"
    log_path = job_root / "worker.log"

    if work_dir.exists():
        shutil.rmtree(work_dir)

    update_job(
        job_id,
        status="running",
        progress=1,
        phase="staging",
        message="Preparing MicMac project.",
    )
    image_count = _stage_images(dataset_id, work_dir)

    update_job(
        job_id,
        progress=8,
        phase="tie_points",
        message=f"MicMac Tapioca matching {image_count} images.",
    )
    if not _run(
        job_id,
        work_dir,
        log_path,
        ["mm3d", "Tapioca", "All", PATTERN, profile["tie_size"]],
    ):
        return

    update_job(
        job_id,
        progress=35,
        phase="orientation",
        message=f"MicMac Tapas calibration: {profile['calibration']}.",
    )
    if not _run(
        job_id,
        work_dir,
        log_path,
        [
            "mm3d",
            "Tapas",
            profile["calibration"],
            PATTERN,
            "Out=GeoPhoto",
        ],
    ):
        return

    update_job(
        job_id,
        progress=58,
        phase="sparse_cloud",
        message="Generating MicMac sparse point cloud.",
    )
    if not _run(
        job_id,
        work_dir,
        log_path,
        ["mm3d", "AperiCloud", PATTERN, "GeoPhoto", "Out=Sparse.ply"],
    ):
        return

    dense_mode = profile["dense_mode"]
    if dense_mode:
        update_job(
            job_id,
            progress=68,
            phase="dense_cloud",
            message=f"Generating dense point cloud with C3DC {dense_mode}.",
        )
        if not _run(
            job_id,
            work_dir,
            log_path,
            [
                "mm3d",
                "C3DC",
                dense_mode,
                PATTERN,
                "GeoPhoto",
                "Out=Dense.ply",
            ],
        ):
            return

    artifacts = _collect_artifacts(work_dir, job_id)
    update_job(
        job_id,
        status="completed",
        progress=100,
        phase="completed",
        message=f"MicMac completed with {len(artifacts)} detected artifacts.",
        artifacts=artifacts,
    )


if __name__ == "__main__":
    consume(ENGINE, handle)
