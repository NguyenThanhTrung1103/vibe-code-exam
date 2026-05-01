"""Generic per-route rate limit — Redis sliding-window dependency factory.

Usage::

    rl = RateLimit("attempt_start", limit=30, window_s=60, scope="user")
    @router.post("/attempts/start", dependencies=[Depends(rl)])
    def start_attempt(...): ...

* `scope="user"` keys on `request.state.user_id` if available, else IP.
* `scope="ip"` keys on the client IP from `request.client.host`.
* `scope="admin"` is identical to `"user"` semantically; the label is for
  log/key separation.

If Redis is unreachable the dependency fails closed (raises 503) — better
than silently letting through unlimited mutations.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from fastapi import HTTPException, Request, status
from redis import Redis
from redis.exceptions import RedisError

from app.deps import RedisDep

log = structlog.get_logger("security.rate_limits")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _principal(request: Request, scope: str) -> str:
    if scope == "ip":
        return _client_ip(request)
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None:
        return f"u:{user_id}"
    # Fall back to IP if no user resolved yet — mirrors login pre-session
    # where there's no user context. Keeps the limit useful before auth.
    return f"ip:{_client_ip(request)}"


def _incr_with_window(redis: Redis, key: str, window_s: int) -> tuple[int, int]:
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.ttl(key)
    count_raw, ttl_raw = pipe.execute()
    count = int(count_raw)
    ttl = int(ttl_raw)
    if ttl < 0:
        redis.expire(key, window_s)
        ttl = window_s
    return count, ttl


@dataclass(frozen=True)
class RateLimit:
    """Configurable Redis-backed sliding-window rate limit dependency."""

    name: str
    limit: int
    window_s: int
    scope: str = "user"  # "user" | "ip" | "admin"

    def __call__(self, request: Request, redis: RedisDep) -> None:
        principal = _principal(request, self.scope)
        key = f"rl:{self.name}:{principal}"
        try:
            count, ttl = _incr_with_window(redis, key, self.window_s)
        except (RedisError, OSError) as exc:
            log.error(
                "rate_limit_redis_unavailable",
                name=self.name,
                error_type=type(exc).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="rate limit backend unavailable",
                headers={"Retry-After": "30"},
            ) from exc

        if count > self.limit:
            log.warning(
                "rate_limited",
                name=self.name,
                principal=principal,
                count=count,
                limit=self.limit,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many requests",
                headers={"Retry-After": str(max(ttl, 1))},
            )


# Prebuilt instances — the Phase 09 plan rate-limit table.
RL_REGISTER = RateLimit("auth_register", limit=5, window_s=3600, scope="ip")
RL_ATTEMPT_START = RateLimit("attempt_start", limit=30, window_s=60, scope="user")
RL_ATTEMPT_ANSWER = RateLimit("attempt_answer", limit=60, window_s=60, scope="user")
RL_QUESTION_REPORT = RateLimit("question_report", limit=30, window_s=3600, scope="user")
RL_ADMIN_IMPORT = RateLimit("admin_import", limit=5, window_s=3600, scope="admin")
RL_PUBLIC_SEARCH = RateLimit("public_search", limit=60, window_s=60, scope="ip")
RL_PUBLIC_LANDING = RateLimit("public_landing", limit=60, window_s=60, scope="ip")


__all__ = [
    "RL_ADMIN_IMPORT",
    "RL_ATTEMPT_ANSWER",
    "RL_ATTEMPT_START",
    "RL_PUBLIC_LANDING",
    "RL_PUBLIC_SEARCH",
    "RL_QUESTION_REPORT",
    "RL_REGISTER",
    "RateLimit",
]
