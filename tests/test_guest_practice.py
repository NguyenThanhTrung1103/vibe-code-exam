"""Phase 18 — guest practice mode.

Two test groups:

* **Pure unit tests** for `app.auth.guest_token` — no DB / no HTTP.
* **Real-DB integration tests** for `/practice` + guest-aware attempt
  routes, gated by `EXAM_PLATFORM_TEST_REAL_DB=1` to mirror the existing
  `test_practice_real_db.py` pattern.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.auth.guest_token import (
    GUEST_COOKIE_NAME,
    issue_guest_token,
    verify_guest_token,
)
from app.db import SessionLocal
from app.main import create_app
from app.models.attempts import Attempt, AttemptAnswer
from app.models.audit import AuditLog
from app.models.catalog import Course, Exam, Provider, Topic
from app.models.enums import (
    QuestionStatus,
    QuestionType,
    UserRole,
)
from app.models.questions import Question, QuestionOption
from app.models.users import User
from app.redis_client import get_redis
from app.services import catalog_service

# ---------------------------------------------------------------------------
# Pure unit tests — no DB, no HTTP
# ---------------------------------------------------------------------------


def test_issue_guest_token_returns_uuid_and_signed_cookie() -> None:
    raw, signed = issue_guest_token()
    # Raw is a UUID4 string; signed is the itsdangerous serialised form.
    assert uuid.UUID(raw)  # raises if not a valid UUID
    assert signed != raw
    assert "." in signed  # itsdangerous separator


def test_verify_guest_token_round_trip() -> None:
    raw, signed = issue_guest_token()
    assert verify_guest_token(signed) == raw


def test_verify_guest_token_returns_none_for_garbage() -> None:
    assert verify_guest_token("not-a-real-token") is None
    assert verify_guest_token("") is None
    assert verify_guest_token(None) is None


def test_verify_guest_token_returns_none_for_tampered() -> None:
    raw, signed = issue_guest_token()
    tampered = signed[:-2] + ("AB" if signed[-2:] != "AB" else "CD")
    assert verify_guest_token(tampered) is None


def test_verify_guest_token_respects_max_age() -> None:
    """A max_age of 0 expires immediately (timestamp must be strictly newer)."""
    _, signed = issue_guest_token()
    # Sleep at least 1 second so the timestamp embedded in the token is
    # strictly older than 0 seconds; max_age=0 then rejects it.
    time.sleep(1.1)
    assert verify_guest_token(signed, max_age=0) is None


# ---------------------------------------------------------------------------
# Real-DB integration tests
# ---------------------------------------------------------------------------


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
def _flush_rate_limits():
    r = get_redis()
    for key in r.scan_iter(match="rl:*"):
        r.delete(key)
    yield


@pytest.fixture(autouse=True)
def _cleanup_phase18():
    yield
    with SessionLocal() as s:
        # Tear down anything seeded for this test (provider slugs prefixed).
        provider_ids = list(s.scalars(select(Provider.id).where(Provider.slug.like("p18t-%"))))
        course_ids = list(
            s.scalars(select(Course.id).where(Course.provider_id.in_(provider_ids or [-1])))
        )
        exam_ids = list(s.scalars(select(Exam.id).where(Exam.course_id.in_(course_ids or [-1]))))
        # Guest attempts may have been created via TestClient.
        guest_attempt_ids = list(
            s.scalars(select(Attempt.id).where(Attempt.exam_id.in_(exam_ids or [-1])))
        )
        if guest_attempt_ids:
            s.execute(delete(AttemptAnswer).where(AttemptAnswer.attempt_id.in_(guest_attempt_ids)))
            s.execute(delete(Attempt).where(Attempt.id.in_(guest_attempt_ids)))
        question_ids = list(
            s.scalars(select(Question.id).where(Question.exam_id.in_(exam_ids or [-1])))
        )
        if question_ids:
            s.execute(delete(QuestionOption).where(QuestionOption.question_id.in_(question_ids)))
            s.execute(delete(Question).where(Question.id.in_(question_ids)))
        if exam_ids:
            s.execute(delete(Topic).where(Topic.exam_id.in_(exam_ids)))
            s.execute(delete(Exam).where(Exam.id.in_(exam_ids)))
        if course_ids:
            s.execute(delete(Course).where(Course.id.in_(course_ids)))
        if provider_ids:
            s.execute(delete(Provider).where(Provider.id.in_(provider_ids)))
        # Cleanup any audit rows for those attempts.
        if guest_attempt_ids:
            s.execute(
                delete(AuditLog)
                .where(AuditLog.entity_type == "attempt")
                .where(AuditLog.entity_id.in_(guest_attempt_ids))
            )
        # Drop any test-seeded admin user.
        s.execute(delete(User).where(User.email.like("%@p18test.local")))
        s.commit()


def _make_admin(nonce: str) -> User:
    from app.auth.service import register_user

    with SessionLocal() as s:
        u = register_user(
            s,
            email=f"admin-{nonce}@p18test.local",
            username=f"a18{nonce}",
            password="Phase18-good-pw",
            role=UserRole.admin,
            request_id=None,
        )
        s.commit()
        return s.get(User, u.id)


def _seed_published_exam(actor: User, nonce: str, *, n_questions: int = 2) -> int:
    """Provider/course/exam (published) + N published questions. Returns exam_id."""
    from decimal import Decimal

    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name=f"P{nonce}", slug=f"p18t-{nonce}"
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug=f"c-{nonce}"
        )
        exam = catalog_service.create_exam(
            s,
            actor=actor,
            request_id=None,
            course_id=course.id,
            name=f"E{nonce}",
            slug=f"e-{nonce}",
            passing_score_percent=Decimal("60.00"),
        )
        catalog_service.publish_exam(s, actor=actor, request_id=None, exam_id=exam.id)
        s.commit()
        exam_id = exam.id

        for i in range(n_questions):
            q = Question(
                exam_id=exam_id,
                question_text=f"GuestQ{i}-{nonce}",
                question_type=QuestionType.single,
                status=QuestionStatus.published,
                content_hash="g" * 62 + f"{i:02d}",
            )
            s.add(q)
            s.flush()
            s.add(QuestionOption(question_id=q.id, label="A", option_text="wrong", is_correct=False, order_index=0))
            s.add(QuestionOption(question_id=q.id, label="B", option_text="right", is_correct=True, order_index=1))
        s.commit()
        return exam_id


def _seed_draft_exam(actor: User, nonce: str) -> int:
    """Draft (unpublished) exam — must NOT appear on /practice."""
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name=f"DP{nonce}", slug=f"p18t-d{nonce}"
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug=f"cd-{nonce}"
        )
        exam = catalog_service.create_exam(
            s, actor=actor, request_id=None, course_id=course.id, name="DraftE", slug=f"ed-{nonce}"
        )
        s.commit()
        return exam.id


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def test_catalog_returns_200_without_auth(client, nonce):
    admin = _make_admin(nonce)
    _seed_published_exam(admin, nonce)
    r = client.get("/practice")
    assert r.status_code == 200
    assert "Practice exams" in r.text


def test_catalog_lists_only_published_exams(client, nonce):
    admin = _make_admin(nonce)
    pub_id = _seed_published_exam(admin, nonce)
    _seed_draft_exam(admin, nonce)
    r = client.get("/practice")
    assert r.status_code == 200
    # Published exam name is rendered; the draft slug is not.
    assert f"E{nonce}" in r.text
    assert "DraftE" not in r.text
    assert str(pub_id) in r.text or f"/practice/{pub_id}/start" in r.text


# ---------------------------------------------------------------------------
# Start guest attempt
# ---------------------------------------------------------------------------


def test_start_guest_attempt_redirects_and_sets_cookie(client, nonce):
    admin = _make_admin(nonce)
    exam_id = _seed_published_exam(admin, nonce)
    r = client.post(f"/practice/{exam_id}/start", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/attempts/")
    # Cookie was set on the redirect response.
    assert GUEST_COOKIE_NAME in r.cookies


def test_start_guest_attempt_on_draft_exam_is_403(client, nonce):
    admin = _make_admin(nonce)
    exam_id = _seed_draft_exam(admin, nonce)
    r = client.post(f"/practice/{exam_id}/start", follow_redirects=False)
    assert r.status_code == 403


def test_guest_can_navigate_attempt_with_valid_cookie(client, nonce):
    admin = _make_admin(nonce)
    exam_id = _seed_published_exam(admin, nonce, n_questions=2)
    r = client.post(f"/practice/{exam_id}/start", follow_redirects=False)
    assert r.status_code == 303
    location = r.headers["location"]
    # Cookie carries over because TestClient persists cookies on its instance.
    page = client.get(location)
    assert page.status_code == 200
    assert "Question #1" in page.text or "Q1 / 2" in page.text


def test_guest_cannot_access_anothers_attempt(client, nonce):
    admin = _make_admin(nonce)
    exam_id = _seed_published_exam(admin, nonce)
    r = client.post(f"/practice/{exam_id}/start", follow_redirects=False)
    assert r.status_code == 303
    location = r.headers["location"]
    # Wipe the cookie → simulate a different (or no) guest.
    client.cookies.clear()
    forbidden = client.get(location)
    assert forbidden.status_code == 403


# ---------------------------------------------------------------------------
# Mode + question_count (Learning vs Mock Exam)
# ---------------------------------------------------------------------------


def test_guest_start_accepts_mode_exam(client, nonce):
    """Mock Exam Mode — guest POSTs `mode=exam` and the attempt is created
    with `AttemptMode.exam`."""
    admin = _make_admin(nonce)
    exam_id = _seed_published_exam(admin, nonce, n_questions=2)
    r = client.post(
        f"/practice/{exam_id}/start",
        data={"mode": "exam"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    attempt_id = int(r.headers["location"].split("/")[2])
    with SessionLocal() as s:
        a = s.get(Attempt, attempt_id)
        assert a is not None
        assert a.mode.value == "exam"


def test_guest_start_rejects_unsupported_mode(client, nonce):
    admin = _make_admin(nonce)
    exam_id = _seed_published_exam(admin, nonce)
    r = client.post(
        f"/practice/{exam_id}/start",
        data={"mode": "garbage"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_mock_exam_subsets_to_question_count(client, nonce):
    """When `question_count=3` is sent against a 5-question bank, the
    Attempt should have exactly 3 AttemptAnswer rows (random subset)."""
    admin = _make_admin(nonce)
    exam_id = _seed_published_exam(admin, nonce, n_questions=5)
    r = client.post(
        f"/practice/{exam_id}/start",
        data={"mode": "exam", "question_count": "3"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    attempt_id = int(r.headers["location"].split("/")[2])
    with SessionLocal() as s:
        a = s.get(Attempt, attempt_id)
        assert a is not None
        assert a.total_questions == 3
        rows = s.scalars(
            select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt_id)
        ).all()
        assert len(rows) == 3


def test_mock_exam_default_count_caps_at_total(client, nonce):
    """If exam has fewer than the default mock size (30), the attempt uses all
    available questions — no padding, no error."""
    admin = _make_admin(nonce)
    exam_id = _seed_published_exam(admin, nonce, n_questions=4)
    r = client.post(
        f"/practice/{exam_id}/start",
        data={"mode": "exam"},  # no question_count → default 30, capped at 4
        follow_redirects=False,
    )
    assert r.status_code == 303
    attempt_id = int(r.headers["location"].split("/")[2])
    with SessionLocal() as s:
        a = s.get(Attempt, attempt_id)
        assert a is not None
        assert a.total_questions == 4


def test_mock_exam_default_count_uses_30_when_bank_has_more(client, nonce):
    """When the question bank is bigger than the default Mock Exam size, the
    Mock Exam attempt is created with exactly 30 randomly-sampled questions."""
    admin = _make_admin(nonce)
    exam_id = _seed_published_exam(admin, nonce, n_questions=42)
    r = client.post(
        f"/practice/{exam_id}/start",
        data={"mode": "exam"},  # no question_count → default 30
        follow_redirects=False,
    )
    assert r.status_code == 303
    attempt_id = int(r.headers["location"].split("/")[2])
    with SessionLocal() as s:
        a = s.get(Attempt, attempt_id)
        assert a is not None
        assert a.total_questions == 30
        rows = s.scalars(
            select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt_id)
        ).all()
        assert len(rows) == 30
        # Random subset must be unique — same question can't repeat in one mock.
        qids = [r.question_id for r in rows]
        assert len(set(qids)) == 30


def test_learning_mode_uses_all_questions(client, nonce):
    """Learning Mode ignores question_count — the learner studies the full
    bank, not a random subset."""
    admin = _make_admin(nonce)
    exam_id = _seed_published_exam(admin, nonce, n_questions=5)
    r = client.post(
        f"/practice/{exam_id}/start",
        data={"mode": "practice", "question_count": "2"},  # ignored
        follow_redirects=False,
    )
    assert r.status_code == 303
    attempt_id = int(r.headers["location"].split("/")[2])
    with SessionLocal() as s:
        a = s.get(Attempt, attempt_id)
        assert a is not None
        assert a.mode.value == "practice"
        assert a.total_questions == 5


def test_mock_exam_page_does_not_leak_correct_answer(client, nonce):
    """Mock Exam page must not render any correct-answer marker, explanation,
    reveal-toggle, or solution panel — even if the URL forges a `?reveal=`
    query string. Learning Mode (control) does render markers when revealed."""
    admin = _make_admin(nonce)
    exam_id = _seed_published_exam(admin, nonce, n_questions=2)

    # Mock Exam attempt
    r_exam = client.post(
        f"/practice/{exam_id}/start",
        data={"mode": "exam"},
        follow_redirects=False,
    )
    assert r_exam.status_code == 303
    attempt_id_exam = int(r_exam.headers["location"].split("/")[2])

    # Try to reveal — query param must be ignored in exam mode.
    page = client.get(f"/attempts/{attempt_id_exam}/page/1?reveal=1,2")
    assert page.status_code == 200
    assert "Reveal Solution" not in page.text
    assert "Hide Solution" not in page.text
    assert "Correct answer:" not in page.text
    assert "✓ correct" not in page.text

    # Reset cookie to start a fresh Learning attempt as a different guest.
    client.cookies.clear()
    r_learn = client.post(
        f"/practice/{exam_id}/start",
        data={"mode": "practice"},
        follow_redirects=False,
    )
    assert r_learn.status_code == 303
    attempt_id_learn = int(r_learn.headers["location"].split("/")[2])

    # Learning Mode shows the reveal control + (when revealed) the solution.
    page_learn_no_reveal = client.get(f"/attempts/{attempt_id_learn}/page/1")
    assert page_learn_no_reveal.status_code == 200
    assert "Reveal Solution" in page_learn_no_reveal.text

    page_learn_revealed = client.get(f"/attempts/{attempt_id_learn}/page/1?reveal=1")
    assert page_learn_revealed.status_code == 200
    assert "Correct answer:" in page_learn_revealed.text
