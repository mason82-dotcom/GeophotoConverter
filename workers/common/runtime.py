from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Callable

from redis import Redis

DATA_ROOT = Path(os.getenv("GEOPHOTO_DATA_ROOT", "/data")).resolve()
DB_PATH = DATA_ROOT / "geophoto.db"
REDIS_URL = os.getenv("GEOPHOTO_REDIS_URL", "redis://redis:6379/0")


def redis_client() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def get_job(job_id: str) -> dict | None:
    with connect_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    phase: str | None = None,
    message: str | None = None,
    artifacts: list[dict] | None = None,
) -> None:
    current = get_job(job_id)
    if not current:
        return
    with connect_db() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status=?, progress=?, phase=?, message=?, artifacts_json=?,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id=?
            """,
            (
                status if status is not None else current["status"],
                progress if progress is not None else current["progress"],
                phase if phase is not None else current["phase"],
                message if message is not None else current["message"],
                json.dumps(artifacts) if artifacts is not None else current["artifacts_json"],
                job_id,
            ),
        )


def cancellation_requested(job_id: str) -> bool:
    job = get_job(job_id)
    return bool(job and job["status"] == "cancel_requested")


def run_process(
    job_id: str,
    command: list[str],
    *,
    cwd: Path,
    log_path: Path,
    progress_probe: Callable[[str], float | None] | None = None,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write("$ " + " ".join(command) + "\n")
        log.flush()
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        assert proc.stdout is not None
        while True:
            line = proc.stdout.readline()
            if line:
                log.write(line)
                log.flush()
                if progress_probe:
                    progress = progress_probe(line)
                    if progress is not None:
                        update_job(job_id, progress=max(0.0, min(99.0, progress)))
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.2)

            if cancellation_requested(job_id) and proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                update_job(
                    job_id,
                    status="cancelled",
                    phase="cancelled",
                    message="Processing cancelled by user.",
                )
                return 130

        return proc.wait()


def consume(engine: str, handler: Callable[[dict], None]) -> None:
    queue = f"geophoto:queue:{engine}"
    client = redis_client()
    while True:
        item = client.brpop(queue, timeout=5)
        if not item:
            continue
        _, raw = item
        payload = json.loads(raw)
        job_id = payload.get("job_id")
        if not job_id:
            continue
        try:
            handler(payload)
        except Exception as exc:
            update_job(
                job_id,
                status="failed",
                phase="failed",
                message=f"{type(exc).__name__}: {exc}",
            )
