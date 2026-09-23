from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Protocol

from redis import Redis
from redis.exceptions import ResponseError

DATA_ROOT = Path(os.getenv("GEOPHOTO_DATA_ROOT", "/data")).resolve()
DB_PATH = DATA_ROOT / "geophoto.db"
REDIS_URL = os.getenv("GEOPHOTO_REDIS_URL", "redis://redis:6379/0")

QUEUE_GROUP = os.getenv("GEOPHOTO_QUEUE_GROUP", "geophoto-workers")
QUEUE_STALE_SECONDS = max(30, int(os.getenv("GEOPHOTO_QUEUE_STALE_SECONDS", "180")))
QUEUE_MAX_CRASH_ATTEMPTS = max(
    1,
    int(os.getenv("GEOPHOTO_QUEUE_MAX_CRASH_ATTEMPTS", "3")),
)
_TERMINAL = {"completed", "failed", "cancelled"}

_LEGACY_MIGRATE_LUA = """
local raw = redis.call('RPOP', KEYS[1])
if not raw then
  return nil
end
return redis.call('XADD', KEYS[2], '*', 'payload', raw)
"""


def redis_client() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _json_object(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class JobBackend(Protocol):
    namespace: str

    def get(self, job_id: str) -> dict[str, Any] | None: ...

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        phase: str | None = None,
        message: str | None = None,
        artifacts: list[dict] | None = None,
    ) -> None: ...

    def recovery_rows(self, worker_key: str) -> list[sqlite3.Row]: ...

    def payload(self, row: sqlite3.Row) -> dict[str, Any]: ...

    def log_path(self, job_id: str) -> Path: ...

    def stream_name(self, worker_key: str) -> str: ...

    def legacy_queue_name(self, worker_key: str) -> str | None: ...

    def worker_state_key(self, worker_key: str) -> str: ...

    def reconcile_lock_key(self, worker_key: str, job_id: str) -> str: ...

    def attempt_key(self, worker_key: str, message_id: str) -> str: ...


class DatasetJobBackend:
    namespace = "dataset"

    def get(self, job_id: str) -> dict[str, Any] | None:
        with connect_db() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        phase: str | None = None,
        message: str | None = None,
        artifacts: list[dict] | None = None,
    ) -> None:
        current = self.get(job_id)
        if not current:
            return
        next_progress = (
            max(0.0, min(100.0, float(progress)))
            if progress is not None
            else current["progress"]
        )
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
                    next_progress,
                    phase if phase is not None else current["phase"],
                    message if message is not None else current["message"],
                    json.dumps(artifacts)
                    if artifacts is not None
                    else current["artifacts_json"],
                    job_id,
                ),
            )

    def recovery_rows(self, worker_key: str) -> list[sqlite3.Row]:
        with connect_db() as conn:
            return conn.execute(
                """
                SELECT *
                FROM jobs
                WHERE engine=? AND status IN ('queued','running','cancel_requested')
                ORDER BY created_at
                """,
                (worker_key,),
            ).fetchall()

    def payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["id"],
            "dataset_id": row["dataset_id"],
            "engine": row["engine"],
            "profile": row["profile"],
            "workflow": row["workflow"],
            "options": _json_object(row["options_json"]),
        }

    def log_path(self, job_id: str) -> Path:
        return DATA_ROOT / "jobs" / str(job_id) / "worker.log"

    def stream_name(self, worker_key: str) -> str:
        return f"geophoto:stream:{worker_key}"

    def legacy_queue_name(self, worker_key: str) -> str | None:
        return f"geophoto:queue:{worker_key}"

    def worker_state_key(self, worker_key: str) -> str:
        return f"geophoto:worker:{worker_key}"

    def reconcile_lock_key(self, worker_key: str, job_id: str) -> str:
        return f"geophoto:reconcile:{worker_key}:{job_id}"

    def attempt_key(self, worker_key: str, message_id: str) -> str:
        return f"geophoto:attempt:{worker_key}:{message_id}"


