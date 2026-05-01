"""Phase 03 integration tests against the real DB + Redis on the LXC.

Gated by `EXAM_PLATFORM_TEST_REAL_DB=1`. Each test uses a unique nonce
in emails / usernames to avoid colliding with seed data or other tests,
and cleans up its own DB rows + Redis rate-limit keys at teardown.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.db import SessionLocal, engine
from app.main import create_app
from app.models.audit import AuditLog
from app.models.enums import ActorType
from app.models.users import User
from app.redis_client import get_redis

pytestmark = pytest.mark.skipif(
    os.environ.get("EXAM_PLATFORM_TEST_REAL_DB") != "1",
    reason="real-DB integration tests gated by EXAM_PLATFORM_TEST_REAL_DB=1",
)


@pytest.fixture()
def app_real():
    return create_app()


@pytest.fixture()
def client(app_real):
    with TestClient(app_real) as c:
        yield c


@pytest.fixture()
def nonce() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def _flush_login_rate_limits():
    """Phase 09 — clear ALL rate-limit keys (rl:*) before each test."""
    r = get_redis()
    for key in r.scan_iter(match="rl:*"):
        r.delete(key)
    yield


@pytest.fixture(autouse=True)
def _cleanup_test_users():
    yield
    with SessionLocal() as s:
        # Wipe rows we created. Order matters: audit_logs row references no FK
        # to users (entity_id is just BIGINT), but we filter by entity_type and
        # the new_value JSONB containing our @test.local marker via the
        # `astext` column comparator (cast to text in PG).
        from sqlalchemy import cast
        from sqlalchemy.types import String

        s.execute(
            delete(AuditLog).where(
                AuditLog.entity_type.in_(("user", "auth")),
                cast(AuditLog.new_value, String).like("%@test.local%"),
            )
        )
        s.execute(delete(User).where(User.email.like("%@test.local")))
        s.commit()


def _csrf_pair(client: TestClient, path: str = "/auth/login") -> tuple[str, dict[str, str]]:
    resp = client.get(path)
    assert resp.status_code == 200
    token = resp.cookies.get("exam_csrf")
    assert token
    return token, {"exam_csrf": token}


def _register(client: TestClient, *, email: str, username: str, password: str = "Phase03-good-pw"):
    csrf, _ = _csrf_pair(client, "/auth/register")
    return client.post(
        "/auth/register",
        data={
            "email": email,
            "username": username,
            "password": password,
            "csrf_token": csrf,
        },
    )


def _login(
    client: TestClient,
    *,
    identifier: str,
    password: str = "Phase03-good-pw",
):
    csrf, _ = _csrf_pair(client, "/auth/login")
    return client.post(
        "/auth/login",
        data={
            "identifier": identifier,
            "password": password,
            "csrf_token": csrf,
        },
    )


# ---------------------------------------------------------------------------
# Flow tests
# ---------------------------------------------------------------------------


def test_register_creates_user_and_audit_row(client: TestClient, nonce: str) -> None:
    email = f"reg-{nonce}@test.local"
    resp = _register(client, email=email, username=f"reg{nonce}")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert "user_id" in body
    # Cookie set on register success
    assert "exam_session" in resp.cookies

    with SessionLocal() as s:
        user = s.execute(User.__table__.select().where(User.email == email)).fetchone()
        assert user is not None

        audits = list(
            s.execute(
                AuditLog.__table__.select()
                .where(AuditLog.action == AuditAction.USER_REGISTERED.value)
                .where(AuditLog.entity_type == "user")
            )
        )
        assert any(row.entity_id == body["user_id"] for row in audits)


def test_login_success_sets_cookie_and_audits(client: TestClient, nonce: str) -> None:
    email = f"login-{nonce}@test.local"
    _register(client, email=email, username=f"login{nonce}")
    client.cookies.clear()

    resp = _login(client, identifier=email)
    assert resp.status_code == 200, resp.text
    assert "exam_session" in resp.cookies

    with SessionLocal() as s:
        rows = list(
            s.execute(
                AuditLog.__table__.select()
                .where(AuditLog.action == AuditAction.LOGIN_SUCCEEDED.value)
                .where(AuditLog.actor_type == ActorType.user)
            )
        )
        assert len(rows) >= 1


def test_login_wrong_password_returns_401_and_audits_failure(
    client: TestClient, nonce: str
) -> None:
    email = f"fail-{nonce}@test.local"
    _register(client, email=email, username=f"fail{nonce}")
    client.cookies.clear()

    resp = _login(client, identifier=email, password="WRONG-pw-1234567")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid credentials"

    with SessionLocal() as s:
        rows = list(
            s.execute(
                AuditLog.__table__.select().where(AuditLog.action == AuditAction.LOGIN_FAILED.value)
            )
        )
        assert any((row.new_value or {}).get("identifier") == email for row in rows)


def test_logout_clears_cookie_and_audits(client: TestClient, nonce: str) -> None:
    email = f"out-{nonce}@test.local"
    _register(client, email=email, username=f"out{nonce}")
    client.cookies.clear()
    _login(client, identifier=email)
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    # Server clears the cookie via Set-Cookie max-age=0; httpx records that.
    set_cookies = resp.headers.get_list("set-cookie")
    assert any("exam_session=" in s and "Max-Age=0" in s for s in set_cookies)


def test_me_returns_current_user(client: TestClient, nonce: str) -> None:
    email = f"me-{nonce}@test.local"
    _register(client, email=email, username=f"me{nonce}")
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == email
    assert body["role"] == "student"


def test_me_anonymous_returns_401(client: TestClient) -> None:
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_csrf_post_without_token_rejected(client: TestClient, nonce: str) -> None:
    # Post directly without GET-ing the form first.
    resp = client.post(
        "/auth/register",
        data={
            "email": f"csrf-{nonce}@test.local",
            "username": f"csrf{nonce}",
            "password": "Phase03-good-pw",
            # no csrf_token, no csrf cookie
        },
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "invalid csrf"


def test_login_rate_limit_returns_429(client: TestClient, nonce: str) -> None:
    email = f"rl-{nonce}@test.local"
    _register(client, email=email, username=f"rl{nonce}")
    client.cookies.clear()

    # 5/min IP; 6th attempt should 429.
    last = None
    for _ in range(7):
        last = _login(client, identifier=email, password="WRONG-pw-1234567")
        if last.status_code == 429:
            break
    assert last is not None
    assert last.status_code == 429
    assert last.headers.get("retry-after")


def test_admin_audit_route_requires_admin(client: TestClient, nonce: str) -> None:
    # Anonymous → 401
    resp = client.get("/admin/audit.json")
    assert resp.status_code == 401

    # Student → 403
    email = f"student-{nonce}@test.local"
    _register(client, email=email, username=f"student{nonce}")
    resp = client.get("/admin/audit.json")
    assert resp.status_code == 403

    # Promote to admin directly in DB.
    with SessionLocal() as s:
        from app.models.enums import UserRole

        u = s.execute(User.__table__.select().where(User.email == email)).fetchone()
        s.execute(User.__table__.update().where(User.id == u.id).values(role=UserRole.admin.value))
        s.commit()

    resp = client.get("/admin/audit.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "rows" in body and "total" in body


def test_audit_writer_rolls_back_with_outer_transaction(nonce: str) -> None:
    """Audit row written via the helper rolls back when the outer tx rolls back."""
    with engine.connect() as conn:
        outer_tx = conn.begin()
        from sqlalchemy.orm import Session

        session = Session(bind=conn, autoflush=False)

        before = list(session.execute(AuditLog.__table__.select().where(AuditLog.reason == nonce)))
        assert before == []

        write_audit_log(
            session,
            actor_type=ActorType.system,
            actor_id=None,
            action=AuditAction.USER_REGISTERED,
            entity_type="user",
            entity_id=None,
            reason=nonce,
        )
        session.flush()

        mid = list(session.execute(AuditLog.__table__.select().where(AuditLog.reason == nonce)))
        assert len(mid) == 1, "audit row should exist inside the open transaction"

        outer_tx.rollback()
        session.close()

    with SessionLocal() as s:
        after = list(s.execute(AuditLog.__table__.select().where(AuditLog.reason == nonce)))
    assert after == [], "audit row must be gone after outer rollback"


def test_session_rotates_on_login(client: TestClient, nonce: str) -> None:
    email = f"rot-{nonce}@test.local"
    _register(client, email=email, username=f"rot{nonce}")
    cookie_after_register = client.cookies.get("exam_session")
    assert cookie_after_register is not None

    client.cookies.clear()
    _login(client, identifier=email)
    cookie_after_login = client.cookies.get("exam_session")
    assert cookie_after_login is not None
    # iat/sid randomness → different signed token
    assert cookie_after_register != cookie_after_login
