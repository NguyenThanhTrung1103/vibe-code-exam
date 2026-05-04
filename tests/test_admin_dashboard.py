"""Admin dashboard entrypoint GET /admin."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_admin_dashboard_redirects_when_not_logged_in() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/admin", follow_redirects=False, headers={"Accept": "text/html"})
    assert r.status_code == 303
    loc = r.headers.get("location", "")
    assert "login" in loc
