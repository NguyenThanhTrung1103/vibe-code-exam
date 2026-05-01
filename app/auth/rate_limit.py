"""Redis-backed sliding-window rate limit for login attempts.

Two scopes are checked together:
  * per IP — 5 attempts / 60 s
  * per identifier (lowercased email or username) — 20 attempts / 3600 s

If Redis is unreachable, login fails closed: caller raises an HTTP error
rather than allowing unlimited attempts.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from redis import Redis
from redis.exceptions import RedisError

log = structlog.get_logger("auth.rate_limit")


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int | None = None
    reason: str | None = None


# (scope, limit, window_seconds)
LOGIN_PER_IP = ("login_ip", 5, 60)
LOGIN_PER_IDENT = ("login_ident", 20, 60 * 60)


def _key(scope: str, value: str) -> str:
    return f"rl:{scope}:{value}"


def _incr_with_window(redis: Redis, key: str, window: int) -> tuple[int, int]:
    """Returns (current_count, ttl_seconds) — TTL is the window if newly set."""
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.ttl(key)
    count_raw, ttl_raw = pipe.execute()
    count = int(count_raw)
    ttl = int(ttl_raw)
    if ttl < 0:
        # First hit (or expired) — set the window now.
        redis.expire(key, window)
        ttl = window
    return count, ttl


def check_login_rate_limit(
    redis: Redis,
    *,
    ip: str,
    identifier: str | None,
) -> RateLimitResult:
    """Check + increment counters atomically. Returns deny if either limit is hit."""
    try:
        # IP scope (always counted)
        ip_scope, ip_limit, ip_window = LOGIN_PER_IP
        ip_count, ip_ttl = _incr_with_window(redis, _key(ip_scope, ip), ip_window)
        if ip_count > ip_limit:
            return RateLimitResult(allowed=False, retry_after_seconds=ip_ttl, reason="ip_limit")

        # Identifier scope (only if we have one — anonymous attempts skip)
        if identifier:
            ident_scope, ident_limit, ident_window = LOGIN_PER_IDENT
            ident_count, ident_ttl = _incr_with_window(
                redis, _key(ident_scope, identifier.strip().lower()), ident_window
            )
            if ident_count > ident_limit:
                return RateLimitResult(
                    allowed=False,
                    retry_after_seconds=ident_ttl,
                    reason="identifier_limit",
                )

        return RateLimitResult(allowed=True)

    except (RedisError, OSError) as exc:
        # Redis is the source of truth for rate limiting. If we can't talk
        # to it, fail closed: refuse the login attempt rather than allow
        # unlimited tries. Operator alert via structured log.
        log.error("rate_limit_redis_unavailable", error_type=type(exc).__name__)
        return RateLimitResult(
            allowed=False,
            retry_after_seconds=30,
            reason="rate_limit_unavailable",
        )
