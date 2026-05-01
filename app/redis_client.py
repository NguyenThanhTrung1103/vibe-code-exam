"""Singleton Redis client wrapper.

Phase 01 only needs a `ping()` for `/healthz` and a placeholder for RQ
queues used in later phases.
"""

from __future__ import annotations

from functools import lru_cache

from redis import Redis

from app.config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    settings = get_settings()
    # Short timeouts so /healthz degrades quickly when Redis is unreachable.
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
