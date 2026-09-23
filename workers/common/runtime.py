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
from typing import Callable

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


def get_artifact_job(job_id: str) -> dict | None:
    with connect_db() as conn:
        row = conn.execute(
            "SELECT * FROM artifact_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    return dict(row) if row else None


def update_artifact_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    phase: str | None = None,
    message: str | None = None,
    artifacts: list[dict] | None = None,
) -> None:
    current = get_artifact_job(job_id)
    if not current:
        return
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
                progress if progress is not None else current["progress"],
                phase if phase is not None else current["phase"],
                message if message is not None else current["message"],
                (
                    json.dumps(artifacts)
                    if artifacts is not None
                    else current["artifacts_json"]
                ),
                job_id,
            ),
        )


def artifact_cancellation_requested(job_id: str) -> bool:
    job = get_artifact_job(job_id)
    return bool(job and job["status"] == "cancel_requested")


def cancellation_requested(job_id: str) -> bool:
    job = get_job(job_id)
    return bool(job and job["status"] == "cancel_requested")


def _run_process(
    job_id: str,
    command: list[str],
    *,
    cwd: Path,
    log_path: Path,
    get_job_fn: Callable[[str], dict | None],
    update_job_fn: Callable[..., None],
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
                        update_job_fn(
                            job_id,
                            progress=max(0.0, min(99.0, progress)),
                        )
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.2)

            current = get_job_fn(job_id)
            if (
                current
                and current["status"] == "cancel_requested"
                and proc.poll() is None
            ):
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
                update_job_fn(
                    job_id,
                    status="cancelled",
                    phase="cancelled",
                    message="Verarbeitung wurde vom Benutzer abgebrochen.",
                )
                return 130

        return proc.wait()


def run_process(
    job_id: str,
    command: list[str],
    *,
    cwd: Path,
    log_path: Path,
    progress_probe: Callable[[str], float | None] | None = None,
) -> int:
    return _run_process(
        job_id,
        command,
        cwd=cwd,
        log_path=log_path,
        get_job_fn=get_job,
        update_job_fn=update_job,
        progress_probe=progress_probe,
    )


def run_artifact_process(
    job_id: str,
    command: list[str],
    *,
    cwd: Path,
    log_path: Path,
    progress_probe: Callable[[str], float | None] | None = None,
) -> int:
    return _run_process(
        job_id,
        command,
        cwd=cwd,
        log_path=log_path,
        get_job_fn=get_artifact_job,
        update_job_fn=update_artifact_job,
        progress_probe=progress_probe,
    )


def stream_name(engine: str) -> str:
    return f"geophoto:stream:{engine}"


def legacy_queue_name(engine: str) -> str:
    return f"geophoto:queue:{engine}"


