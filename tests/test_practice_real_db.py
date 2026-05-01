"""Phase 07 real-DB integration tests for practice / exam mode.

Gated by `EXAM_PLATFORM_TEST_REAL_DB=1`. Verifies:
  * start_attempt creates Attempt + N pre-created attempt_answers with
    order_index 1..N (UNIQUE constraint never trips).
  * empty / unpublished exam → 400.
  * resume returns the existing in-progress attempt instead of a new one.
  * cross-user attempt access → 403.
  * save_answer single-choice / multi-choice / clear / invalid label.
  * idempotent autosave (same input twice → no duplicates).
  * flag toggle.
  * timer enforcement: backdate started_at and a render forces submit.
  * order_index frozen across question retirement after attempt start.
  * submit is idempotent.
  * audit rows for start, submit, expire (none for save).
  * RBAC: anon → 401, missing CSRF → 403.
  * Phase 08 not implemented yet — submitted_stub renders.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.audit.events import AuditAction
from app.db import SessionLocal
from app.main import create_app
from app.models.attempts import Attempt, AttemptAnswer
from app.models.audit import AuditLog
from app.models.catalog import Course, Exam, Provider, Topic
from app.models.enums import (
    AttemptMode,
    ExamPublishStatus,
    QuestionStatus,
    QuestionType,
    UserRole,
)
from app.models.questions import Question, QuestionOption
from app.models.users import User
from app.redis_client import get_redis
from app.services import attempt_service, catalog_service

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
def _cleanup_phase07():
    yield
    with SessionLocal() as s:
        user_ids = list(s.scalars(select(User.id).where(User.email.like("%@p07test.local"))))
        if user_ids:
            attempt_ids = list(s.scalars(select(Attempt.id).where(Attempt.user_id.in_(user_ids))))
            if attempt_ids:
                s.execute(delete(AttemptAnswer).where(AttemptAnswer.attempt_id.in_(attempt_ids)))
                s.execute(delete(Attempt).where(Attempt.id.in_(attempt_ids)))
        provider_ids = list(s.scalars(select(Provider.id).where(Provider.slug.like("p07t-%"))))
        course_ids = list(
            s.scalars(select(Course.id).where(Course.provider_id.in_(provider_ids or [-1])))
        )
        exam_ids = list(s.scalars(select(Exam.id).where(Exam.course_id.in_(course_ids or [-1]))))
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
        if user_ids:
            s.execute(delete(AuditLog).where(AuditLog.entity_type == "attempt"))
            s.execute(delete(User).where(User.id.in_(user_ids)))
        s.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(nonce: str, role: UserRole = UserRole.student) -> User:
    from app.auth.service import register_user

    with SessionLocal() as s:
        u = register_user(
            s,
            email=f"{role.value}-{nonce}@p07test.local",
            username=f"{role.value[:3]}{nonce}",
            password="Phase07-good-pw",
            role=role,
            request_id=None,
        )
        s.commit()
        return s.get(User, u.id)


def _seed_exam_with_questions(
    actor: User, nonce: str, *, n_questions: int = 3, time_limit: int | None = None
) -> int:
    """Create provider/course/exam (published) + N published questions.

    Returns exam_id.
    """
    from decimal import Decimal

    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name=f"P{nonce}", slug=f"p07t-{nonce}"
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
            time_limit_seconds=time_limit,
            passing_score_percent=Decimal("60.00"),
        )
        # Publish the exam directly (we created it with admin role so this is fine).
        catalog_service.publish_exam(s, actor=actor, request_id=None, exam_id=exam.id)
        s.commit()
        exam_id = exam.id

        for i in range(n_questions):
            q = Question(
                exam_id=exam_id,
                question_text=f"Q{i}-{nonce}",
                question_type=QuestionType.single,
                status=QuestionStatus.published,
                content_hash="0" * 63 + str(i),
            )
            s.add(q)
            s.flush()
            # Two options, B is correct.
            s.add(
                QuestionOption(
                    question_id=q.id,
                    label="A",
                    option_text="wrong",
                    is_correct=False,
                    order_index=0,
                )
            )
            s.add(
                QuestionOption(
                    question_id=q.id, label="B", option_text="right", is_correct=True, order_index=1
                )
            )
        s.commit()
        return exam_id


def _seed_empty_published_exam(actor: User, nonce: str) -> int:
    """Published exam with zero published questions."""
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name=f"P{nonce}", slug=f"p07t-{nonce}"
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug="c1"
        )
        exam = catalog_service.create_exam(
            s, actor=actor, request_id=None, course_id=course.id, name="E", slug="e1"
        )
        catalog_service.publish_exam(s, actor=actor, request_id=None, exam_id=exam.id)
        s.commit()
        return exam.id


def _csrf_pair(client: TestClient, path: str = "/auth/login") -> str:
    resp = client.get(path)
    assert resp.status_code == 200
    token = resp.cookies.get("exam_csrf")
    assert token
    return token


def _login(client: TestClient, user: User) -> None:
    csrf = _csrf_pair(client, "/auth/login")
    r = client.post(
        "/auth/login",
        data={"identifier": user.email, "password": "Phase07-good-pw", "csrf_token": csrf},
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Service-level: start / resume
# ---------------------------------------------------------------------------


def test_start_creates_attempt_and_n_attempt_answers(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=4)
    with SessionLocal() as s:
        student = s.merge(student)
        attempt = attempt_service.start_attempt(
            s,
            actor=student,
            request_id=None,
            exam_id=exam_id,
            mode=AttemptMode.practice,
        )
        s.commit()
        rows = list(
            s.scalars(
                select(AttemptAnswer)
                .where(AttemptAnswer.attempt_id == attempt.id)
                .order_by(AttemptAnswer.order_index)
            )
        )
        assert len(rows) == 4
        assert [r.order_index for r in rows] == [1, 2, 3, 4]
        assert all(r.selected_options is None for r in rows)
        assert attempt.user_id == student.id
        assert attempt.exam_id == exam_id
        # audit row written
        audits = list(
            s.scalars(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.ATTEMPT_STARTED.value,
                    AuditLog.entity_id == attempt.id,
                )
            )
        )
        assert len(audits) == 1


def test_start_empty_exam_rejected(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_empty_published_exam(admin, nonce)
    with SessionLocal() as s:
        student = s.merge(student)
        with pytest.raises(attempt_service.AttemptValidationError, match="no questions"):
            attempt_service.start_attempt(
                s,
                actor=student,
                request_id=None,
                exam_id=exam_id,
                mode=AttemptMode.practice,
            )


def test_start_unpublished_exam_rejected(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=2)
    with SessionLocal() as s:
        s.execute(select(Exam).where(Exam.id == exam_id))  # warm up
        e = s.get(Exam, exam_id)
        e.publish_status = ExamPublishStatus.draft
        s.commit()
    with SessionLocal() as s:
        student = s.merge(student)
        with pytest.raises(attempt_service.AttemptValidationError, match="not available"):
            attempt_service.start_attempt(
                s,
                actor=student,
                request_id=None,
                exam_id=exam_id,
                mode=AttemptMode.practice,
            )


def test_start_returns_existing_in_progress_attempt(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=2)
    with SessionLocal() as s:
        student = s.merge(student)
        first = attempt_service.start_attempt(
            s,
            actor=student,
            request_id=None,
            exam_id=exam_id,
            mode=AttemptMode.practice,
        )
        s.commit()
        first_id = first.id
        # Second start should resume the same attempt id.
        again = attempt_service.start_attempt(
            s,
            actor=student,
            request_id=None,
            exam_id=exam_id,
            mode=AttemptMode.practice,
        )
        s.commit()
        assert again.id == first_id
        # No duplicate attempt_answers.
        cnt = s.scalar(
            select(func.count(AttemptAnswer.id)).where(AttemptAnswer.attempt_id == first_id)
        )
        assert cnt == 2


# ---------------------------------------------------------------------------
# Service-level: save / flag
# ---------------------------------------------------------------------------


def test_save_single_choice_and_idempotent(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=2)
    with SessionLocal() as s:
        student = s.merge(student)
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        # Save twice; second call must be no-op (no duplicates).
        attempt_service.save_answer(
            s,
            actor=student,
            request_id=None,
            attempt_id=attempt.id,
            order=1,
            selected="B",
        )
        attempt_service.save_answer(
            s,
            actor=student,
            request_id=None,
            attempt_id=attempt.id,
            order=1,
            selected="B",
        )
        s.commit()
        rows = list(s.scalars(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id)))
        # Still N rows (frozen at start), and order=1 has 'B'.
        assert len(rows) == 2
        target = next(r for r in rows if r.order_index == 1)
        assert target.selected_options == "B"


def test_save_multi_choice_sorted(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    # Seed an exam with one multi-choice question with 3 options.
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=1)
    with SessionLocal() as s:
        # Add option C and convert to multi.
        q = s.scalars(select(Question).where(Question.exam_id == exam_id)).first()
        q.question_type = QuestionType.multiple
        s.add(
            QuestionOption(
                question_id=q.id,
                label="C",
                option_text="also right",
                is_correct=True,
                order_index=2,
            )
        )
        s.commit()

    with SessionLocal() as s:
        student = s.merge(student)
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        # Save in reversed order — service must store sorted.
        attempt_service.save_answer(
            s,
            actor=student,
            request_id=None,
            attempt_id=attempt.id,
            order=1,
            selected=["C", "A"],
        )
        s.commit()
        target = s.scalars(
            select(AttemptAnswer)
            .where(AttemptAnswer.attempt_id == attempt.id)
            .where(AttemptAnswer.order_index == 1)
        ).first()
        assert target.selected_options == "A,C"


def test_save_invalid_label_rejected(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=1)
    with SessionLocal() as s:
        student = s.merge(student)
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        with pytest.raises(attempt_service.AttemptValidationError, match="not on this question"):
            attempt_service.save_answer(
                s,
                actor=student,
                request_id=None,
                attempt_id=attempt.id,
                order=1,
                selected="Z",
            )


def test_save_clears_when_empty(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=1)
    with SessionLocal() as s:
        student = s.merge(student)
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        attempt_service.save_answer(
            s,
            actor=student,
            request_id=None,
            attempt_id=attempt.id,
            order=1,
            selected="B",
        )
        s.commit()
        # Now clear.
        attempt_service.save_answer(
            s,
            actor=student,
            request_id=None,
            attempt_id=attempt.id,
            order=1,
            selected=None,
        )
        s.commit()
        target = s.scalars(
            select(AttemptAnswer)
            .where(AttemptAnswer.attempt_id == attempt.id)
            .where(AttemptAnswer.order_index == 1)
        ).first()
        assert target.selected_options is None


def test_cross_user_save_403(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    alice = _make_user(nonce + "a", UserRole.student)
    bob = _make_user(nonce + "b", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=1)
    with SessionLocal() as s:
        alice = s.merge(alice)
        attempt = attempt_service.start_attempt(
            s, actor=alice, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        attempt_id = attempt.id
    with SessionLocal() as s:
        bob = s.merge(bob)
        with pytest.raises(attempt_service.AttemptForbiddenError):
            attempt_service.save_answer(
                s,
                actor=bob,
                request_id=None,
                attempt_id=attempt_id,
                order=1,
                selected="B",
            )


def test_flag_toggle(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=1)
    with SessionLocal() as s:
        student = s.merge(student)
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        attempt_service.toggle_flag(
            s, actor=student, request_id=None, attempt_id=attempt.id, order=1
        )
        s.commit()
        target = s.scalars(
            select(AttemptAnswer)
            .where(AttemptAnswer.attempt_id == attempt.id)
            .where(AttemptAnswer.order_index == 1)
        ).first()
        assert target.flagged is True
        attempt_service.toggle_flag(
            s, actor=student, request_id=None, attempt_id=attempt.id, order=1
        )
        s.commit()
        target = s.scalars(
            select(AttemptAnswer)
            .where(AttemptAnswer.attempt_id == attempt.id)
            .where(AttemptAnswer.order_index == 1)
        ).first()
        assert target.flagged is False


# ---------------------------------------------------------------------------
# Service-level: timer + submit
# ---------------------------------------------------------------------------


def test_timer_expiry_forces_submit(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=2, time_limit=60)
    with SessionLocal() as s:
        student = s.merge(student)
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.exam
        )
        # Backdate started_at by 2 minutes — past the 60s limit.
        attempt.started_at = datetime.now(UTC) - timedelta(minutes=2)
        s.commit()
        with pytest.raises(attempt_service.AttemptExpiredError):
            attempt_service.ensure_not_expired(s, actor=student, request_id=None, attempt=attempt)
        s.commit()
        a2 = s.get(Attempt, attempt.id)
        assert a2.finished_at is not None
        # Audit row for expiry written.
        audits = list(
            s.scalars(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.ATTEMPT_EXPIRED.value,
                    AuditLog.entity_id == attempt.id,
                )
            )
        )
        assert len(audits) == 1


def test_submit_idempotent(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=1)
    with SessionLocal() as s:
        student = s.merge(student)
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        attempt_service.submit_attempt(s, actor=student, request_id=None, attempt_id=attempt.id)
        first_finish = s.get(Attempt, attempt.id).finished_at
        s.commit()
        attempt_service.submit_attempt(s, actor=student, request_id=None, attempt_id=attempt.id)
        s.commit()
        second_finish = s.get(Attempt, attempt.id).finished_at
        assert first_finish == second_finish  # not overwritten


def test_save_after_submit_rejected(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=1)
    with SessionLocal() as s:
        student = s.merge(student)
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        attempt_service.submit_attempt(s, actor=student, request_id=None, attempt_id=attempt.id)
        s.commit()
        with pytest.raises(attempt_service.AttemptValidationError, match="already submitted"):
            attempt_service.save_answer(
                s,
                actor=student,
                request_id=None,
                attempt_id=attempt.id,
                order=1,
                selected="B",
            )


# ---------------------------------------------------------------------------
# Service-level: order_index frozen across question retirement
# ---------------------------------------------------------------------------


def test_order_index_survives_question_retirement_after_attempt(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=3)
    with SessionLocal() as s:
        student = s.merge(student)
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        attempt_id = attempt.id
        # Snapshot the (order, question_id) tuples.
        before = [
            (r.order_index, r.question_id)
            for r in s.scalars(
                select(AttemptAnswer)
                .where(AttemptAnswer.attempt_id == attempt_id)
                .order_by(AttemptAnswer.order_index)
            )
        ]
        # Retire the FIRST question.
        first_qid = before[0][1]
        q = s.get(Question, first_qid)
        q.retired_at = datetime.now(UTC)
        q.status = QuestionStatus.retired
        s.commit()

    # Now reload the attempt; the (order, question_id) tuples must be unchanged.
    with SessionLocal() as s:
        after = [
            (r.order_index, r.question_id)
            for r in s.scalars(
                select(AttemptAnswer)
                .where(AttemptAnswer.attempt_id == attempt_id)
                .order_by(AttemptAnswer.order_index)
            )
        ]
        assert after == before


# ---------------------------------------------------------------------------
# HTTP-level: RBAC + CSRF
# ---------------------------------------------------------------------------


def test_anon_cannot_start_attempt(client: TestClient) -> None:
    r = client.post("/attempts/start", data={"exam_id": 1, "mode": "practice"})
    assert r.status_code == 401


def test_csrf_required_on_start(client: TestClient, nonce: str) -> None:
    student = _make_user(nonce + "stu", UserRole.student)
    _login(client, student)
    r = client.post("/attempts/start", data={"exam_id": 1, "mode": "practice"})
    assert r.status_code == 403
    assert r.json()["detail"] == "invalid csrf"


def test_anon_cannot_view_question_or_submit(client: TestClient) -> None:
    assert client.get("/attempts/1/q/1").status_code == 401
    r = client.post("/attempts/1/submit", data={"csrf_token": "x"})
    assert r.status_code == 401


def test_full_http_flow_smoke(client: TestClient, nonce: str) -> None:
    """Walk an end-to-end practice attempt over HTTP."""
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=2)

    _login(client, student)
    csrf = _csrf_pair(client, "/auth/login")
    # 1. start
    r = client.post(
        "/attempts/start",
        data={"exam_id": exam_id, "mode": "practice", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/attempts/")
    location = r.headers["location"]
    attempt_id = int(location.split("/")[2])

    # 2. show q1
    r = client.get(f"/attempts/{attempt_id}/q/1")
    assert r.status_code == 200
    assert "Q1 / 2" in r.text

    # 3. autosave selection
    csrf2 = client.cookies.get("exam_csrf")
    r = client.post(
        f"/attempts/{attempt_id}/q/1/answer",
        data={"selected_options": "B", "csrf_token": csrf2},
    )
    assert r.status_code == 204

    # 4. flag
    r = client.post(
        f"/attempts/{attempt_id}/q/1/flag",
        data={"csrf_token": csrf2},
    )
    assert r.status_code == 200
    assert "Unflag" in r.text

    # 5. nav to q2 + submit
    r = client.get(f"/attempts/{attempt_id}/q/2")
    assert r.status_code == 200
    csrf3 = client.cookies.get("exam_csrf")
    r = client.post(
        f"/attempts/{attempt_id}/submit",
        data={"csrf_token": csrf3},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].endswith("/submitted")

    # 6. submitted stub renders
    r = client.get(f"/attempts/{attempt_id}/submitted")
    assert r.status_code == 200
    assert "submitted" in r.text.lower()


def test_cross_user_http_403(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    alice = _make_user(nonce + "a", UserRole.student)
    bob = _make_user(nonce + "b", UserRole.student)
    exam_id = _seed_exam_with_questions(admin, nonce, n_questions=1)

    _login(client, alice)
    csrf = _csrf_pair(client, "/auth/login")
    r = client.post(
        "/attempts/start",
        data={"exam_id": exam_id, "mode": "practice", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    attempt_id = int(r.headers["location"].split("/")[2])

    # Alice logs out, Bob logs in.
    client.post("/auth/logout")
    _login(client, bob)
    r = client.get(f"/attempts/{attempt_id}/q/1")
    assert r.status_code == 403
