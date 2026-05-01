"""Phase 09 — RateLimit dependency unit tests using a fake Redis."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.deps import get_redis_dep
from app.security.rate_limits import RateLimit


class _MemoryRedis:
    """Tiny in-memory replacement supporting INCR/TTL/EXPIRE/pipeline.

    `_ttls` deliberately uses an underscore prefix so it doesn't clash with
    the `ttl(key)` method called by the production rate-limit code.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._ttls: dict[str, int] = {}
        self._pending: list[Any] = []

    def pipeline(self) -> _MemoryRedis:
        self._pending = []
        return self

    def incr(self, key: str) -> None:
        self._counts[key] = self._counts.get(key, 0) + 1
        self._pending.append(self._counts[key])

    def ttl(self, key: str) -> None:
        self._pending.append(self._ttls.get(key, -2))

    def execute(self) -> list[Any]:
        out, self._pending = self._pending, []
        return out

    def expire(self, key: str, seconds: int) -> None:
        self._ttls[key] = seconds


class _BrokenRedis:
    def pipeline(self) -> _BrokenRedis:
        return self

    def incr(self, _key: str) -> None: ...
    def ttl(self, _key: str) -> None: ...
    def execute(self) -> list[Any]:
        raise RedisError("forced failure")

    def expire(self, _key: str, _seconds: int) -> None: ...


def _build_app(redis_client: Any) -> FastAPI:
    rl = RateLimit("test", limit=2, window_s=60, scope="ip")
    app = FastAPI()

    @app.get("/", dependencies=[Depends(rl)])
    def _handler() -> dict[str, str]:
        return {"ok": "yes"}

    def _override() -> Generator[Any, None, None]:
        yield redis_client

    app.dependency_overrides[get_redis_dep] = _override
    return app


def test_under_limit_allows() -> None:
    app = _build_app(_MemoryRedis())
    with TestClient(app) as c:
        for _ in range(2):
            assert c.get("/").status_code == 200


def test_over_limit_returns_429_with_retry_after() -> None:
    app = _build_app(_MemoryRedis())
    with TestClient(app) as c:
        for _ in range(2):
            assert c.get("/").status_code == 200
        r = c.get("/")
        assert r.status_code == 429
        assert int(r.headers.get("retry-after", "0")) > 0


def test_redis_failure_fails_closed() -> None:
    app = _build_app(_BrokenRedis())
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 503
        assert r.headers.get("retry-after") == "30"


@pytest.mark.parametrize("scope", ["user", "ip", "admin"])
def test_scope_label_is_accepted(scope: str) -> None:
    rl = RateLimit("scope", limit=10, window_s=60, scope=scope)
    assert rl.scope == scope