def _ensure_group(redis: Redis, stream: str) -> None:
    try:
        redis.xgroup_create(stream, QUEUE_GROUP, id="0-0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _migrate_legacy_queue(redis: Redis, engine: str) -> int:
    legacy = legacy_queue_name(engine)
    stream = stream_name(engine)
    migrated = 0
    while redis.eval(_LEGACY_MIGRATE_LUA, 2, legacy, stream):
        migrated += 1
    return migrated


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


def _job_ids_in_legacy_queue(redis: Redis, engine: str) -> set[str]:
    result: set[str] = set()
    for raw in redis.lrange(legacy_queue_name(engine), 0, -1):
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("job_id"):
            result.add(str(payload["job_id"]))
    return result


def _payload_from_job(row: sqlite3.Row) -> dict:
    options: dict = {}
    raw_options = row["options_json"] if "options_json" in row.keys() else None
    if raw_options:
        try:
            parsed = json.loads(raw_options)
            if isinstance(parsed, dict):
                options = parsed
        except json.JSONDecodeError:
            pass
    return {
        "job_id": row["id"],
        "dataset_id": row["dataset_id"],
        "engine": row["engine"],
        "profile": row["profile"],
        "workflow": row["workflow"],
        "options": options,
    }


def _payload_from_artifact_job(row: sqlite3.Row) -> dict:
    options: dict = {}
    raw_options = row["options_json"] if "options_json" in row.keys() else None
    if raw_options:
        try:
            parsed = json.loads(raw_options)
            if isinstance(parsed, dict):
                options = parsed
        except json.JSONDecodeError:
            pass
    return {
        "job_id": row["id"],
        "source_job_id": row["source_job_id"],
        "source_artifact_index": int(row["source_artifact_index"]),
        "processor": row["processor"],
        "operation": row["operation"],
        "options": options,
    }


def _dataset_recovery_rows(engine: str) -> list[sqlite3.Row]:
    with connect_db() as conn:
        return conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE engine=? AND status IN ('queued','running','cancel_requested')
            ORDER BY created_at
            """,
            (engine,),
        ).fetchall()


def _artifact_recovery_rows(processor: str) -> list[sqlite3.Row]:
    with connect_db() as conn:
        return conn.execute(
            """
            SELECT *
            FROM artifact_jobs
            WHERE processor=? AND status IN ('queued','running','cancel_requested')
            ORDER BY created_at
            """,
            (processor,),
        ).fetchall()


def _reconcile_backend_jobs(
    redis: Redis,
    *,
    stream_key: str,
    worker_key: str,
    consumer: str,
    recovery_rows_fn: Callable[[str], list[sqlite3.Row]],
    payload_from_row_fn: Callable[[sqlite3.Row], dict],
    update_job_fn: Callable[..., None],
    include_legacy_queue: bool,
) -> int:
    stream = stream_name(stream_key)
    present = _job_ids_in_stream(redis, stream)
    if include_legacy_queue:
        present.update(_job_ids_in_legacy_queue(redis, worker_key))

    rows = recovery_rows_fn(worker_key)

    recovered = 0
    for row in rows:
        job_id = str(row["id"])
        if job_id in present:
            continue
        if row["status"] == "cancel_requested":
            update_job_fn(
                job_id,
                status="cancelled",
                phase="cancelled",
                message="Abbruch vor Wiederaufnahme bestätigt.",
            )
            continue

        lock = f"geophoto:reconcile:{stream_key}:{job_id}"
        if not redis.set(lock, consumer, nx=True, ex=60):
            continue

        current = _job_ids_in_stream(redis, stream)
        if include_legacy_queue:
            current.update(_job_ids_in_legacy_queue(redis, worker_key))
        if job_id in current:
            present.add(job_id)
            continue

        redis.xadd(
            stream,
            {
                "payload": json.dumps(
                    payload_from_row_fn(row),
                    separators=(",", ":"),
                )
            },
        )
        update_job_fn(
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
        stream_key=engine,
        worker_key=engine,
        consumer=consumer,
        recovery_rows_fn=_dataset_recovery_rows,
        payload_from_row_fn=_payload_from_job,
        update_job_fn=update_job,
        include_legacy_queue=True,
    )


def _reconcile_artifact_jobs(
    redis: Redis,
    processor: str,
    consumer: str,
) -> int:
    return _reconcile_backend_jobs(
        redis,
        stream_key=f"artifact:{processor}",
        worker_key=processor,
        consumer=consumer,
        recovery_rows_fn=_artifact_recovery_rows,
        payload_from_row_fn=_payload_from_artifact_job,
        update_job_fn=update_artifact_job,
        include_legacy_queue=False,
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
    return f"geophoto:attempt:{engine}:{message_id}"


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


def _dataset_log_path(job_id: str) -> Path:
    return DATA_ROOT / "jobs" / str(job_id) / "worker.log"


def _artifact_log_path(job_id: str) -> Path:
    return DATA_ROOT / "artifact-jobs" / str(job_id) / "worker.log"


def _append_runtime_log(log_path: Path, text: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write(f"\n--- {text} ---\n")


def _append_recovery_log(job_id: str, text: str) -> None:
    _append_runtime_log(_dataset_log_path(job_id), text)


def _heartbeat(engine: str, consumer: str) -> None:
    redis = redis_client()
    global_key = f"geophoto:worker:{engine}"
    consumer_key = f"geophoto:worker:{engine}:{consumer}"
    while True:
        payload = json.dumps(
            {
                "engine": engine,
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


def _consume_with_backend(
    *,
    stream_key: str,
    worker_key: str,
    handler: Callable[[dict], None],
    get_job_fn: Callable[[str], dict | None],
    update_job_fn: Callable[..., None],
    reconcile_fn: Callable[[Redis, str, str], int],
    log_path_fn: Callable[[str], Path],
    migrate_legacy_queue: bool,
) -> None:
    stream = stream_name(stream_key)
    consumer = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    redis = redis_client()

    _ensure_group(redis, stream)
    if migrate_legacy_queue:
        _migrate_legacy_queue(redis, worker_key)
    reconcile_fn(redis, worker_key, consumer)

    threading.Thread(
        target=_heartbeat,
        args=(stream_key, consumer),
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
        attempt_key = _attempt_key(stream_key, message_id)

        if payload is None or not payload.get("job_id"):
            _ack_message(redis, stream, message_id, attempt_key)
            continue

        job_id = str(payload["job_id"])
        job = get_job_fn(job_id)
        if job is None or job["status"] in _TERMINAL:
            _ack_message(redis, stream, message_id, attempt_key)
            continue

        if job["status"] == "cancel_requested":
            update_job_fn(
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
            _append_runtime_log(
                log_path_fn(job_id),
                (
                    "Maximale Anzahl automatischer Wiederaufnahmen "
                    f"überschritten ({QUEUE_MAX_CRASH_ATTEMPTS})"
                ),
            )
            update_job_fn(
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
            _append_runtime_log(
                log_path_fn(job_id),
                f"Wiederaufnahme nach Worker-Ausfall, Versuch {attempts}",
            )
            update_job_fn(
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
            log_path = log_path_fn(job_id)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8", errors="replace") as log:
                log.write("\n--- Worker-Fehler ---\n")
                traceback.print_exc(file=log)
            update_job_fn(
                job_id,
                status="failed",
                phase="failed",
                message="Verarbeitung fehlgeschlagen. Details siehe Job-Log.",
            )
        finally:
            stop_claim.set()
            claim_thread.join(timeout=2)
            _ack_message(redis, stream, message_id, attempt_key)


def consume(engine: str, handler: Callable[[dict], None]) -> None:
    _consume_with_backend(
        stream_key=engine,
        worker_key=engine,
        handler=handler,
        get_job_fn=get_job,
        update_job_fn=update_job,
        reconcile_fn=_reconcile_jobs,
        log_path_fn=_dataset_log_path,
        migrate_legacy_queue=True,
    )


def consume_artifact_jobs(
    processor: str,
    handler: Callable[[dict], None],
) -> None:
    _consume_with_backend(
        stream_key=f"artifact:{processor}",
        worker_key=processor,
        handler=handler,
        get_job_fn=get_artifact_job,
        update_job_fn=update_artifact_job,
        reconcile_fn=_reconcile_artifact_jobs,
        log_path_fn=_artifact_log_path,
        migrate_legacy_queue=False,
    )