class ArtifactJobBackend:
    namespace = "artifact"

    def get(self, job_id: str) -> dict[str, Any] | None:
        with connect_db() as conn:
            row = conn.execute(
                "SELECT * FROM artifact_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        phase: str | None = None,
        message: str | None = None,
        artifacts: list[dict] | None = None,
    ) -> None:
        current = self.get(job_id)
        if not current:
            return
        next_progress = (
            max(0.0, min(100.0, float(progress)))
            if progress is not None
            else current["progress"]
        )
        with connect_db() as conn:
            conn.execute(
                """
                UPDATE artifact_jobs
                SET status=?, progress=?, phase=?, message=?, artifacts_json=?,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE id=?
                """,
                (
                    status if status is not None else current["status"],
                    next_progress,
                    phase if phase is not None else current["phase"],
                    message if message is not None else current["message"],
                    json.dumps(artifacts)
                    if artifacts is not None
                    else current["artifacts_json"],
                    job_id,
                ),
            )

    def recovery_rows(self, worker_key: str) -> list[sqlite3.Row]:
        with connect_db() as conn:
            return conn.execute(
                """
                SELECT *
                FROM artifact_jobs
                WHERE processor=? AND status IN ('queued','running','cancel_requested')
                ORDER BY created_at
                """,
                (worker_key,),
            ).fetchall()

    def payload(self, row: sqlite3.Row) -> dict[str, Any]:
        artifact_job_id = str(row["id"])
        return {
            "job_id": artifact_job_id,
            "artifact_job_id": artifact_job_id,
            "source_job_id": row["source_job_id"],
            "source_artifact_index": int(row["source_artifact_index"]),
            "processor": row["processor"],
            "operation": row["operation"],
            "options": _json_object(row["options_json"]),
        }

    def log_path(self, job_id: str) -> Path:
        return DATA_ROOT / "artifact-jobs" / str(job_id) / "worker.log"

    def stream_name(self, worker_key: str) -> str:
        return f"geophoto:stream:artifact:{worker_key}"

    def legacy_queue_name(self, worker_key: str) -> str | None:
        return None

    def worker_state_key(self, worker_key: str) -> str:
        return f"geophoto:worker:artifact:{worker_key}"

    def reconcile_lock_key(self, worker_key: str, job_id: str) -> str:
        return f"geophoto:reconcile:artifact:{worker_key}:{job_id}"

    def attempt_key(self, worker_key: str, message_id: str) -> str:
        return f"geophoto:attempt:artifact:{worker_key}:{message_id}"


DATASET_JOB_BACKEND = DatasetJobBackend()
ARTIFACT_JOB_BACKEND = ArtifactJobBackend()


# Backwards-compatible helpers used by existing workers.
def get_job(job_id: str) -> dict[str, Any] | None:
    return DATASET_JOB_BACKEND.get(job_id)


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    phase: str | None = None,
    message: str | None = None,
    artifacts: list[dict] | None = None,
) -> None:
    DATASET_JOB_BACKEND.update(
        job_id,
        status=status,
        progress=progress,
        phase=phase,
        message=message,
        artifacts=artifacts,
    )


def cancellation_requested(job_id: str) -> bool:
    job = DATASET_JOB_BACKEND.get(job_id)
    return bool(job and job["status"] == "cancel_requested")


def run_process(
    job_id: str,
    command: list[str],
    *,
    cwd: Path,
    log_path: Path,
    progress_probe: Callable[[str], float | None] | None = None,
    backend: JobBackend | None = None,
) -> int:
    selected = backend or DATASET_JOB_BACKEND
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
                        selected.update(
                            job_id,
                            progress=max(0.0, min(99.0, progress)),
                        )
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.2)

            job = selected.get(job_id)
            if job and job["status"] == "cancel_requested" and proc.poll() is None:
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
                selected.update(
                    job_id,
                    status="cancelled",
                    phase="cancelled",
                    message="Verarbeitung wurde vom Benutzer abgebrochen.",
                )
                return 130

        return proc.wait()


def stream_name(engine: str) -> str:
    return DATASET_JOB_BACKEND.stream_name(engine)


def artifact_stream_name(processor: str) -> str:
    return ARTIFACT_JOB_BACKEND.stream_name(processor)


def legacy_queue_name(engine: str) -> str:
    value = DATASET_JOB_BACKEND.legacy_queue_name(engine)
    assert value is not None
    return value


