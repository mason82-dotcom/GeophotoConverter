from __future__ import annotations

import json
from typing import Any

from redis import Redis

from .config import REDIS_URL


def client() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)


def enqueue(engine: str, payload: dict) -> None:
    client().lpush(f"geophoto:queue:{engine}", json.dumps(payload))


def ping() -> bool:
    try:
        return bool(client().ping())
    except Exception:
        return False


def worker_state(engine: str) -> dict[str, Any]:
    c = client()
    raw = c.get(f"geophoto:worker:{engine}")
    state: dict[str, Any] = {
        "engine": engine,
        "status": "offline",
        "queue_depth": c.llen(f"geophoto:queue:{engine}"),
    }
    if raw:
        try:
            state.update(json.loads(raw))
        except json.JSONDecodeError:
            state["status"] = "unknown"
    return state
