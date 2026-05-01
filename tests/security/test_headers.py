"""Phase 09 — security header coverage on every response."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_security_headers_on_health(healthy_client: TestClient) -> None:
    r = healthy_client.get("/healthz")
    assert r.status_code == 200
    h = r.headers
    assert "default-src 'self'" in h["content-security-policy"]
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY"
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "geolocation=()" in h["permissions-policy"]
    # HSTS is gated on prod; local env must not emit it.
    assert "strict-transport-security" not in h


def test_request_id_round_trip(healthy_client: TestClient) -> None:
    r = healthy_client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"


def test_request_id_generated_when_absent(healthy_client: TestClient) -> None:
    r = healthy_client.get("/healthz")
    rid = r.headers.get("x-request-id")
    assert rid and len(rid) >= 8


def test_security_headers_on_404(healthy_client: TestClient) -> None:
    r = healthy_client.get("/no-such-page")
    assert r.status_code == 404
    # Even 404 must carry the security headers — defense-in-depth.
    assert "content-security-policy" in r.headers
    assert r.headers["x-frame-options"] == "DENY"
