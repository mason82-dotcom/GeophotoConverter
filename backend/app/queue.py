from __future__ import annotations

import json
import os
from typing import Any

from redis import Redis
from redis.exceptions import ResponseError

from .config import REDIS_URL

STREAM_GROUP = os.getenv("GEOPHOTO_QUEUE_GROUP", "geophoto-workers")


def client() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)


def stream_name(engine: str) -> str:
    return f"geophoto:stream:{engine}"


def legacy_queue_name(engine: str) -> str:
    return f"geophoto:queue:{engine}"


def artifact_stream_name(processor: str) -> str:
    return f"geophoto:stream:artifact:{processor}"


def enqueue(engine: str, payload: dict) -> str:
    return str(
        client().xadd(
            stream_name(engine),
            {"payload": json.dumps(payload, separators=(",", ":"))},
        )
    )


def enqueue_artifact(processor: str, payload: dict) -> str:
    return str(
        client().xadd(
            artifact_stream_name(processor),
            {"payload": json.dumps(payload, separators=(",", ":"))},
        )
    )


def ping() -> bool:
    try:
        return bool(client().ping())
    except Exception:
        return False


def _pending_count(redis: Redis, stream: str) -> int:
    try:
        summary = redis.xpending(stream, STREAM_GROUP)
    except ResponseError as exc:
        if "NOGROUP" in str(exc):
            return 0
        raise

    if isinstance(summary, dict):
        return int(summary.get("pending", 0))
    if isinstance(summary, (list, tuple)) and summary:
        return int(summary[0])
    return 0


def worker_state(engine: str) -> dict[str, Any]:
    redis = client()
    raw = redis.get(f"geophoto:worker:{engine}")
    stream = stream_name(engine)
    pending = _pending_count(redis, stream)
    stream_depth = int(redis.xlen(stream))
    legacy_depth = int(redis.llen(legacy_queue_name(engine)))
    waiting = max(0, stream_depth - pending) + legacy_depth

    state: dict[str, Any] = {
        "engine": engine,
        "status": "offline",
        "queue_depth": waiting,
        "processing_depth": pending,
        "stream_depth": stream_depth,
        "legacy_queue_depth": legacy_depth,
    }
    if raw:
        try:
            state.update(json.loads(raw))
        except json.JSONDecodeError:
            state["status"] = "unknown"
    return state



def artifact_worker_state(processor: str) -> dict[str, Any]:
    redis = client()
    stream = artifact_stream_name(processor)
    pending = _pending_count(redis, stream)
    stream_depth = int(redis.xlen(stream))
    waiting = max(0, stream_depth - pending)
    raw = redis.get(f"geophoto:worker:artifact:{processor}")

    state: dict[str, Any] = {
        "processor": processor,
        "job_namespace": "artifact",
        "status": "offline",
        "queue_depth": waiting,
        "processing_depth": pending,
        "stream_depth": stream_depth,
    }
    if raw:
        try:
            state.update(json.loads(raw))
        except json.JSONDecodeError:
            state["status"] = "unknown"
    return state
