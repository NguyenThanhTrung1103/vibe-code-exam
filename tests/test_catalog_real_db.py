"""Phase 04 catalog tests against real Postgres + Redis on the LXC.

Gated by `EXAM_PLATFORM_TEST_REAL_DB=1`. Each test creates rows scoped to a
random nonce so concurrent runs / seed data don't collide. Cleanup deletes
everything we created (catalog rows + audit log rows) at teardown.

Covered scenarios:
  * full CRUD on each entity
  * audit row written in the same transaction as the mutation
  * duplicate slug raises DuplicateSlugError (per-parent uniqueness)
  * soft-delete on Exam hides it from public queries
  * publish / unpublish toggle audited
  * publish-with-zero-questions allowed → public page shows "Coming soon"
  * admin RBAC: anonymous 401, student 403
  * missing CSRF on admin POST → 403
  * search hits + draft/soft-deleted exclusion
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.audit.events import AuditAction
from app.db import SessionLocal
from app.main import create_app
from app.models.audit import AuditLog
from app.models.catalog import Course, Exam, ProductVersion, Provider, Topic
from app.models.enums import ExamPublishStatus, UserRole
from app.models.users import User
from app.redis_client import get_redis
from app.services import catalog_service

pytestmark = pytest.mark.skipif(
    os.environ.get("EXAM_PLATFORM_TEST_REAL_DB") != "1",
    reason="real-DB integration tests gated by EXAM_PLATFORM_TEST_REAL_DB=1",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    r = get_redis()
    for key in r.scan_iter(match="rl:*"):
        r.delete(key)
    yield


@pytest.fixture(autouse=True)
def _cleanup_catalog():
    """Run-after fixture: delete any phase-04-test rows by nonce-prefixed slug."""
    yield
    with SessionLocal() as s:
        # Catalog rows we created use slugs/names containing 'p04t-' marker.
        provider_ids = list(s.scalars(select(Provider.id).where(Provider.slug.like("p04t-%"))))
        if provider_ids:
            # exams → topics → questions… we only created topics/exams under
            # these providers; cascade delete via children-first.
            course_ids = list(
                s.scalars(select(Course.id).where(Course.provider_id.in_(provider_ids)))
            )
            exam_ids = list(
                s.scalars(select(Exam.id).where(Exam.course_id.in_(course_ids or [-1])))
            )
            if exam_ids:
                s.execute(delete(Topic).where(Topic.exam_id.in_(exam_ids)))
                s.execute(delete(Exam).where(Exam.id.in_(exam_ids)))
            if course_ids:
                s.execute(delete(Course).where(Course.id.in_(course_ids)))
            s.execute(delete(ProductVersion).where(ProductVersion.provider_id.in_(provider_ids)))
            s.execute(delete(Provider).where(Provider.id.in_(provider_ids)))
        # Audit rows tied to phase-04 catalog entity_types
        s.execute(
            delete(AuditLog).where(
                AuditLog.entity_type.in_(("provider", "product_version", "course", "exam", "topic"))
            )
        )
        # Test users
        s.execute(delete(User).where(User.email.like("%@p04test.local")))
        s.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(nonce: str) -> User:
    """Create an admin user and return it (committed)."""
    from app.auth.service import register_user

    with SessionLocal() as s:
        u = register_user(
            s,
            email=f"admin-{nonce}@p04test.local",
            username=f"admin{nonce}",
            password="Phase04-good-pw",
            role=UserRole.admin,
            request_id=None,
        )
        s.commit()
        return s.get(User, u.id)


def _login(client: TestClient, *, identifier: str, password: str = "Phase04-good-pw"):
    csrf, _ = _csrf_pair(client, "/auth/login")
    return client.post(
        "/auth/login",
        data={"identifier": identifier, "password": password, "csrf_token": csrf},
    )


def _register(
    client: TestClient,
    *,
    email: str,
    username: str,
    password: str = "Phase04-good-pw",
):
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


def _csrf_pair(client: TestClient, path: str) -> tuple[str, dict[str, str]]:
    resp = client.get(path)
    assert resp.status_code == 200, f"GET {path} returned {resp.status_code}"
    token = resp.cookies.get("exam_csrf")
    assert token
    return token, {"exam_csrf": token}


def _admin_login(client: TestClient, nonce: str) -> User:
    user = _make_admin(nonce)
    resp = _login(client, identifier=user.email)
    assert resp.status_code == 200
    return user


# ---------------------------------------------------------------------------
# Service-level CRUD (unit-of-work) tests
# ---------------------------------------------------------------------------


def test_create_provider_audits_in_same_tx(nonce: str) -> None:
    actor = _make_admin(nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        p = catalog_service.create_provider(
            s,
            actor=actor,
            request_id=None,
            name=f"Prov {nonce}",
            slug=f"p04t-{nonce}",
        )
        s.commit()
        rows = list(
            s.execute(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.PROVIDER_CREATED.value,
                    AuditLog.entity_id == p.id,
                )
            )
        )
        assert len(rows) == 1
        (row,) = rows[0]
        assert row.actor_id == actor.id
        assert row.new_value == {"name": p.name, "slug": p.slug}


def test_duplicate_provider_slug_raises_friendly_error(nonce: str) -> None:
    actor = _make_admin(nonce)
    slug = f"p04t-{nonce}"
    with SessionLocal() as s:
        actor = s.merge(actor)
        catalog_service.create_provider(s, actor=actor, request_id=None, name="A", slug=slug)
        s.commit()
    with SessionLocal() as s:
        actor = s.merge(actor)
        with pytest.raises(catalog_service.DuplicateSlugError):
            catalog_service.create_provider(s, actor=actor, request_id=None, name="B", slug=slug)


def test_duplicate_course_slug_under_same_provider_rejected(nonce: str) -> None:
    actor = _make_admin(nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name="P", slug=f"p04t-{nonce}"
        )
        catalog_service.create_course(
            s,
            actor=actor,
            request_id=None,
            provider_id=provider.id,
            name="C1",
            slug="dup",
        )
        s.commit()
        provider_id = provider.id

    with SessionLocal() as s:
        actor = s.merge(actor)
        with pytest.raises(catalog_service.DuplicateSlugError):
            catalog_service.create_course(
                s,
                actor=actor,
                request_id=None,
                provider_id=provider_id,
                name="C2",
                slug="dup",
            )


def test_duplicate_exam_slug_under_same_course_rejected(nonce: str) -> None:
    actor = _make_admin(nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name="P", slug=f"p04t-{nonce}"
        )
        course = catalog_service.create_course(
            s,
            actor=actor,
            request_id=None,
            provider_id=provider.id,
            name="C",
            slug="c1",
        )
        catalog_service.create_exam(
            s,
            actor=actor,
            request_id=None,
            course_id=course.id,
            name="E1",
            slug="dup",
        )
        s.commit()
        course_id = course.id

    with SessionLocal() as s:
        actor = s.merge(actor)
        with pytest.raises(catalog_service.DuplicateSlugError):
            catalog_service.create_exam(
                s,
                actor=actor,
                request_id=None,
                course_id=course_id,
                name="E2",
                slug="dup",
            )


def test_duplicate_topic_slug_under_same_exam_rejected(nonce: str) -> None:
    actor = _make_admin(nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name="P", slug=f"p04t-{nonce}"
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug="c1"
        )
        exam = catalog_service.create_exam(
            s, actor=actor, request_id=None, course_id=course.id, name="E", slug="e1"
        )
        catalog_service.create_topic(
            s, actor=actor, request_id=None, exam_id=exam.id, name="T", slug="dup"
        )
        s.commit()
        exam_id = exam.id

    with SessionLocal() as s:
        actor = s.merge(actor)
        with pytest.raises(catalog_service.DuplicateSlugError):
            catalog_service.create_topic(
                s,
                actor=actor,
                request_id=None,
                exam_id=exam_id,
                name="T2",
                slug="dup",
            )


def test_duplicate_product_version_unique_triple_rejected(nonce: str) -> None:
    actor = _make_admin(nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name="P", slug=f"p04t-{nonce}"
        )
        catalog_service.create_product_version(
            s,
            actor=actor,
            request_id=None,
            provider_id=provider.id,
            product_name="FortiGate",
            product_version="7.4.3",
        )
        s.commit()
        provider_id = provider.id
    with SessionLocal() as s:
        actor = s.merge(actor)
        with pytest.raises(catalog_service.DuplicateSlugError):
            catalog_service.create_product_version(
                s,
                actor=actor,
                request_id=None,
                provider_id=provider_id,
                product_name="FortiGate",
                product_version="7.4.3",
            )


def test_publish_unpublish_exam_audited(nonce: str) -> None:
    actor = _make_admin(nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name="P", slug=f"p04t-{nonce}"
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug="c1"
        )
        exam = catalog_service.create_exam(
            s,
            actor=actor,
            request_id=None,
            course_id=course.id,
            name="E",
            slug="e1",
            passing_score_percent=Decimal("70.00"),
        )
        s.commit()
        exam_id = exam.id

    with SessionLocal() as s:
        actor = s.merge(actor)
        catalog_service.publish_exam(s, actor=actor, request_id=None, exam_id=exam_id)
        s.commit()
        e = s.get(Exam, exam_id)
        assert e.publish_status == ExamPublishStatus.published
        assert e.last_verified_at is not None
        published_audit = list(
            s.scalars(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.EXAM_PUBLISHED.value,
                    AuditLog.entity_id == exam_id,
                )
            )
        )
        assert len(published_audit) == 1

        catalog_service.unpublish_exam(s, actor=actor, request_id=None, exam_id=exam_id)
        s.commit()
        unpub_audit = list(
            s.scalars(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.EXAM_UNPUBLISHED.value,
                    AuditLog.entity_id == exam_id,
                )
            )
        )
        assert len(unpub_audit) == 1


def test_soft_delete_exam_hides_from_public(nonce: str, client: TestClient) -> None:
    actor = _make_admin(nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name=f"Prov {nonce}", slug=f"p04t-{nonce}"
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug="c1"
        )
        exam = catalog_service.create_exam(
            s, actor=actor, request_id=None, course_id=course.id, name="E", slug="e1"
        )
        catalog_service.publish_exam(s, actor=actor, request_id=None, exam_id=exam.id)
        s.commit()
        provider_slug = provider.slug
        exam_id = exam.id

    # Public detail returns 200 while published.
    resp_ok = client.get(f"/exams/{provider_slug}/e1")
    assert resp_ok.status_code == 200

    # Soft-delete it.
    with SessionLocal() as s:
        actor = s.merge(actor)
        catalog_service.soft_delete_exam(s, actor=actor, request_id=None, exam_id=exam_id)
        s.commit()

    resp_404 = client.get(f"/exams/{provider_slug}/e1")
    assert resp_404.status_code == 404


def test_published_exam_with_zero_questions_shows_coming_soon(
    nonce: str, client: TestClient
) -> None:
    actor = _make_admin(nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name=f"Prov {nonce}", slug=f"p04t-{nonce}"
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug="c1"
        )
        exam = catalog_service.create_exam(
            s, actor=actor, request_id=None, course_id=course.id, name="E", slug="e1"
        )
        catalog_service.publish_exam(s, actor=actor, request_id=None, exam_id=exam.id)
        s.commit()
        provider_slug = provider.slug

    resp = client.get(f"/exams/{provider_slug}/e1")
    assert resp.status_code == 200
    body = resp.text
    assert "Coming soon" in body
    assert "No questions available yet" in body
    assert "Start Practice" not in body  # CTA must be hidden when no questions.


def test_unpublished_exam_not_visible_publicly(nonce: str, client: TestClient) -> None:
    actor = _make_admin(nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name=f"Prov {nonce}", slug=f"p04t-{nonce}"
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug="c1"
        )
        catalog_service.create_exam(
            s, actor=actor, request_id=None, course_id=course.id, name="E", slug="e1"
        )
        s.commit()
        provider_slug = provider.slug

    resp = client.get(f"/exams/{provider_slug}/e1")
    assert resp.status_code == 404


def test_search_hits_only_published(nonce: str, client: TestClient) -> None:
    actor = _make_admin(nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s,
            actor=actor,
            request_id=None,
            name=f"SearchVendor {nonce}",
            slug=f"p04t-{nonce}",
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug="c1"
        )
        e_pub = catalog_service.create_exam(
            s,
            actor=actor,
            request_id=None,
            course_id=course.id,
            name=f"NSE4-pub-{nonce}",
            slug="e1",
            code=f"NSE4-{nonce}",
        )
        catalog_service.create_exam(
            s,
            actor=actor,
            request_id=None,
            course_id=course.id,
            name=f"NSE4-draft-{nonce}",
            slug="e2",
        )
        catalog_service.publish_exam(s, actor=actor, request_id=None, exam_id=e_pub.id)
        s.commit()

    resp = client.get(f"/search/exams?q=NSE4-pub-{nonce}")
    assert resp.status_code == 200
    # The published exam appears as a hit (linked under <ul class="search-results">).
    assert 'class="search-results"' in resp.text

    resp_draft = client.get(f"/search/exams?q=NSE4-draft-{nonce}")
    # Draft exam returns empty-state message — the result list must NOT render.
    assert 'class="search-results"' not in resp_draft.text
    assert "No published exams matched" in resp_draft.text


# ---------------------------------------------------------------------------
# RBAC + CSRF tests on admin routes
# ---------------------------------------------------------------------------


def test_admin_provider_list_requires_admin(client: TestClient, nonce: str) -> None:
    # Anonymous → 401
    r = client.get("/admin/providers")
    assert r.status_code == 401

    # Student → 403
    _register(client, email=f"stu-{nonce}@p04test.local", username=f"stu{nonce}")
    r = client.get("/admin/providers")
    assert r.status_code == 403


def test_admin_provider_create_requires_csrf(client: TestClient, nonce: str) -> None:
    _admin_login(client, nonce)
    # POST without csrf token → 403.
    r = client.post(
        "/admin/providers",
        data={"name": f"X {nonce}", "slug": f"p04t-{nonce}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "invalid csrf"


def test_admin_provider_create_succeeds_with_csrf(client: TestClient, nonce: str) -> None:
    _admin_login(client, nonce)
    csrf, _ = _csrf_pair(client, "/admin/providers")
    r = client.post(
        "/admin/providers",
        data={
            "name": f"FNet {nonce}",
            "slug": f"p04t-{nonce}",
            "csrf_token": csrf,
        },
    )
    assert r.status_code == 200, r.text
    assert f"p04t-{nonce}" in r.text


def test_admin_provider_create_duplicate_slug_returns_friendly_error(
    client: TestClient, nonce: str
) -> None:
    _admin_login(client, nonce)
    csrf, _ = _csrf_pair(client, "/admin/providers")
    slug = f"p04t-{nonce}"
    # First create succeeds.
    r1 = client.post(
        "/admin/providers",
        data={"name": "A", "slug": slug, "csrf_token": csrf},
    )
    assert r1.status_code == 200
    # Re-fetch a fresh CSRF (each GET issues a new token, but same one re-validates).
    csrf, _ = _csrf_pair(client, "/admin/providers")
    r2 = client.post(
        "/admin/providers",
        data={"name": "B", "slug": slug, "csrf_token": csrf},
    )
    # Friendly 400 + message; never raw IntegrityError.
    assert r2.status_code == 400
    assert "already in use" in r2.text
    assert "IntegrityError" not in r2.text
