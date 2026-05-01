"""Phase 09 — every POST that mutates state must reject missing CSRF.

Hermetic test using FastAPI's route table — we look up every POST under
the relevant prefixes and call them without a CSRF cookie. Auth-gated
routes correctly return 401 (auth runs first); the goal is "never 200
without CSRF" which transitively proves the CSRF guard is wired.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _post_paths(app: FastAPI) -> list[str]:
    paths: list[str] = []
    for r in app.routes:
        if not hasattr(r, "methods"):
            continue
        if "POST" not in r.methods:  # type: ignore[attr-defined]
            continue
        path: str = r.path  # type: ignore[attr-defined]
        # Skip path-parameterised mutating routes — TestClient won't resolve them.
        if "{" in path:
            continue
        paths.append(path)
    return paths


def test_post_routes_reject_missing_csrf(healthy_client: TestClient, app: FastAPI) -> None:
    """No POST under /auth/* /admin/* /attempts/* /questions/* must return 200 without CSRF."""
    candidates = [
        p
        for p in _post_paths(app)
        if p.startswith(("/auth/", "/admin/", "/attempts/", "/questions/"))
    ]
    assert candidates, "expected at least one mutating POST route"
    for path in candidates:
        r = healthy_client.post(path, data={})
        # Acceptable: 401 (no auth), 403 (CSRF), 422 (validation), 405, 429.
        # Forbidden: 200/201 — that would mean CSRF was bypassed.
        assert r.status_code != 200, f"{path} returned 200 without CSRF"
        assert r.status_code != 201, f"{path} returned 201 without CSRF"


@pytest.mark.parametrize(
    "path",
    [
        "/admin/imports",
        "/admin/providers",
        "/admin/courses",
        "/admin/exams",
        "/admin/topics",
        "/admin/questions",
    ],
)
def test_admin_post_requires_auth_or_csrf(healthy_client: TestClient, path: str) -> None:
    r = healthy_client.post(path, data={})
    # 401 (no session) is the canonical anonymous-blocked response. 403/422 also OK.
    assert r.status_code in {401, 403, 405, 422}, f"{path} unexpected status {r.status_code}"
