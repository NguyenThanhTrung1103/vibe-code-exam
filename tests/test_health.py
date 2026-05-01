"""Healthcheck contract tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_ok_when_dependencies_up(healthy_client: TestClient) -> None:
    response = healthy_client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "db": "ok", "redis": "ok"}


def test_healthz_returns_503_when_dependencies_down(degraded_client: TestClient) -> None:
    response = degraded_client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "down"
    assert body["redis"] == "down"


def test_request_id_header_present(healthy_client: TestClient) -> None:
    response = healthy_client.get("/healthz")
    assert "x-request-id" in {h.lower() for h in response.headers}
