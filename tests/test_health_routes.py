"""Phase 10 — health route hermetic tests (`/healthz`, `/readyz`)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient


def test_healthz_ok(healthy_client: TestClient) -> None:
    r = healthy_client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "db": "ok", "redis": "ok"}


def test_healthz_degraded(degraded_client: TestClient) -> None:
    r = degraded_client.get("/healthz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["db"] == "down"
    assert body["redis"] == "down"


def _patch_migration(status: str, *, current: str | None, head: str | None) -> Any:
    return patch(
        "app.routers.health._migration_state",
        return_value=(status, current, head),
    )


def test_readyz_ok_when_migrations_at_head(healthy_client: TestClient) -> None:
    with _patch_migration("ok", current="abc123", head="abc123"):
        r = healthy_client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["migrations"] == {"status": "ok", "current": "abc123", "head": "abc123"}


def test_readyz_not_ready_when_db_down(degraded_client: TestClient) -> None:
    with _patch_migration("ok", current="abc123", head="abc123"):
        r = degraded_client.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["db"] == "down"


def test_readyz_not_ready_when_migration_behind(healthy_client: TestClient) -> None:
    with _patch_migration("behind", current="abc123", head="def456"):
        r = healthy_client.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["migrations"]["status"] == "behind"


def test_readyz_not_ready_when_migration_unknown(healthy_client: TestClient) -> None:
    with _patch_migration("unknown", current=None, head=None):
        r = healthy_client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["migrations"]["status"] == "unknown"