def _ensure_group(redis: Redis, stream: str) -> None:
    try:
        redis.xgroup_create(stream, QUEUE_GROUP, id="0-0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _migrate_legacy_queue_keys(redis: Redis, legacy: str, stream: str) -> int:
    migrated = 0
    while redis.eval(_LEGACY_MIGRATE_LUA, 2, legacy, stream):
        migrated += 1
    return migrated


def _migrate_legacy_queue(redis: Redis, engine: str) -> int:
    return _migrate_legacy_queue_keys(
        redis,
        legacy_queue_name(engine),
        stream_name(engine),
    )


def _decode_payload(fields: dict) -> dict | None:
    raw = fields.get("payload")
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _job_ids_in_stream(redis: Redis, stream: str) -> set[str]:
    result: set[str] = set()
    for _, fields in redis.xrange(stream, min="-", max="+"):
        payload = _decode_payload(fields)
        job_id = payload.get("job_id") if payload else None
        if job_id:
            result.add(str(job_id))
    return result


def _job_ids_in_legacy_queue_key(redis: Redis, legacy: str | None) -> set[str]:
    if not legacy:
        return set()
    result: set[str] = set()
    for raw in redis.lrange(legacy, 0, -1):
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("job_id"):
            result.add(str(payload["job_id"]))
    return result


def _job_ids_in_legacy_queue(redis: Redis, engine: str) -> set[str]:
    return _job_ids_in_legacy_queue_key(redis, legacy_queue_name(engine))


def _payload_from_job(row: sqlite3.Row) -> dict[str, Any]:
    return DATASET_JOB_BACKEND.payload(row)


def _reconcile_backend_jobs(
    redis: Redis,
    worker_key: str,
    consumer: str,
    backend: JobBackend,
) -> int:
    stream = backend.stream_name(worker_key)
    legacy = backend.legacy_queue_name(worker_key)
    present = _job_ids_in_stream(redis, stream)
    present.update(_job_ids_in_legacy_queue_key(redis, legacy))

    recovered = 0
    for row in backend.recovery_rows(worker_key):
        job_id = str(row["id"])
        if job_id in present:
            continue

        if row["status"] == "cancel_requested":
            backend.update(
                job_id,
                status="cancelled",
                phase="cancelled",
                message="Abbruch vor Wiederaufnahme bestätigt.",
            )
            continue

        lock = backend.reconcile_lock_key(worker_key, job_id)
        if not redis.set(lock, consumer, nx=True, ex=60):
            continue

        current = _job_ids_in_stream(redis, stream)
        current.update(_job_ids_in_legacy_queue_key(redis, legacy))
        if job_id in current:
            present.add(job_id)
            continue

        redis.xadd(
            stream,
            {
                "payload": json.dumps(
                    backend.payload(row),
                    separators=(",", ":"),
                )
            },
        )
        backend.update(
            job_id,
            status="queued",
            phase="recovery",
            message="Auftrag nach Queue-Neustart wieder eingereiht.",
        )
        present.add(job_id)
        recovered += 1
    return recovered


def _reconcile_jobs(redis: Redis, engine: str, consumer: str) -> int:
    return _reconcile_backend_jobs(
        redis,
        engine,
        consumer,
        DATASET_JOB_BACKEND,
    )


def _read_new_message(
    redis: Redis,
    stream: str,
    consumer: str,
    *,
    block_ms: int = 5000,
) -> tuple[str, dict] | None:
    result = redis.xreadgroup(
        QUEUE_GROUP,
        consumer,
        {stream: ">"},
        count=1,
        block=block_ms,
    )
    if not result:
        return None
    _, messages = result[0]
    if not messages:
        return None
    message_id, fields = messages[0]
    return str(message_id), fields


def _recover_stale_message(
    redis: Redis,
    stream: str,
    consumer: str,
    *,
    start_id: str,
    stale_ms: int,
) -> tuple[str, tuple[str, dict] | None]:
    result = redis.xautoclaim(
        stream,
        QUEUE_GROUP,
        consumer,
        stale_ms,
        start_id=start_id,
        count=1,
    )
    if not result:
        return "0-0", None
    next_id = str(result[0])
    messages = result[1] if len(result) > 1 else []
    if not messages:
        return next_id, None
    message_id, fields = messages[0]
    return next_id, (str(message_id), fields)


def _attempt_key(engine: str, message_id: str) -> str:
    return DATASET_JOB_BACKEND.attempt_key(engine, message_id)


def _ack_message(
    redis: Redis,
    stream: str,
    message_id: str,
    attempt_key: str | None = None,
) -> None:
    pipe = redis.pipeline(transaction=True)
    pipe.xack(stream, QUEUE_GROUP, message_id)
    pipe.xdel(stream, message_id)
    if attempt_key:
        pipe.delete(attempt_key)
    pipe.execute()


def _refresh_claim(
    redis: Redis,
    stream: str,
    consumer: str,
    message_id: str,
    stop: threading.Event,
) -> None:
    interval = max(5.0, min(30.0, QUEUE_STALE_SECONDS / 3))
    while not stop.wait(interval):
        try:
            redis.xclaim(
                stream,
                QUEUE_GROUP,
                consumer,
                0,
                [message_id],
                justid=True,
            )
        except Exception:
            pass


def _append_recovery_log(
    job_id: str,
    text: str,
    *,
    backend: JobBackend | None = None,
) -> None:
    selected = backend or DATASET_JOB_BACKEND
    log_path = selected.log_path(job_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write(f"\n--- {text} ---\n")


def _heartbeat(
    worker_key: str,
    consumer: str,
    backend: JobBackend | None = None,
) -> None:
    selected = backend or DATASET_JOB_BACKEND
    redis = redis_client()
    global_key = selected.worker_state_key(worker_key)
    consumer_key = f"{global_key}:{consumer}"
    while True:
        payload = json.dumps(
            {
                "engine": worker_key,
                "job_namespace": selected.namespace,
                "status": "online",
                "pid": os.getpid(),
                "consumer": consumer,
                "updated_at": time.time(),
            }
        )
        try:
            pipe = redis.pipeline(transaction=False)
            pipe.set(global_key, payload, ex=15)
            pipe.set(consumer_key, payload, ex=15)
            pipe.execute()
        except Exception:
            pass
        time.sleep(5)


def consume(
    worker_key: str,
    handler: Callable[[dict], None],
    *,
    backend: JobBackend | None = None,
) -> None:
    selected = backend or DATASET_JOB_BACKEND
    stream = selected.stream_name(worker_key)
    consumer = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    redis = redis_client()

    _ensure_group(redis, stream)
    legacy = selected.legacy_queue_name(worker_key)
    if legacy:
        _migrate_legacy_queue_keys(redis, legacy, stream)
    _reconcile_backend_jobs(redis, worker_key, consumer, selected)

    threading.Thread(
        target=_heartbeat,
        args=(worker_key, consumer, selected),
        daemon=True,
    ).start()

    recovery_cursor = "0-0"
    stale_ms = QUEUE_STALE_SECONDS * 1000

    while True:
        recovery_cursor, recovered = _recover_stale_message(
            redis,
            stream,
            consumer,
            start_id=recovery_cursor,
            stale_ms=stale_ms,
        )
        message = recovered or _read_new_message(redis, stream, consumer)
        if message is None:
            continue

        message_id, fields = message
        payload = _decode_payload(fields)
        attempt_key = selected.attempt_key(worker_key, message_id)

        if payload is None or not payload.get("job_id"):
            _ack_message(redis, stream, message_id, attempt_key)
            continue

        job_id = str(payload["job_id"])
        job = selected.get(job_id)
        if job is None or job["status"] in _TERMINAL:
            _ack_message(redis, stream, message_id, attempt_key)
            continue

        if job["status"] == "cancel_requested":
            selected.update(
                job_id,
                status="cancelled",
                phase="cancelled",
                message="Abbruch vor Verarbeitungsstart bestätigt.",
            )
            _ack_message(redis, stream, message_id, attempt_key)
            continue

        attempts = int(redis.incr(attempt_key))
        redis.expire(attempt_key, 86400)
        if attempts > QUEUE_MAX_CRASH_ATTEMPTS:
            _append_recovery_log(
                job_id,
                (
                    "Maximale Anzahl automatischer Wiederaufnahmen "
                    f"überschritten ({QUEUE_MAX_CRASH_ATTEMPTS})"
                ),
                backend=selected,
            )
            selected.update(
                job_id,
                status="failed",
                phase="failed",
                message=(
                    "Verarbeitung nach wiederholtem Worker-Ausfall "
                    "endgültig fehlgeschlagen."
                ),
            )
            _ack_message(redis, stream, message_id, attempt_key)
            continue

        if recovered is not None:
            _append_recovery_log(
                job_id,
                f"Wiederaufnahme nach Worker-Ausfall, Versuch {attempts}",
                backend=selected,
            )
            selected.update(
                job_id,
                status="queued",
                phase="recovery",
                message=(
                    "Verarbeitung wird nach einem Worker-Ausfall "
                    "automatisch wiederaufgenommen."
                ),
            )

        stop_claim = threading.Event()
        claim_thread = threading.Thread(
            target=_refresh_claim,
            args=(redis, stream, consumer, message_id, stop_claim),
            daemon=True,
        )
        claim_thread.start()

        try:
            handler(payload)
        except Exception:
            log_path = selected.log_path(job_id)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8", errors="replace") as log:
                log.write("\n--- Worker-Fehler ---\n")
                traceback.print_exc(file=log)
            selected.update(
                job_id,
                status="failed",
                phase="failed",
                message="Verarbeitung fehlgeschlagen. Details siehe Job-Log.",
            )
        finally:
            stop_claim.set()
            claim_thread.join(timeout=2)
            _ack_message(redis, stream, message_id, attempt_key)
