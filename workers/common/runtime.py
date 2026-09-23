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

ACCELERATOR = os.getenv("GEOPHOTO_ACCELERATOR", "").strip() or None
CUDA_REQUIRED = os.getenv("GEOPHOTO_CUDA_REQUIRED", "0").strip().lower() in {
    "1", "true", "yes", "on",
}
CUDA_PROBE = os.getenv("GEOPHOTO_CUDA_PROBE", "0").strip().lower() in {
    "1", "true", "yes", "on",
}
CUDA_VERSION = os.getenv("GEOPHOTO_CUDA_VERSION", "").strip() or None

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


def _accelerator_state() -> dict[str, object]:
    if ACCELERATOR != "nvidia-cuda":
        return {}

    state: dict[str, object] = {
        "accelerator": "nvidia-cuda",
        "cuda_required": CUDA_REQUIRED,
    }
    if CUDA_VERSION:
        state["cuda_version"] = CUDA_VERSION
    if not CUDA_PROBE:
        state["cuda_probe"] = "not_requested"
        return state

    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        state["cuda_probe"] = "unavailable"
        return state

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode != 0 or not lines:
        state["cuda_probe"] = "unavailable"
        return state

    parts = [part.strip() for part in lines[0].split(",")]
    state["cuda_probe"] = "ok"
    if parts:
        state["cuda_device"] = parts[0]
    if len(parts) > 1:
        state["cuda_driver"] = parts[1]
    if len(parts) > 2:
        try:
            state["cuda_memory_mb"] = int(float(parts[2]))
        except ValueError:
            pass
    state["cuda_device_count"] = len(lines)
    return state


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
                    message="Verarbeitung wurde vom Benutzer abgebrochen.",
                )
                return 130

        return proc.wait()


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


def _reconcile_jobs(redis: Redis, engine: str, consumer: str) -> int:
    stream = stream_name(engine)
    present = _job_ids_in_stream(redis, stream)
    present.update(_job_ids_in_legacy_queue(redis, engine))

    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE engine=? AND status IN ('queued','running','cancel_requested')
            ORDER BY created_at
            """,
            (engine,),
        ).fetchall()

    recovered = 0
    for row in rows:
        job_id = str(row["id"])
        if job_id in present:
            continue
        if row["status"] == "cancel_requested":
            update_job(
                job_id,
                status="cancelled",
                phase="cancelled",
                message="Abbruch vor Wiederaufnahme bestätigt.",
            )
            continue

        lock = f"geophoto:reconcile:{engine}:{job_id}"
        if not redis.set(lock, consumer, nx=True, ex=60):
            continue

        current = _job_ids_in_stream(redis, stream)
        current.update(_job_ids_in_legacy_queue(redis, engine))
        if job_id in current:
            present.add(job_id)
            continue

        redis.xadd(
            stream,
            {
                "payload": json.dumps(
                    _payload_from_job(row),
                    separators=(",", ":"),
                )
            },
        )
        update_job(
            job_id,
            status="queued",
            phase="recovery",
            message="Auftrag nach Queue-Neustart wieder eingereiht.",
        )
        present.add(job_id)
        recovered += 1
    return recovered


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


def _append_recovery_log(job_id: str, text: str) -> None:
    log_path = DATA_ROOT / "jobs" / str(job_id) / "worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write(f"\n--- {text} ---\n")


def _heartbeat(engine: str, consumer: str) -> None:
    redis = redis_client()
    global_key = f"geophoto:worker:{engine}"
    consumer_key = f"geophoto:worker:{engine}:{consumer}"
    accelerator = _accelerator_state()
    while True:
        payload = json.dumps(
            {
                "engine": engine,
                "status": "online",
                "pid": os.getpid(),
                "consumer": consumer,
                "updated_at": time.time(),
                **accelerator,
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


def consume(engine: str, handler: Callable[[dict], None]) -> None:
    stream = stream_name(engine)
    consumer = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    redis = redis_client()

    _ensure_group(redis, stream)
    _migrate_legacy_queue(redis, engine)
    _reconcile_jobs(redis, engine, consumer)

    threading.Thread(
        target=_heartbeat,
        args=(engine, consumer),
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
        attempt_key = _attempt_key(engine, message_id)

        if payload is None or not payload.get("job_id"):
            _ack_message(redis, stream, message_id, attempt_key)
            continue

        job_id = str(payload["job_id"])
        job = get_job(job_id)
        if job is None or job["status"] in _TERMINAL:
            _ack_message(redis, stream, message_id, attempt_key)
            continue

        if job["status"] == "cancel_requested":
            update_job(
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
            )
            update_job(
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
            )
            update_job(
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
            log_path = DATA_ROOT / "jobs" / str(job_id) / "worker.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8", errors="replace") as log:
                log.write("\n--- Worker-Fehler ---\n")
                traceback.print_exc(file=log)
            update_job(
                job_id,
                status="failed",
                phase="failed",
                message="Verarbeitung fehlgeschlagen. Details siehe Job-Log.",
            )
        finally:
            stop_claim.set()
            claim_thread.join(timeout=2)
            _ack_message(redis, stream, message_id, attempt_key)
