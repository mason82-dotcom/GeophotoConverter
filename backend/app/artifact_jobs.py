from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .config import DATA_ROOT
from .storage import store

router = APIRouter(prefix="/api/v1", tags=["artifact-processing"])
_TERMINAL = {"completed", "failed", "cancelled"}


def _artifact_job_or_404(artifact_job_id: str) -> dict[str, Any]:
    job = store.get_artifact_job(artifact_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Artifact-Job nicht gefunden")
    return job


def _owned_artifact_path(
    artifact_job_id: str,
    artifact: dict[str, Any],
) -> Path:
    relative = artifact.get("relative_path")
    if not relative:
        raise HTTPException(
            status_code=404,
            detail="Artefaktpfad ist nicht verfügbar",
        )

    path = (DATA_ROOT / str(relative)).resolve()
    owner_root = (DATA_ROOT / "artifact-jobs" / artifact_job_id).resolve()
    if path != owner_root and owner_root not in path.parents:
        raise HTTPException(
            status_code=403,
            detail="Artifact-Job verweist auf einen fremden Artefaktpfad.",
        )
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Abgeleitete Artefaktdatei nicht gefunden",
        )
    return path


@router.get("/artifact-jobs/{artifact_job_id}")
def get_artifact_job(artifact_job_id: str) -> dict[str, Any]:
    return _artifact_job_or_404(artifact_job_id)


@router.get("/jobs/{source_job_id}/artifact-jobs")
def list_source_artifact_jobs(source_job_id: str) -> dict[str, Any]:
    if not store.get_job(source_job_id):
        raise HTTPException(status_code=404, detail="Source-Job nicht gefunden")
    return {
        "source_job_id": source_job_id,
        "artifact_jobs": store.list_artifact_jobs(source_job_id=source_job_id),
    }


@router.post("/artifact-jobs/{artifact_job_id}/cancel")
def cancel_artifact_job(artifact_job_id: str) -> dict[str, Any]:
    job = _artifact_job_or_404(artifact_job_id)
    if job["status"] in _TERMINAL:
        return job

    store.update_artifact_job(
        artifact_job_id,
        status="cancel_requested",
        message="Abbruch des Artifact-Processing-Auftrags angefordert.",
    )
    result = store.get_artifact_job(artifact_job_id)
    assert result is not None
    return result


@router.get("/artifact-jobs/{artifact_job_id}/logs")
def artifact_job_log(artifact_job_id: str) -> FileResponse:
    _artifact_job_or_404(artifact_job_id)
    path = (
        DATA_ROOT
        / "artifact-jobs"
        / artifact_job_id
        / "worker.log"
    ).resolve()
    owner_root = (DATA_ROOT / "artifact-jobs" / artifact_job_id).resolve()
    if path != owner_root and owner_root not in path.parents:
        raise HTTPException(status_code=403, detail="Ungültiger Logpfad")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Worker-Log noch nicht verfügbar")
    return FileResponse(
        path=path,
        media_type="text/plain; charset=utf-8",
        filename=f"{artifact_job_id}-worker.log",
    )


@router.get(
    "/artifact-jobs/{artifact_job_id}/artifacts/{artifact_index}"
)
def download_artifact_job_artifact(
    artifact_job_id: str,
    artifact_index: int,
) -> FileResponse:
    job = _artifact_job_or_404(artifact_job_id)
    artifacts = job.get("artifacts") or []
    if artifact_index < 0 or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="Artefakt nicht gefunden")

    artifact = artifacts[artifact_index]
    path = _owned_artifact_path(artifact_job_id, artifact)
    return FileResponse(
        path=path,
        filename=artifact.get("name") or path.name,
    )
