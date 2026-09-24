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


def _artifact_source_job() -> dict:
    dataset = store.create_dataset("Artifact Queue", None)
    job = store.create_job(dataset["id"], "odm", "standard", "mapping", {})
    store.update_job(
        job["id"],
        status="completed",
        progress=100,
        artifacts=[
            {
                "type": "point_cloud_laz",
                "name": "cloud.laz",
                "relative_path": "jobs/source/cloud.laz",
                "size_bytes": 123,
            }
        ],
    )
    result = store.get_job(job["id"])
    assert result is not None
    return result


def test_artifact_backend_uses_separate_stream_and_payload(monkeypatch):
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])
    runtime.DB_PATH = DB_PATH

    source = _artifact_source_job()
    artifact_job = store.create_artifact_job(
        source["id"],
        0,
        "pdal",
        "reproject",
        options={"target_crs": "EPSG:32633"},
        status="queued",
    )

    backend = runtime.ArtifactJobBackend()
    rows = backend.recovery_rows("pdal")
    assert len(rows) == 1

    payload = backend.payload(rows[0])
    assert payload == {
        "job_id": artifact_job["id"],
        "artifact_job_id": artifact_job["id"],
        "source_job_id": source["id"],
        "source_artifact_index": 0,
        "processor": "pdal",
        "operation": "reproject",
        "options": {"target_crs": "EPSG:32633"},
    }
    assert backend.stream_name("pdal") == "geophoto:stream:artifact:pdal"
    assert backend.legacy_queue_name("pdal") is None
    assert (
        backend.worker_state_key("pdal")
        == "geophoto:worker:artifact:pdal"
    )
    assert backend.log_path(artifact_job["id"]).parts[-3:] == (
        "artifact-jobs",
        artifact_job["id"],
        "worker.log",
    )


def test_artifact_reconcile_requeues_only_artifact_jobs(
    redis_client,
):
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])
    runtime.QUEUE_GROUP = "geophoto-workers-artifact-test"
    runtime.DB_PATH = DB_PATH

    dataset = store.create_dataset("Dataset Queue Separation", None)
    dataset_job = store.create_job(
        dataset["id"],
        "odm",
        "preview",
        "mapping",
        {},
    )
    store.update_job(dataset_job["id"], status="running")

    source = _artifact_source_job()
    artifact_job = store.create_artifact_job(
        source["id"],
        0,
        "pdal",
        "reproject",
        options={"target_crs": "EPSG:32633"},
        status="running",
    )

    backend = runtime.ArtifactJobBackend()
    stream = backend.stream_name("pdal")
    runtime._ensure_group(redis_client, stream)

    assert runtime._reconcile_backend_jobs(
        redis_client,
        "pdal",
        "artifact-worker",
        backend,
    ) == 1

    assert redis_client.xlen(stream) == 1
    assert redis_client.xlen(runtime.stream_name("odm")) == 0

    _, fields = redis_client.xrange(stream, min="-", max="+")[0]
    payload = json.loads(fields["payload"])
    assert payload["job_id"] == artifact_job["id"]
    assert payload["artifact_job_id"] == artifact_job["id"]
    assert payload["source_job_id"] == source["id"]

    updated_artifact = store.get_artifact_job(artifact_job["id"])
    assert updated_artifact["status"] == "queued"
    assert updated_artifact["phase"] == "recovery"

    untouched_dataset = store.get_job(dataset_job["id"])
    assert untouched_dataset["status"] == "running"


def test_artifact_reconcile_confirms_prestart_cancel_without_enqueue(
    redis_client,
):
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])
    runtime.QUEUE_GROUP = "geophoto-workers-artifact-cancel-test"
    runtime.DB_PATH = DB_PATH

    source = _artifact_source_job()
    artifact_job = store.create_artifact_job(
        source["id"],
        0,
        "pdal",
        "reproject",
        status="cancel_requested",
    )

    backend = runtime.ArtifactJobBackend()
    stream = backend.stream_name("pdal")
    runtime._ensure_group(redis_client, stream)

    assert runtime._reconcile_backend_jobs(
        redis_client,
        "pdal",
        "artifact-worker",
        backend,
    ) == 0
    assert redis_client.xlen(stream) == 0

    cancelled = store.get_artifact_job(artifact_job["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["phase"] == "cancelled"


def test_artifact_attempt_keys_cannot_collide_with_dataset_jobs():
    runtime = _load_worker_runtime(Path(__file__).resolve().parents[2])
    artifact = runtime.ArtifactJobBackend()

    assert artifact.attempt_key("pdal", "1-0") == (
        "geophoto:attempt:artifact:pdal:1-0"
    )
    assert artifact.attempt_key("pdal", "1-0") != runtime._attempt_key(
        "pdal",
        "1-0",
    )
