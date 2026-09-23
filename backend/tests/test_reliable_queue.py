from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from redis import Redis

from app import queue
from app.config import DB_PATH
from app.storage import store

REDIS_TEST_URL = "redis://127.0.0.1:6379/15"


@pytest.fixture()
def redis_client():
    redis = Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    try:
        redis.ping()
    except Exception:
        pytest.skip("Lokaler Redis-Testdienst ist nicht verfügbar.")
    redis.flushdb()
    yield redis
    redis.flushdb()


def _load_worker_runtime(repo_root: Path):
    workers_root = repo_root / "workers"
    sys.path.insert(0, str(workers_root))
    try:
        spec = importlib.util.spec_from_file_location(
            "geophoto_queue_runtime_test_module",
            workers_root / "common" / "runtime.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_api_enqueue_uses_stream_and_reports_depth(redis_client, monkeypatch):
    monkeypatch.setattr(queue, "client", lambda: redis_client)

    message_id = queue.enqueue(
        "odm",
        {
            "job_id": "job-1",
            "dataset_id": "dataset-1",
            "engine": "odm",
            "profile": "preview",
            "workflow": "rgb",
            "options": {},
        },
    )

    assert message_id
    assert redis_client.xlen(queue.stream_name("odm")) == 1
    assert redis_client.llen(queue.legacy_queue_name("odm")) == 0

    state = queue.worker_state("odm")
    assert state["queue_depth"] == 1
    assert state["processing_depth"] == 0


def test_stream_message_stays_pending_until_ack(redis_client):
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])
    runtime.QUEUE_GROUP = "geophoto-workers-test"

    stream = runtime.stream_name("odm")
    runtime._ensure_group(redis_client, stream)
    redis_client.xadd(stream, {"payload": json.dumps({"job_id": "job-1"})})

    message = runtime._read_new_message(
        redis_client,
        stream,
        "worker-a",
        block_ms=10,
    )
    assert message is not None
    message_id, _ = message

    assert redis_client.xpending(stream, runtime.QUEUE_GROUP)["pending"] == 1
    assert redis_client.xlen(stream) == 1

    runtime._ack_message(redis_client, stream, message_id)
    assert redis_client.xpending(stream, runtime.QUEUE_GROUP)["pending"] == 0
    assert redis_client.xlen(stream) == 0


def test_stale_pending_message_can_be_reclaimed(redis_client):
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])
    runtime.QUEUE_GROUP = "geophoto-workers-test"

    stream = runtime.stream_name("odm")
    runtime._ensure_group(redis_client, stream)
    redis_client.xadd(stream, {"payload": json.dumps({"job_id": "job-2"})})

    original = runtime._read_new_message(
        redis_client,
        stream,
        "dead-worker",
        block_ms=10,
    )
    assert original is not None
    message_id, _ = original

    redis_client.execute_command(
        "XCLAIM",
        stream,
        runtime.QUEUE_GROUP,
        "dead-worker",
        0,
        message_id,
        "IDLE",
        5000,
        "JUSTID",
    )

    _, recovered = runtime._recover_stale_message(
        redis_client,
        stream,
        "replacement-worker",
        start_id="0-0",
        stale_ms=1000,
    )
    assert recovered is not None
    recovered_id, _ = recovered
    assert recovered_id == message_id

    runtime._ack_message(redis_client, stream, recovered_id)


def test_legacy_list_is_migrated_without_losing_fifo_order(redis_client):
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])
    runtime.QUEUE_GROUP = "geophoto-workers-test"
    engine = "odm"
    legacy = runtime.legacy_queue_name(engine)
    stream = runtime.stream_name(engine)

    # Historisch: LPUSH + BRPOP => job-1 wird vor job-2 verarbeitet.
    redis_client.lpush(legacy, json.dumps({"job_id": "job-1"}))
    redis_client.lpush(legacy, json.dumps({"job_id": "job-2"}))

    runtime._ensure_group(redis_client, stream)
    assert runtime._migrate_legacy_queue(redis_client, engine) == 2
    assert redis_client.llen(legacy) == 0

    entries = redis_client.xrange(stream, min="-", max="+")
    ids = [json.loads(fields["payload"])["job_id"] for _, fields in entries]
    assert ids == ["job-1", "job-2"]


