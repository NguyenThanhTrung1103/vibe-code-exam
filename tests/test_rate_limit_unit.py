"""Rate-limit unit tests with an in-memory fake Redis.

Covers the happy path, IP-scope and identifier-scope thresholds, and the
"Redis unavailable" → fail-closed branch.
"""

from __future__ import annotations

from typing import Any

from redis.exceptions import ConnectionError as RedisConnectionError

from app.auth.rate_limit import (
    LOGIN_PER_IDENT,
    LOGIN_PER_IP,
    check_login_rate_limit,
)


class _FakeRedisPipeline:
    def __init__(self, store: dict[str, int], expirations: dict[str, int]) -> None:
        self._store = store
        self._expirations = expirations
        self._ops: list[tuple[str, str]] = []

    def incr(self, key: str) -> _FakeRedisPipeline:
        self._ops.append(("incr", key))
        return self

    def ttl(self, key: str) -> _FakeRedisPipeline:
        self._ops.append(("ttl", key))
        return self

    def execute(self) -> list[Any]:
        results: list[Any] = []
        for op, key in self._ops:
            if op == "incr":
                self._store[key] = self._store.get(key, 0) + 1
                results.append(self._store[key])
            elif op == "ttl":
                results.append(self._expirations.get(key, -2))
        return results


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    def pipeline(self) -> _FakeRedisPipeline:
        return _FakeRedisPipeline(self.store, self.expirations)

    def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True


class _ExplodingRedis:
    def pipeline(self) -> Any:
        raise RedisConnectionError("simulated outage")


def test_rate_limit_allows_below_threshold() -> None:
    r = _FakeRedis()
    for _ in range(LOGIN_PER_IP[1]):  # exactly the limit
        result = check_login_rate_limit(r, ip="127.0.0.1", identifier="alice")
        assert result.allowed is True


def test_rate_limit_denies_when_ip_threshold_exceeded() -> None:
    r = _FakeRedis()
    for _ in range(LOGIN_PER_IP[1]):
        check_login_rate_limit(r, ip="127.0.0.1", identifier="alice")
    # The next attempt should be blocked.
    result = check_login_rate_limit(r, ip="127.0.0.1", identifier="alice")
    assert result.allowed is False
    assert result.reason == "ip_limit"
    assert result.retry_after_seconds is not None
    assert result.retry_after_seconds > 0


def test_rate_limit_denies_when_identifier_threshold_exceeded() -> None:
    r = _FakeRedis()
    # Different IPs, same identifier — only the identifier scope should fire.
    for i in range(LOGIN_PER_IDENT[1]):
        # Use a unique IP each time so the IP scope never fills.
        check_login_rate_limit(r, ip=f"10.0.0.{i}", identifier="alice")
    result = check_login_rate_limit(r, ip="10.0.0.99", identifier="alice")
    assert result.allowed is False
    assert result.reason == "identifier_limit"


def test_rate_limit_fails_closed_when_redis_unreachable() -> None:
    result = check_login_rate_limit(_ExplodingRedis(), ip="127.0.0.1", identifier="bob")
    assert result.allowed is False
    assert result.reason == "rate_limit_unavailable"
    assert result.retry_after_seconds == 30
