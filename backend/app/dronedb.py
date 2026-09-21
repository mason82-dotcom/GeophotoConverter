from __future__ import annotations

import json
import mimetypes
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .config import (
    DATA_ROOT,
    DRONEDB_BASE_URL,
    DRONEDB_ORG,
    DRONEDB_PASSWORD,
    DRONEDB_USERNAME,
)
from .storage import store

router = APIRouter(prefix="/api/v1", tags=["dronedb"])


class DroneDBPublishRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "geophoto")[:72].rstrip("-")


def _safe_remote_name(value: str) -> str:
    name = Path(value).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or "artifact.bin"


def _artifact_path(relative_path: str) -> Path:
    path = (DATA_ROOT / relative_path).resolve()
    root = DATA_ROOT.resolve()
    if root not in path.parents:
        raise ValueError("Artifact path escapes the GeoPhoto data root")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


class DroneDBClient:
    def __init__(self) -> None:
        self.base_url = DRONEDB_BASE_URL.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=15.0, read=120.0, write=600.0, pool=15.0),
            follow_redirects=True,
        )
        self.token: str | None = None

    def __enter__(self) -> "DroneDBClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.client.close()

    def authenticate(self) -> None:
        response = self.client.post(
            "/users/authenticate",
            json={
                "username": DRONEDB_USERNAME,
                "password": DRONEDB_PASSWORD,
            },
        )
        response.raise_for_status()
        token = response.json().get("token")
        if not token:
            raise RuntimeError("DroneDB authentication returned no token")
        self.token = str(token)

    @property
    def headers(self) -> dict[str, str]:
        if not self.token:
            raise RuntimeError("DroneDB client is not authenticated")
        return {"Authorization": f"Bearer {self.token}"}

    def ensure_organization(self, org_slug: str) -> None:
        response = self.client.get(f"/orgs/{org_slug}", headers=self.headers)
        if response.status_code == 200:
            return
        if response.status_code != 404:
            response.raise_for_status()

        created = self.client.post(
            "/orgs",
            headers=self.headers,
            data={
                "Slug": org_slug,
                "Name": "GeoPhoto Converter",
                "IsPublic": "false",
            },
        )
        if created.status_code not in {200, 201, 409}:
            created.raise_for_status()

    def ensure_dataset(self, org_slug: str, ds_slug: str, name: str) -> None:
        response = self.client.get(
            f"/orgs/{org_slug}/ds/{ds_slug}",
            headers=self.headers,
        )
        if response.status_code == 200:
            return
        if response.status_code != 404:
            response.raise_for_status()

        created = self.client.post(
            f"/orgs/{org_slug}/ds",
            headers=self.headers,
            data={
                "Slug": ds_slug,
                "Name": name,
            },
        )
        if created.status_code not in {200, 201, 409}:
            created.raise_for_status()

    def upload_bytes(
        self,
        org_slug: str,
        ds_slug: str,
        remote_path: str,
        filename: str,
        payload: bytes,
        content_type: str,
    ) -> None:
        response = self.client.post(
            f"/orgs/{org_slug}/ds/{ds_slug}/obj",
            headers=self.headers,
            data={"path": remote_path},
            files={"file": (filename, BytesIO(payload), content_type)},
        )
        response.raise_for_status()

    def upload_file(
        self,
        org_slug: str,
        ds_slug: str,
        remote_path: str,
        path: Path,
    ) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as handle:
            response = self.client.post(
                f"/orgs/{org_slug}/ds/{ds_slug}/obj",
                headers=self.headers,
                data={"path": remote_path},
                files={"file": (path.name, handle, content_type)},
            )
        response.raise_for_status()

    def trigger_build(self, org_slug: str, ds_slug: str) -> None:
        response = self.client.post(
            f"/orgs/{org_slug}/ds/{ds_slug}/build",
            headers={**self.headers, "Content-Type": "application/json"},
            json={},
        )
        if response.status_code not in {200, 201, 202, 204}:
            response.raise_for_status()


