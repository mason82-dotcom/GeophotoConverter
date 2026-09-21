from __future__ import annotations

import re
import shutil
from pathlib import Path

from common.runtime import DATA_ROOT, consume, run_process, update_job

ENGINE = "gsplat"
SUPPORTED = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

PROFILES = {
    "preview": {
        "max_image_size": "1600",
        "matcher": "sequential_matcher",
    },
    "standard": {
        "max_image_size": "2400",
        "matcher": "exhaustive_matcher",
    },
    "high": {
        "max_image_size": "3200",
        "matcher": "exhaustive_matcher",
    },
}


def _stage_images(dataset_id: str, scene_dir: Path) -> int:
    source = DATA_ROOT / "datasets" / dataset_id / "images"
    if not source.exists():
        raise FileNotFoundError(f"Dataset image directory not found: {source}")

    image_dir = scene_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        count += 1
        target = image_dir / f"IMG_{count:06d}{path.suffix.lower()}"
        try:
            target.symlink_to(path)
        except OSError:
            shutil.copy2(path, target)

    if count < 3:
        raise ValueError(
            "gsplat requires at least three JPEG/PNG/TIFF images. "
            "DNG/R-JPEG normalization is not enabled yet."
        )
    return count


def _run(job_id: str, cwd: Path, log_path: Path, command: list[str]) -> bool:
    code = run_process(job_id, command, cwd=cwd, log_path=log_path)
    if code == 130:
        return False
    if code != 0:
        raise RuntimeError(f"Command exited with code {code}: {' '.join(command)}")
    return True


def _training_progress(line: str) -> float | None:
    match = re.search(r"(\d{1,3})%", line)
    if match:
        percent = min(100.0, float(match.group(1)))
        return 65.0 + percent * 0.34
    step = re.search(r"(?:step|iter(?:ation)?)\D+(\d+)", line, re.IGNORECASE)
    if step:
        return None
    return None


def _artifact(path: Path, job_id: str, result_dir: Path, kind: str) -> dict:
    relative = path.relative_to(result_dir).as_posix()
    return {
        "type": kind,
        "name": path.name,
        "relative_path": f"jobs/{job_id}/gsplat/results/{relative}",
        "size_bytes": path.stat().st_size,
    }


def _collect_artifacts(result_dir: Path, job_id: str) -> list[dict]:
    result: list[dict] = []
    for path in sorted(result_dir.rglob("*.ply")):
        result.append(_artifact(path, job_id, result_dir, "gaussian_splat_ply"))
    for path in sorted(result_dir.rglob("*.pt")):
        result.append(_artifact(path, job_id, result_dir, "checkpoint"))
    for path in sorted(result_dir.rglob("*.json")):
        if "stats" in path.parts:
            result.append(_artifact(path, job_id, result_dir, "training_stats"))
    return result


def handle(payload: dict) -> None:
    job_id = payload["job_id"]
    dataset_id = payload["dataset_id"]
    profile_name = payload.get("profile", "standard")
    profile = PROFILES.get(profile_name)
    if profile is None:
        raise ValueError(f"Unsupported gsplat profile: {profile_name}")

    job_root = DATA_ROOT / "jobs" / job_id
    gsplat_root = job_root / "gsplat"
    scene_dir = gsplat_root / "scene"
    sparse_dir = scene_dir / "sparse"
    result_dir = gsplat_root / "results"
    database = scene_dir / "database.db"
    log_path = job_root / "worker.log"

    if gsplat_root.exists():
        shutil.rmtree(gsplat_root)
    sparse_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)

    update_job(
        job_id,
        status="running",
        progress=1,
        phase="staging",
        message="Preparing gsplat/COLMAP project.",
    )
    image_count = _stage_images(dataset_id, scene_dir)

    update_job(
        job_id,
        progress=8,
        phase="colmap_features",
        message=f"COLMAP extracting features from {image_count} images.",
    )
    if not _run(
        job_id,
        scene_dir,
        log_path,
        [
            "colmap",
            "feature_extractor",
            "--database_path",
            str(database),
            "--image_path",
            str(scene_dir / "images"),
            "--ImageReader.single_camera",
            "1",
            "--SiftExtraction.use_gpu",
            "0",
            "--SiftExtraction.max_image_size",
            profile["max_image_size"],
        ],
    ):
        return

    update_job(
        job_id,
        progress=23,
        phase="colmap_matching",
        message=f"COLMAP {profile['matcher']} matching image features.",
    )
    if not _run(
        job_id,
        scene_dir,
        log_path,
        [
            "colmap",
            profile["matcher"],
            "--database_path",
            str(database),
            "--SiftMatching.use_gpu",
            "0",
        ],
    ):
        return

    update_job(
        job_id,
        progress=42,
        phase="colmap_mapping",
        message="COLMAP reconstructing camera poses and sparse point cloud.",
    )
    if not _run(
        job_id,
        scene_dir,
        log_path,
        [
            "colmap",
            "mapper",
            "--database_path",
            str(database),
            "--image_path",
            str(scene_dir / "images"),
            "--output_path",
            str(sparse_dir),
        ],
    ):
        return

    model_dir = sparse_dir / "0"
    if not model_dir.is_dir():
        candidates = sorted(path for path in sparse_dir.iterdir() if path.is_dir())
        if not candidates:
            raise RuntimeError("COLMAP did not produce a sparse reconstruction.")
        model_dir = candidates[0]
        if model_dir.name != "0":
            target = sparse_dir / "0"
            model_dir.rename(target)
            model_dir = target

    update_job(
        job_id,
        progress=65,
        phase="gsplat_training",
        message=f"Training gsplat profile '{profile_name}' on CUDA.",
    )
    code = run_process(
        job_id,
        [
            "python3",
            "/worker/train.py",
            "--data-dir",
            str(scene_dir),
            "--result-dir",
            str(result_dir),
            "--profile",
            profile_name,
        ],
        cwd=Path("/worker"),
        log_path=log_path,
        progress_probe=_training_progress,
    )
    if code == 130:
        return
    if code != 0:
        raise RuntimeError(f"gsplat training exited with code {code}.")

    artifacts = _collect_artifacts(result_dir, job_id)
    update_job(
        job_id,
        status="completed",
        progress=100,
        phase="completed",
        message=f"gsplat completed with {len(artifacts)} detected artifacts.",
        artifacts=artifacts,
    )


if __name__ == "__main__":
    consume(ENGINE, handle)