def test_reconcile_requeues_job_missing_from_redis(redis_client):
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])
    runtime.QUEUE_GROUP = "geophoto-workers-test"
    runtime.DB_PATH = DB_PATH

    dataset = store.create_dataset("Queue Recovery", None)
    job = store.create_job(dataset["id"], "odm", "preview", "rgb", {})
    store.update_job(
        job["id"],
        status="running",
        phase="processing",
        message="vor simuliertem Redis-Verlust",
    )

    stream = runtime.stream_name("odm")
    runtime._ensure_group(redis_client, stream)

    assert runtime._reconcile_jobs(
        redis_client,
        "odm",
        "recovery-worker",
    ) == 1
    assert redis_client.xlen(stream) == 1

    recovered_job = store.get_job(job["id"])
    assert recovered_job["status"] == "queued"
    assert recovered_job["phase"] == "recovery"

    _, fields = redis_client.xrange(stream, min="-", max="+")[0]
    payload = json.loads(fields["payload"])
    assert payload["job_id"] == job["id"]
    assert payload["profile"] == "preview"



def test_reconcile_requeues_artifact_job_missing_from_redis(
    redis_client,
):
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])
    runtime.QUEUE_GROUP = "geophoto-workers-test"
    runtime.DB_PATH = DB_PATH

    dataset = store.create_dataset("Artifact Queue Recovery", None)
    source = store.create_job(
        dataset["id"],
        "odm",
        "standard",
        "mapping",
        {},
    )
    artifact_job = store.create_artifact_job(
        source["id"],
        0,
        "pdal",
        "reproject",
        options={"target_crs": "EPSG:32632"},
        status="prepared",
    )
    store.update_artifact_job(
        artifact_job["id"],
        status="running",
        phase="reproject",
        message="vor simuliertem Redis-Verlust",
    )

    stream = runtime.stream_name("artifact:pdal")
    runtime._ensure_group(redis_client, stream)

    assert runtime._reconcile_artifact_jobs(
        redis_client,
        "pdal",
        "artifact-recovery-worker",
    ) == 1
    assert redis_client.xlen(stream) == 1
    assert redis_client.xlen(runtime.stream_name("pdal")) == 0

    recovered = store.get_artifact_job(artifact_job["id"])
    assert recovered["status"] == "queued"
    assert recovered["phase"] == "recovery"

    _, fields = redis_client.xrange(stream, min="-", max="+")[0]
    payload = json.loads(fields["payload"])
    assert payload == {
        "job_id": artifact_job["id"],
        "source_job_id": source["id"],
        "source_artifact_index": 0,
        "processor": "pdal",
        "operation": "reproject",
        "options": {"target_crs": "EPSG:32632"},
    }


def test_artifact_reconcile_cancels_without_requeue(redis_client):
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])
    runtime.QUEUE_GROUP = "geophoto-workers-test"
    runtime.DB_PATH = DB_PATH

    dataset = store.create_dataset("Artifact Cancel Recovery", None)
    source = store.create_job(
        dataset["id"],
        "odm",
        "standard",
        "mapping",
        {},
    )
    artifact_job = store.create_artifact_job(
        source["id"],
        0,
        "pdal",
        "reproject",
    )
    store.update_artifact_job(
        artifact_job["id"],
        status="cancel_requested",
    )

    stream = runtime.stream_name("artifact:pdal")
    runtime._ensure_group(redis_client, stream)

    assert runtime._reconcile_artifact_jobs(
        redis_client,
        "pdal",
        "artifact-recovery-worker",
    ) == 0
    assert redis_client.xlen(stream) == 0

    cancelled = store.get_artifact_job(artifact_job["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["phase"] == "cancelled"


def test_artifact_log_path_is_separate_from_dataset_jobs():
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])

    dataset_log = runtime._dataset_log_path("same-id")
    artifact_log = runtime._artifact_log_path("same-id")

    assert dataset_log != artifact_log
    assert dataset_log.as_posix().endswith("/jobs/same-id/worker.log")
    assert artifact_log.as_posix().endswith(
        "/artifact-jobs/same-id/worker.log"
    )


def test_artifact_payload_does_not_require_dataset_engine_fields():
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])
    runtime.DB_PATH = DB_PATH

    dataset = store.create_dataset("Artifact Payload", None)
    source = store.create_job(
        dataset["id"],
        "odm",
        "standard",
        "mapping",
        {},
    )
    artifact_job = store.create_artifact_job(
        source["id"],
        0,
        "pdal",
        "reproject",
        options={"target_crs": "EPSG:25832"},
    )

    with runtime.connect_db() as conn:
        row = conn.execute(
            "SELECT * FROM artifact_jobs WHERE id=?",
            (artifact_job["id"],),
        ).fetchone()

    payload = runtime._payload_from_artifact_job(row)
    assert payload["processor"] == "pdal"
    assert payload["operation"] == "reproject"
    assert payload["options"] == {"target_crs": "EPSG:25832"}
    assert "dataset_id" not in payload
    assert "engine" not in payload
