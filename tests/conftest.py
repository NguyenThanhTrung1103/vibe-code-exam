"""Pytest fixtures for Phase 01 — DB/Redis dependencies stubbed.

Real DB/Redis are only exercised in higher-phase tests; here we override the
FastAPI dependencies so unit tests stay hermetic.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_redis_dep, get_session
from app.main import create_app


class _FakeRedis:
    """Hermetic Redis stand-in supporting ping + minimal INCR/TTL/EXPIRE/pipeline.

    The pipeline contract emulates `redis-py`: methods enqueue results, and
    `execute()` returns them in order. Phase 09 rate-limit middleware uses
    `pipeline().incr().ttl().execute()` — keep the order in sync.
    """

    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy
        self._counts: dict[str, int] = {}
        self._ttls: dict[str, int] = {}
        self._pending: list[Any] = []

    def ping(self) -> bool:
        if not self.healthy:
            from redis.exceptions import RedisError

            raise RedisError("forced failure")
        return True

    # --- pipeline emulation --------------------------------------------------
    def pipeline(self) -> _FakeRedis:
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


class _FakeSession:
    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy

    def execute(self, *_args: Any, **_kwargs: Any) -> MagicMock:
        if not self.healthy:
            from sqlalchemy.exc import OperationalError

            raise OperationalError("SELECT 1", {}, Exception("forced failure"))
        return MagicMock()

    def close(self) -> None: ...


@pytest.fixture()
def app() -> FastAPI:
    return create_app()


@pytest.fixture()
def healthy_client(app: FastAPI) -> Generator[TestClient, None, None]:
    def _session_override() -> Generator[_FakeSession, None, None]:
        yield _FakeSession(healthy=True)

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_redis_dep] = lambda: _FakeRedis(healthy=True)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def degraded_client(app: FastAPI) -> Generator[TestClient, None, None]:
    def _session_override() -> Generator[_FakeSession, None, None]:
        yield _FakeSession(healthy=False)

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_redis_dep] = lambda: _FakeRedis(healthy=False)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
