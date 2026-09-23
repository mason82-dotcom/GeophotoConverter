from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DB_PATH, ensure_directories

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    scan_status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    media_type TEXT,
    sha256 TEXT,
    metadata_json TEXT,
    fh2_media_json TEXT,
    scan_error TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE,
    UNIQUE(dataset_id, relative_path)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    engine TEXT NOT NULL,
    profile TEXT NOT NULL,
    workflow TEXT NOT NULL DEFAULT 'rgb',
    options_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    phase TEXT,
    message TEXT,
    artifacts_json TEXT,
    publication_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artifact_jobs (
    id TEXT PRIMARY KEY,
    source_job_id TEXT NOT NULL,
    source_artifact_index INTEGER NOT NULL CHECK(source_artifact_index >= 0),
    processor TEXT NOT NULL,
    operation TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    phase TEXT,
    message TEXT,
    artifacts_json TEXT,
    provenance_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(source_job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
"""


class Store:
    def __init__(self) -> None:
        ensure_directories()
        self._lock = threading.RLock()
        with self.connect() as conn:
            conn.executescript(_SCHEMA)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(files)").fetchall()
            }
            if "sha256" not in columns:
                conn.execute("ALTER TABLE files ADD COLUMN sha256 TEXT")
            if "fh2_media_json" not in columns:
                conn.execute("ALTER TABLE files ADD COLUMN fh2_media_json TEXT")
            job_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "workflow" not in job_columns:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN workflow TEXT NOT NULL DEFAULT 'rgb'"
                )
            if "options_json" not in job_columns:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "publication_json" not in job_columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN publication_json TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_files_dataset_sha256 "
                "ON files(dataset_id, sha256)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artifact_jobs_source_job "
                "ON artifact_jobs(source_job_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artifact_jobs_status "
                "ON artifact_jobs(status, created_at)"
            )

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        for key in (
            "metadata_json",
            "fh2_media_json",
            "artifacts_json",
            "options_json",
            "publication_json",
            "provenance_json",
        ):
            if data.get(key):
                data[key.removesuffix("_json")] = json.loads(data.pop(key))
            else:
                data.pop(key, None)
        return data

    def create_dataset(self, name: str, description: str | None) -> dict[str, Any]:
        dataset_id = self.new_id()
        now = self.now()
        with self._lock, self.connect() as conn:
            conn.execute(
                "INSERT INTO datasets(id,name,description,created_at,updated_at) VALUES(?,?,?,?,?)",
                (dataset_id, name, description, now, now),
            )
        return self.get_dataset(dataset_id)

    def list_datasets(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT d.*,
                    COUNT(f.id) AS image_count,
                    SUM(
                        CASE
                            WHEN (
                                json_extract(f.metadata_json, '$.gps.latitude') IS NOT NULL
                                AND json_extract(f.metadata_json, '$.gps.longitude') IS NOT NULL
                            ) OR (
                                json_extract(f.fh2_media_json, '$.asset.capture.latitudeDeg') IS NOT NULL
                                AND json_extract(f.fh2_media_json, '$.asset.capture.longitudeDeg') IS NOT NULL
                            )
                            THEN 1 ELSE 0
                        END
                    ) AS geotagged_count
                FROM datasets d
                LEFT JOIN files f ON f.dataset_id=d.id
                GROUP BY d.id
                ORDER BY d.created_at DESC
                """
            ).fetchall()
        return [self.row(r) for r in rows]

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT d.*,
                    COUNT(f.id) AS image_count,
                    SUM(
                        CASE
                            WHEN (
                                json_extract(f.metadata_json, '$.gps.latitude') IS NOT NULL
                                AND json_extract(f.metadata_json, '$.gps.longitude') IS NOT NULL
                            ) OR (
                                json_extract(f.fh2_media_json, '$.asset.capture.latitudeDeg') IS NOT NULL
                                AND json_extract(f.fh2_media_json, '$.asset.capture.longitudeDeg') IS NOT NULL
                            )
                            THEN 1 ELSE 0
                        END
                    ) AS geotagged_count
                FROM datasets d
                LEFT JOIN files f ON f.dataset_id=d.id
                WHERE d.id=?
                GROUP BY d.id
                """,
                (dataset_id,),
            ).fetchone()
        return self.row(row)

    def add_file(
        self,
        dataset_id: str,
        relative_path: str,
        stored_path: Path,
        size_bytes: int,
        media_type: str | None,
        sha256: str,
    ) -> dict[str, Any]:
        file_id = self.new_id()
        now = self.now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO files(
                    id,dataset_id,relative_path,stored_path,size_bytes,media_type,sha256,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    file_id,
                    dataset_id,
                    relative_path,
                    str(stored_path),
                    size_bytes,
                    media_type,
                    sha256,
                    now,
                ),
            )
            conn.execute("UPDATE datasets SET updated_at=? WHERE id=?", (now, dataset_id))
            row = conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        return self.row(row)

    def dataset_size_bytes(self, dataset_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM files WHERE dataset_id=?",
                (dataset_id,),
            ).fetchone()
        return int(row["total"]) if row else 0

    def find_file_by_sha256(self, dataset_id: str, sha256: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM files WHERE dataset_id=? AND sha256=? LIMIT 1",
                (dataset_id, sha256),
            ).fetchone()
        return self.row(row)

    def get_file(
        self,
        dataset_id: str,
        file_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM files WHERE dataset_id=? AND id=?",
                (dataset_id, file_id),
            ).fetchone()
        return self.row(row)

    def get_file_by_relative_path(
        self,
        dataset_id: str,
        relative_path: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM files WHERE dataset_id=? AND relative_path=?",
                (dataset_id, relative_path),
            ).fetchone()
        return self.row(row)

    def list_files(self, dataset_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM files WHERE dataset_id=? ORDER BY relative_path",
                (dataset_id,),
            ).fetchall()
        return [self.row(r) for r in rows]

    def update_file_scan(self, file_id: str, metadata: dict[str, Any] | None, error: str | None) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                "UPDATE files SET metadata_json=?, scan_error=? WHERE id=?",
                (json.dumps(metadata) if metadata else None, error, file_id),
            )

    def update_file_fh2_media(
        self,
        file_id: str,
        fh2_media: dict[str, Any] | None,
    ) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                "UPDATE files SET fh2_media_json=? WHERE id=?",
                (
                    json.dumps(fh2_media) if fh2_media is not None else None,
                    file_id,
                ),
            )

    def set_dataset_scan_status(self, dataset_id: str, status: str) -> None:
        now = self.now()
        with self._lock, self.connect() as conn:
            conn.execute(
                "UPDATE datasets SET scan_status=?, updated_at=? WHERE id=?",
                (status, now, dataset_id),
            )

    def create_job(
        self,
        dataset_id: str,
        engine: str,
        profile: str,
        workflow: str = "rgb",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = self.new_id()
        now = self.now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                    id,dataset_id,engine,profile,workflow,options_json,
                    status,created_at,updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    dataset_id,
                    engine,
                    profile,
                    workflow,
                    json.dumps(options or {}),
                    "queued",
                    now,
                    now,
                ),
            )
        return self.get_job(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [self.row(r) for r in rows]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self.row(row)

    def update_job_publication(
        self,
        job_id: str,
        publication: dict[str, Any],
    ) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET publication_json=?, updated_at=? WHERE id=?",
                (json.dumps(publication), self.now(), job_id),
            )

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        phase: str | None = None,
        message: str | None = None,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> None:
        current = self.get_job(job_id)
        if current is None:
            return
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status=?, progress=?, phase=?, message=?, artifacts_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    status if status is not None else current["status"],
                    progress if progress is not None else current["progress"],
                    phase if phase is not None else current["phase"],
                    message if message is not None else current["message"],
                    json.dumps(artifacts) if artifacts is not None else (
                        json.dumps(current.get("artifacts")) if current.get("artifacts") else None
                    ),
                    self.now(),
                    job_id,
                ),
            )


    def create_artifact_job(
        self,
        source_job_id: str,
        source_artifact_index: int,
        processor: str,
        operation: str,
        *,
        options: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        status: str = "prepared",
    ) -> dict[str, Any]:
        if source_artifact_index < 0:
            raise ValueError("source_artifact_index must be non-negative.")
        if not processor.strip():
            raise ValueError("processor is required.")
        if not operation.strip():
            raise ValueError("operation is required.")

        artifact_job_id = self.new_id()
        now = self.now()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO artifact_jobs(
                    id,source_job_id,source_artifact_index,processor,operation,
                    options_json,status,progress,provenance_json,
                    created_at,updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    artifact_job_id,
                    source_job_id,
                    int(source_artifact_index),
                    processor.strip(),
                    operation.strip(),
                    json.dumps(options or {}),
                    status,
                    0.0,
                    json.dumps(provenance) if provenance is not None else None,
                    now,
                    now,
                ),
            )
        result = self.get_artifact_job(artifact_job_id)
        assert result is not None
        return result

    def get_artifact_job(self, artifact_job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifact_jobs WHERE id=?",
                (artifact_job_id,),
            ).fetchone()
        return self.row(row)

    def list_artifact_jobs(
        self,
        *,
        source_job_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if source_job_id is None:
                rows = conn.execute(
                    "SELECT * FROM artifact_jobs ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM artifact_jobs
                    WHERE source_job_id=?
                    ORDER BY created_at DESC
                    """,
                    (source_job_id,),
                ).fetchall()
        return [self.row(row) for row in rows]

    def update_artifact_job(
        self,
        artifact_job_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        phase: str | None = None,
        message: str | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> None:
        current = self.get_artifact_job(artifact_job_id)
        if current is None:
            return

        next_progress = (
            max(0.0, min(100.0, float(progress)))
            if progress is not None
            else current["progress"]
        )
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE artifact_jobs
                SET status=?, progress=?, phase=?, message=?,
                    artifacts_json=?, provenance_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    status if status is not None else current["status"],
                    next_progress,
                    phase if phase is not None else current["phase"],
                    message if message is not None else current["message"],
                    (
                        json.dumps(artifacts)
                        if artifacts is not None
                        else (
                            json.dumps(current.get("artifacts"))
                            if current.get("artifacts") is not None
                            else None
                        )
                    ),
                    (
                        json.dumps(provenance)
                        if provenance is not None
                        else (
                            json.dumps(current.get("provenance"))
                            if current.get("provenance") is not None
                            else None
                        )
                    ),
                    self.now(),
                    artifact_job_id,
                ),
            )


store = Store()
