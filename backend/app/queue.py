from __future__ import annotations

import json

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
