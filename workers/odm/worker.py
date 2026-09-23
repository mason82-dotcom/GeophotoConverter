from __future__ import annotations

import os
import re
from pathlib import Path

from common.images import (
    prepare_multispectral_images,
    prepare_photogrammetry_images,
)
from common.runtime import DATA_ROOT, consume, run_process, update_job

ENGINE = "odm"
CUDA_ENABLED = os.getenv("GEOPHOTO_ODM_CUDA", "0").strip().lower() in {
    "1", "true", "yes", "on",
}


def _profile_options(workflow: str, profile: str) -> list[str] | None:
    source = MULTISPECTRAL_PROFILES if workflow == "multispectral" else PROFILES
    base = source.get(profile)
    if base is None:
        return None
    options = list(base)
    if CUDA_ENABLED:
        options.extend(["--feature-type", "sift"])
    return options


PROFILES = {
    "preview": [
        "--fast-orthophoto", "--skip-3dmodel", "--pc-quality", "lowest",
        "--orthophoto-resolution", "10",
    ],
    "standard": [
        "--dsm", "--dtm", "--pc-quality", "medium",
        "--orthophoto-resolution", "5",
    ],
    "high": [
        "--dsm", "--dtm", "--pc-quality", "high",
        "--orthophoto-resolution", "2",
    ],
}

MULTISPECTRAL_PROFILES = {
    "preview": [
        "--radiometric-calibration", "camera",
        "--feature-quality", "medium",
        "--pc-quality", "lowest",
        "--orthophoto-resolution", "10",
        "--auto-boundary",
        "--build-overviews",
        "--skip-3dmodel",
    ],
    "standard": [
        "--radiometric-calibration", "camera",
        "--feature-quality", "high",
        "--pc-quality", "medium",
        "--orthophoto-resolution", "5",
        "--auto-boundary",
        "--build-overviews",
        "--skip-3dmodel",
    ],
    "high": [
        "--radiometric-calibration", "camera",
        "--feature-quality", "high",
        "--pc-quality", "high",
        "--orthophoto-resolution", "2",
        "--auto-boundary",
        "--build-overviews",
        "--skip-3dmodel",
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


def _progress(line: str) -> float | None:
    match = re.search(r"(?:progress|completed)\D+(\d{1,3})(?:\.\d+)?%", line, re.IGNORECASE)
    if match:
        return float(match.group(1))
    for token, value in [
        ("opensfm", 20.0), ("openmvs", 45.0), ("odm_filterpoints", 60.0),
        ("odm_meshing", 70.0), ("odm_texturing", 80.0),
        ("odm_georeferencing", 88.0), ("odm_dem", 93.0),
        ("odm_orthophoto", 97.0),
    ]:
        if token in line.lower():
            return value
    return None


def _collect_artifacts(
    project_dir: Path,
    job_id: str,
    workflow: str,
) -> list[dict]:
    result = []
    for kind, relative in ARTIFACTS:
        path = project_dir / relative
        if path.is_file():
            result.append({
                "type": (
                    "multiband_orthophoto"
                    if workflow == "multispectral" and kind == "orthophoto"
                    else kind
                ),
                "name": path.name,
                "relative_path": f"jobs/{job_id}/project/{relative}",
                "size_bytes": path.stat().st_size,
            })
    return result


def handle(payload: dict) -> None:
    job_id = payload["job_id"]
    dataset_id = payload["dataset_id"]
    profile = payload.get("profile", "standard")
    workflow = payload.get("workflow", "rgb")
    options = _profile_options(workflow, profile)
    if options is None:
        raise ValueError(
            f"Unsupported ODM profile/workflow combination: {profile}/{workflow}"
        )

    job_root = DATA_ROOT / "jobs" / job_id
    project_dir = job_root / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    log_path = job_root / "worker.log"

    update_job(
        job_id,
        status="running",
        progress=1,
        phase="staging",
        message=f"ODM-Projekt wird vorbereitet: {workflow}.",
    )
    if workflow == "multispectral":
        manifest = prepare_multispectral_images(
            dataset_id,
            project_dir / "images",
        )
        image_count = manifest["prepared_count"]
        if image_count < 10:
            raise ValueError(
                "ODM multispectral requires at least two complete M3M capture "
                "groups (10 prepared images)."
            )
        input_label = "M3M-Multispektral"
    else:
        manifest = prepare_photogrammetry_images(
            dataset_id,
            project_dir / "images",
        )
        image_count = manifest["prepared_count"]
        if image_count < 2:
            raise ValueError(
                "ODM benötigt nach der Normalisierung mindestens zwei RGB/WIDE-Bilder."
            )
        input_label = "RGB/WIDE"

    update_job(
        job_id,
        progress=5,
        phase="processing",
        message=(
            f"ODM verarbeitet {image_count} {input_label} Bilder mit "
            f"Profil '{profile}' über {'NVIDIA CUDA' if CUDA_ENABLED else 'CPU'} "
            f"({manifest['skipped_count']} Bilder übersprungen)."
        ),
    )

    code = run_process(
        job_id,
        ["python3", "/code/run.py", "--project-path", str(job_root), "project", *options],
        cwd=Path("/code"),
        log_path=log_path,
        progress_probe=_progress,
    )
    if code == 130:
        return
    if code != 0:
        raise RuntimeError(f"ODM wurde mit Code {code} beendet. Siehe {log_path}")

    artifacts = _collect_artifacts(project_dir, job_id, workflow)
    update_job(
        job_id,
        status="completed",
        progress=100,
        phase="completed",
        message=f"ODM abgeschlossen; {len(artifacts)} Artefakte erkannt.",
        artifacts=artifacts,
    )


if __name__ == "__main__":
    consume(ENGINE, handle)