def publish_job(job_id: str, requested_name: str | None = None) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail="Only completed jobs can be published to DroneDB",
        )

    existing = job.get("publication")
    if isinstance(existing, dict) and existing.get("status") == "published":
        return existing

    artifacts = job.get("artifacts") or []
    if not artifacts:
        raise HTTPException(
            status_code=409,
            detail="Completed job has no publishable artifacts",
        )

    dataset = store.get_dataset(job["dataset_id"])
    if dataset is None:
        raise HTTPException(status_code=404, detail="Source dataset not found")

    display_name = (requested_name or dataset["name"] or f"GeoPhoto {job_id[:8]}").strip()
    ds_slug = f"{_slugify(display_name)}-{job_id[:8].lower()}"
    org_slug = DRONEDB_ORG

    manifest_artifacts: list[dict[str, Any]] = []
    local_files: list[tuple[str, Path]] = []
    for index, artifact in enumerate(artifacts):
        relative = artifact.get("relative_path")
        if not relative:
            continue
        try:
            local_path = _artifact_path(str(relative))
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Artifact is unavailable for publishing: {artifact.get('name')}",
            ) from exc

        safe_name = _safe_remote_name(artifact.get("name") or local_path.name)
        remote_path = f"results/{index:03d}-{safe_name}"
        local_files.append((remote_path, local_path))
        manifest_artifacts.append({
            "type": artifact.get("type"),
            "name": safe_name,
            "path": remote_path,
            "size_bytes": local_path.stat().st_size,
        })

    manifest = {
        "schema_version": 1,
        "source": "GeoPhotoConverter",
        "job": {
            "id": job["id"],
            "dataset_id": job["dataset_id"],
            "engine": job["engine"],
            "workflow": job.get("workflow"),
            "profile": job["profile"],
            "options": job.get("options") or {},
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        },
        "dataset": {
            "name": dataset["name"],
            "description": dataset.get("description"),
        },
        "artifacts": manifest_artifacts,
    }

    try:
        with DroneDBClient() as client:
            client.authenticate()
            client.ensure_organization(org_slug)
            client.ensure_dataset(org_slug, ds_slug, display_name)

            client.upload_bytes(
                org_slug,
                ds_slug,
                "geophoto-job.json",
                "geophoto-job.json",
                json.dumps(manifest, indent=2).encode("utf-8"),
                "application/json",
            )
            for remote_path, local_path in local_files:
                client.upload_file(org_slug, ds_slug, remote_path, local_path)

            client.trigger_build(org_slug, ds_slug)
    except httpx.HTTPError as exc:
        failed = {
            "status": "failed",
            "provider": "dronedb",
            "job_id": job_id,
            "organization": org_slug,
            "dataset_slug": ds_slug,
            "message": str(exc),
        }
        store.update_job_publication(job_id, failed)
        raise HTTPException(
            status_code=502,
            detail="DroneDB publication failed",
        ) from exc
    except RuntimeError as exc:
        failed = {
            "status": "failed",
            "provider": "dronedb",
            "job_id": job_id,
            "organization": org_slug,
            "dataset_slug": ds_slug,
            "message": str(exc),
        }
        store.update_job_publication(job_id, failed)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    publication = {
        "status": "published",
        "provider": "dronedb",
        "job_id": job_id,
        "organization": org_slug,
        "dataset_slug": ds_slug,
        "dataset_id": f"{org_slug}/{ds_slug}",
        "registry_path": f"/orgs/{org_slug}/ds/{ds_slug}",
        "artifact_count": len(local_files),
        "build_requested": True,
    }
    store.update_job_publication(job_id, publication)
    return publication


@router.post("/jobs/{job_id}/publish/dronedb")
def publish_job_to_dronedb(
    job_id: str,
    body: DroneDBPublishRequest | None = None,
) -> dict[str, Any]:
    return publish_job(job_id, body.name if body else None)
