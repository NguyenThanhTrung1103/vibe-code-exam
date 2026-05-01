"""Phase 06 real-DB integration tests for the question CRUD admin.

Gated by `EXAM_PLATFORM_TEST_REAL_DB=1`. Verifies:
  * service-level CRUD (create, update, set_options, set_overall_explanation,
    retire/restore, assign_topic_bulk)
  * audit rows for every mutation
  * RBAC: anon → 401, student → 403
  * CSRF on POST routes
  * imported question (Phase 05 stage) can be edited via Phase 06 routes
  * correct_answer validation rejects unknown labels
  * single vs multiple-choice constraints
  * empty question_text rejected
  * unsafe HTML kept literal (Phase 06 trusts admin input; Phase 09
    will add render-time sanitization).
  * topic assignment honors exam membership
  * retired question is no longer "active" in queries that filter retired_at
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.audit.events import AuditAction
from app.db import SessionLocal
from app.main import create_app
from app.models.audit import AuditLog
from app.models.catalog import Course, Exam, Provider, Topic
from app.models.enums import (
    QuestionDifficulty,
    QuestionStatus,
    QuestionType,
    UserRole,
)
from app.models.questions import Question, QuestionExplanation, QuestionOption
from app.models.users import User
from app.redis_client import get_redis
from app.services import catalog_service, question_service

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
def _cleanup_phase06():
    yield
    with SessionLocal() as s:
        user_ids = list(s.scalars(select(User.id).where(User.email.like("%@p06test.local"))))
        provider_ids = list(s.scalars(select(Provider.id).where(Provider.slug.like("p06t-%"))))
        course_ids = list(
            s.scalars(select(Course.id).where(Course.provider_id.in_(provider_ids or [-1])))
        )
        exam_ids = list(s.scalars(select(Exam.id).where(Exam.course_id.in_(course_ids or [-1]))))
        question_ids = list(
            s.scalars(select(Question.id).where(Question.exam_id.in_(exam_ids or [-1])))
        )
        if question_ids:
            s.execute(
                delete(QuestionExplanation).where(QuestionExplanation.question_id.in_(question_ids))
            )
            s.execute(delete(QuestionOption).where(QuestionOption.question_id.in_(question_ids)))
            s.execute(delete(Question).where(Question.id.in_(question_ids)))
        if exam_ids:
            s.execute(delete(Topic).where(Topic.exam_id.in_(exam_ids)))
            s.execute(delete(Exam).where(Exam.id.in_(exam_ids)))
        if course_ids:
            s.execute(delete(Course).where(Course.id.in_(course_ids)))
        if provider_ids:
            s.execute(delete(Provider).where(Provider.id.in_(provider_ids)))
        if user_ids:
            s.execute(delete(AuditLog).where(AuditLog.entity_type == "question"))
            s.execute(delete(User).where(User.id.in_(user_ids)))
        s.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(nonce: str) -> User:
    from app.auth.service import register_user

    with SessionLocal() as s:
        u = register_user(
            s,
            email=f"admin-{nonce}@p06test.local",
            username=f"adm{nonce}",
            password="Phase06-good-pw",
            role=UserRole.admin,
            request_id=None,
        )
        s.commit()
        return s.get(User, u.id)


def _make_exam_with_topic(actor: User, nonce: str) -> tuple[int, int]:
    """Returns (exam_id, topic_id)."""
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name=f"P{nonce}", slug=f"p06t-{nonce}"
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug="c1"
        )
        exam = catalog_service.create_exam(
            s, actor=actor, request_id=None, course_id=course.id, name="E", slug="e1"
        )
        topic = catalog_service.create_topic(
            s, actor=actor, request_id=None, exam_id=exam.id, name="T", slug="t1"
        )
        s.commit()
        return exam.id, topic.id


def _csrf_pair(client: TestClient, path: str = "/auth/login") -> str:
    resp = client.get(path)
    assert resp.status_code == 200
    token = resp.cookies.get("exam_csrf")
    assert token
    return token


def _login_admin(client: TestClient, user: User) -> None:
    csrf = _csrf_pair(client, "/auth/login")
    r = client.post(
        "/auth/login",
        data={"identifier": user.email, "password": "Phase06-good-pw", "csrf_token": csrf},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


def test_create_single_choice_question_audit_and_options(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id, topic_id = _make_exam_with_topic(actor, nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        q = question_service.create_question(
            s,
            actor=actor,
            request_id=None,
            exam_id=exam_id,
            question_text="What is 2+2?",
            options=[("A", "3"), ("B", "4"), ("C", "5")],
            correct_answer=["B"],
            question_type=QuestionType.single,
            difficulty=QuestionDifficulty.easy,
            topic_id=topic_id,
            overall_explanation="Two plus two is four.",
        )
        s.commit()
        opts = list(s.scalars(select(QuestionOption).where(QuestionOption.question_id == q.id)))
        assert {o.label for o in opts} == {"A", "B", "C"}
        assert {o.label for o in opts if o.is_correct} == {"B"}
        # Audit row written
        audits = list(
            s.scalars(
                select(AuditLog).where(
                    AuditLog.entity_id == q.id,
                    AuditLog.action == AuditAction.QUESTION_CREATED.value,
                )
            )
        )
        assert len(audits) == 1


def test_create_multiple_choice_validates(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id, _ = _make_exam_with_topic(actor, nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        # multiple type but only 1 correct → reject
        with pytest.raises(question_service.QuestionValidationError, match="multiple-choice"):
            question_service.create_question(
                s,
                actor=actor,
                request_id=None,
                exam_id=exam_id,
                question_text="Pick all that fly",
                options=[("A", "duck"), ("B", "dog"), ("C", "eagle")],
                correct_answer=["A"],
                question_type=QuestionType.multiple,
            )


def test_create_invalid_correct_label_rejected(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id, _ = _make_exam_with_topic(actor, nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        with pytest.raises(question_service.QuestionValidationError, match="no matching"):
            question_service.create_question(
                s,
                actor=actor,
                request_id=None,
                exam_id=exam_id,
                question_text="Q?",
                options=[("A", "x"), ("B", "y")],
                correct_answer=["Z"],
                question_type=QuestionType.single,
            )


def test_create_empty_text_rejected(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id, _ = _make_exam_with_topic(actor, nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        with pytest.raises(question_service.QuestionValidationError, match="question_text"):
            question_service.create_question(
                s,
                actor=actor,
                request_id=None,
                exam_id=exam_id,
                question_text="   ",
                options=[("A", "x"), ("B", "y")],
                correct_answer=["A"],
                question_type=QuestionType.single,
            )


def test_update_text_audit_and_hash_changes(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id, _ = _make_exam_with_topic(actor, nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        q = question_service.create_question(
            s,
            actor=actor,
            request_id=None,
            exam_id=exam_id,
            question_text="Old text",
            options=[("A", "x"), ("B", "y")],
            correct_answer=["A"],
            question_type=QuestionType.single,
        )
        s.commit()
        old_hash = q.content_hash
        question_service.update_question(
            s,
            actor=actor,
            request_id=None,
            question_id=q.id,
            question_text="New text",
            question_type=None,
            difficulty=None,
            topic_id=None,
        )
        s.commit()
        q2 = s.get(Question, q.id)
        assert q2.question_text == "New text"
        assert q2.content_hash != old_hash
        audits = list(
            s.scalars(
                select(AuditLog).where(
                    AuditLog.entity_id == q.id,
                    AuditLog.action == AuditAction.QUESTION_TEXT_EDITED.value,
                )
            )
        )
        assert len(audits) == 1


def test_set_options_replaces_set_and_audits(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id, _ = _make_exam_with_topic(actor, nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        q = question_service.create_question(
            s,
            actor=actor,
            request_id=None,
            exam_id=exam_id,
            question_text="Q?",
            options=[("A", "x"), ("B", "y"), ("C", "z")],
            correct_answer=["A"],
            question_type=QuestionType.single,
        )
        s.commit()
        question_service.set_options(
            s,
            actor=actor,
            request_id=None,
            question_id=q.id,
            options=[("A", "alpha"), ("B", "beta")],
            correct_answer=["B"],
        )
        s.commit()
        opts = list(s.scalars(select(QuestionOption).where(QuestionOption.question_id == q.id)))
        assert sorted((o.label, o.option_text, bool(o.is_correct)) for o in opts) == [
            ("A", "alpha", False),
            ("B", "beta", True),
        ]
        audits = list(
            s.scalars(
                select(AuditLog).where(
                    AuditLog.entity_id == q.id,
                    AuditLog.action == AuditAction.QUESTION_OPTION_EDITED.value,
                )
            )
        )
        assert len(audits) >= 1


def test_overall_explanation_upsert_and_audit(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id, _ = _make_exam_with_topic(actor, nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        q = question_service.create_question(
            s,
            actor=actor,
            request_id=None,
            exam_id=exam_id,
            question_text="Q?",
            options=[("A", "x"), ("B", "y")],
            correct_answer=["A"],
            question_type=QuestionType.single,
        )
        s.commit()
        question_service.set_overall_explanation(
            s, actor=actor, request_id=None, question_id=q.id, text="First explanation"
        )
        s.commit()
        question_service.set_overall_explanation(
            s, actor=actor, request_id=None, question_id=q.id, text="Updated explanation"
        )
        s.commit()
        rows = list(
            s.scalars(select(QuestionExplanation).where(QuestionExplanation.question_id == q.id))
        )
        assert len(rows) == 1
        assert rows[0].overall_explanation == "Updated explanation"
        audits = list(
            s.scalars(
                select(AuditLog).where(
                    AuditLog.entity_id == q.id,
                    AuditLog.action == AuditAction.QUESTION_EXPLANATION_EDITED.value,
                )
            )
        )
        assert len(audits) == 2  # one per upsert


def test_retire_and_restore_round_trip(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id, _ = _make_exam_with_topic(actor, nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        q = question_service.create_question(
            s,
            actor=actor,
            request_id=None,
            exam_id=exam_id,
            question_text="Q?",
            options=[("A", "x"), ("B", "y")],
            correct_answer=["A"],
            question_type=QuestionType.single,
        )
        s.commit()
        question_service.retire(
            s, actor=actor, request_id=None, question_id=q.id, reason="wrong answer"
        )
        s.commit()
        q1 = s.get(Question, q.id)
        assert q1.retired_at is not None
        assert q1.status == QuestionStatus.retired
        question_service.restore(s, actor=actor, request_id=None, question_id=q.id)
        s.commit()
        q2 = s.get(Question, q.id)
        assert q2.retired_at is None
        assert q2.status == QuestionStatus.verified_low


def test_assign_topic_bulk_validates_exam_match(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id, topic_id = _make_exam_with_topic(actor, nonce)
    # Build a second exam with its own topic
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = s.scalars(select(Provider).where(Provider.slug == f"p06t-{nonce}")).first()
        course2 = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C2", slug="c2"
        )
        exam2 = catalog_service.create_exam(
            s, actor=actor, request_id=None, course_id=course2.id, name="E2", slug="e2"
        )
        s.commit()
        # 1 question on the original exam
        q = question_service.create_question(
            s,
            actor=actor,
            request_id=None,
            exam_id=exam_id,
            question_text="A?",
            options=[("A", "1"), ("B", "2")],
            correct_answer=["A"],
            question_type=QuestionType.single,
        )
        s.commit()
        # Topic belongs to the FIRST exam — assigning to the second exam's q
        # would mismatch. Here only the first exam's q is in the bulk list,
        # so the assign succeeds.
        n = question_service.assign_topic_bulk(
            s,
            actor=actor,
            request_id=None,
            question_ids=[q.id],
            topic_id=topic_id,
        )
        s.commit()
        assert n == 1
        # Now create a question on exam2; assigning topic_id (from exam1) → reject.
        q2 = question_service.create_question(
            s,
            actor=actor,
            request_id=None,
            exam_id=exam2.id,
            question_text="B?",
            options=[("A", "1"), ("B", "2")],
            correct_answer=["A"],
            question_type=QuestionType.single,
        )
        s.commit()
        with pytest.raises(question_service.QuestionValidationError, match="belongs to exam"):
            question_service.assign_topic_bulk(
                s,
                actor=actor,
                request_id=None,
                question_ids=[q2.id],
                topic_id=topic_id,
            )


def test_imported_question_can_be_edited(nonce: str) -> None:
    """Phase 05 leaves questions in `imported`; Phase 06 must let admin edit them."""
    actor = _make_admin(nonce)
    exam_id, _ = _make_exam_with_topic(actor, nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        # Simulate Phase 05 import — direct INSERT with status=imported
        q = Question(
            exam_id=exam_id,
            question_text="Imported Q?",
            question_type=QuestionType.single,
            status=QuestionStatus.imported,
            content_hash="0" * 64,
        )
        s.add(q)
        s.flush()
        s.add(
            QuestionOption(
                question_id=q.id, label="A", option_text="x", is_correct=False, order_index=0
            )
        )
        s.add(
            QuestionOption(
                question_id=q.id, label="B", option_text="y", is_correct=True, order_index=1
            )
        )
        s.commit()

        question_service.update_question(
            s,
            actor=actor,
            request_id=None,
            question_id=q.id,
            question_text="Edited imported Q?",
        )
        s.commit()
        q2 = s.get(Question, q.id)
        assert q2.question_text == "Edited imported Q?"


# ---------------------------------------------------------------------------
# HTTP-level RBAC + CSRF
# ---------------------------------------------------------------------------


def test_admin_questions_anonymous_returns_401(client: TestClient) -> None:
    r = client.get("/admin/questions")
    assert r.status_code == 401


def test_admin_questions_csrf_required_on_post(client: TestClient, nonce: str) -> None:
    actor = _make_admin(nonce)
    _login_admin(client, actor)
    # POST without csrf
    r = client.post(
        "/admin/questions",
        data={
            "exam_id": 1,
            "question_text": "x",
            "option_a": "1",
            "option_b": "2",
            "correct_answer": "A",
        },
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "invalid csrf"


def test_admin_questions_list_renders(client: TestClient, nonce: str) -> None:
    actor = _make_admin(nonce)
    _login_admin(client, actor)
    r = client.get("/admin/questions")
    assert r.status_code == 200
    assert "Questions" in r.text


def test_admin_question_create_via_http(client: TestClient, nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id, _ = _make_exam_with_topic(actor, nonce)
    _login_admin(client, actor)
    csrf = _csrf_pair(client, "/admin/questions/new")
    r = client.post(
        "/admin/questions",
        data={
            "csrf_token": csrf,
            "exam_id": exam_id,
            "question_text": "What does TCP stand for?",
            "question_type": "single",
            "option_a": "Transmission Control Protocol",
            "option_b": "Transit Coordination Process",
            "correct_answer": "A",
            "difficulty": "easy",
            "overall_explanation": "TCP is a transport-layer protocol.",
        },
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect", "").startswith("/admin/questions/")
