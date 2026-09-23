from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from common.images import prepare_photogrammetry_images
from common.runtime import DATA_ROOT, consume, run_process, update_job

ENGINE = "gsplat"
COLMAP_CUDA = os.getenv("GEOPHOTO_COLMAP_CUDA", "1").strip().lower() in {
    "1", "true", "yes", "on",
}
COLMAP_GPU_INDEX = os.getenv("GEOPHOTO_CUDA_DEVICE", "0").strip() or "0"
COLMAP_VERSION = os.getenv("GEOPHOTO_COLMAP_VERSION", "4.2.0").strip() or "4.2.0"

PROFILES = {
    "preview": {"max_image_size": "1600", "matcher": "sequential_matcher"},
    "standard": {"max_image_size": "2400", "matcher": "exhaustive_matcher"},
    "high": {"max_image_size": "3200", "matcher": "exhaustive_matcher"},
}


def _colmap_feature_command(
    database: Path,
    image_dir: Path,
    max_image_size: str,
) -> list[str]:
    command = [
        "colmap",
        "feature_extractor",
        "--database_path",
        str(database),
        "--image_path",
        str(image_dir),
        "--ImageReader.single_camera",
        "1",
        "--FeatureExtraction.use_gpu",
        "1" if COLMAP_CUDA else "0",
        "--FeatureExtraction.max_image_size",
        max_image_size,
    ]
    if COLMAP_CUDA:
        command.extend(["--FeatureExtraction.gpu_index", COLMAP_GPU_INDEX])
    return command


def _colmap_match_command(database: Path, matcher: str) -> list[str]:
    command = [
        "colmap",
        matcher,
        "--database_path",
        str(database),
        "--FeatureMatching.use_gpu",
        "1" if COLMAP_CUDA else "0",
    ]
    if COLMAP_CUDA:
        command.extend(["--FeatureMatching.gpu_index", COLMAP_GPU_INDEX])
    return command


def _verify_colmap_runtime(log_path: Path) -> None:
    version = subprocess.run(
        ["colmap", "-h"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = (version.stdout or "") + "\n" + (version.stderr or "")
    if version.returncode != 0 or f"COLMAP {COLMAP_VERSION}" not in output:
        raise RuntimeError(
            f"Erwartetes COLMAP {COLMAP_VERSION} ist im gsplat-Container nicht verfügbar."
        )

    cuda_state = "deaktiviert"
    if COLMAP_CUDA:
        gpu = subprocess.run(
            ["nvidia-smi", "-L"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if gpu.returncode != 0 or not (gpu.stdout or "").strip():
            raise RuntimeError(
                "COLMAP-CUDA ist aktiviert, aber im Container ist keine NVIDIA-GPU sichtbar."
            )
        cuda_state = f"aktiv auf GPU {COLMAP_GPU_INDEX}: {(gpu.stdout or '').strip()}"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write(
            f"GeoPhoto COLMAP Runtime: {COLMAP_VERSION}; CUDA-SIFT {cuda_state}.\n"
        )


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
        return 65.0 + min(100.0, float(match.group(1))) * 0.34
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
    result = []
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
        message="gsplat/COLMAP-Projekt wird vorbereitet.",
    )
    manifest = prepare_photogrammetry_images(dataset_id, scene_dir / "images")
    image_count = manifest["prepared_count"]
    if image_count < 3:
        raise ValueError(
            "gsplat benötigt nach der Normalisierung mindestens drei RGB/WIDE-Bilder."
        )

    _verify_colmap_runtime(log_path)

    update_job(
        job_id,
        progress=8,
        phase="colmap_features",
        message=(
            f"COLMAP {COLMAP_VERSION} extrahiert Merkmale aus "
            f"{image_count} RGB/WIDE-Bildern mit "
            f"{'CUDA' if COLMAP_CUDA else 'CPU'} "
            f"({manifest['skipped_count']} Nicht-Mapping-Bilder übersprungen)."
        ),
    )
    if not _run(
        job_id,
        scene_dir,
        log_path,
        _colmap_feature_command(
            database,
            scene_dir / "images",
            profile["max_image_size"],
        ),
    ):
        return

    update_job(
        job_id,
        progress=23,
        phase="colmap_matching",
        message=(
            f"COLMAP {profile['matcher']} gleicht Bildmerkmale "
            f"mit {'CUDA' if COLMAP_CUDA else 'CPU'} ab."
        ),
    )
    if not _run(
        job_id,
        scene_dir,
        log_path,
        _colmap_match_command(database, profile["matcher"]),
    ):
        return

    update_job(
        job_id,
        progress=42,
        phase="colmap_mapping",
        message="COLMAP rekonstruiert Kameraposen und die dünne Punktwolke.",
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
        if candidates[0].name != "0":
            candidates[0].rename(model_dir)

    update_job(
        job_id,
        progress=65,
        phase="gsplat_training",
        message=f"gsplat trainiert Profil '{profile_name}' mit CUDA.",
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
        message=f"gsplat abgeschlossen; {len(artifacts)} Artefakte erkannt.",
        artifacts=artifacts,
    )


if __name__ == "__main__":
    consume(ENGINE, handle)
