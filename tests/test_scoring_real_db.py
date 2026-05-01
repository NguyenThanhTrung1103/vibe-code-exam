"""Phase 08 real-DB integration tests for scoring + result/review.

Gated by `EXAM_PLATFORM_TEST_REAL_DB=1`. Verifies:
  * Submit flow now computes score + topic breakdown atomically.
  * All-correct attempt → 100% + passed.
  * Wrong attempt → 0% + not passed.
  * Multi-choice all-or-nothing.
  * Unanswered questions count as wrong.
  * Idempotent re-submit doesn't double-count.
  * Question edits after attempt don't change attempt order.
  * Result page renders for owner; 403 for cross-user; 401 for anon.
  * Review list ordered by order_index; filter wrong / flagged.
  * Review single-question shows selected vs correct.
  * Question report POST creates row + audit; admin can resolve / reject.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.audit.events import AuditAction
from app.db import SessionLocal
from app.main import create_app
from app.models.attempts import Attempt, AttemptAnswer
from app.models.audit import AuditLog
from app.models.catalog import Course, Exam, Provider, Topic
from app.models.enums import (
    AttemptMode,
    QuestionStatus,
    QuestionType,
    ReportStatus,
    UserRole,
)
from app.models.questions import Question, QuestionExplanation, QuestionOption
from app.models.reports import QuestionReport
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
def _cleanup_phase08():
    yield
    with SessionLocal() as s:
        user_ids = list(s.scalars(select(User.id).where(User.email.like("%@p08test.local"))))
        if user_ids:
            attempt_ids = list(s.scalars(select(Attempt.id).where(Attempt.user_id.in_(user_ids))))
            if attempt_ids:
                s.execute(delete(AttemptAnswer).where(AttemptAnswer.attempt_id.in_(attempt_ids)))
                s.execute(delete(Attempt).where(Attempt.id.in_(attempt_ids)))
            s.execute(delete(QuestionReport).where(QuestionReport.user_id.in_(user_ids)))
        provider_ids = list(s.scalars(select(Provider.id).where(Provider.slug.like("p08t-%"))))
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
            s.execute(
                delete(AuditLog).where(AuditLog.entity_type.in_(("attempt", "question_report")))
            )
            s.execute(delete(User).where(User.id.in_(user_ids)))
        s.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _TestUser:
    id: int
    email: str
    role: UserRole


def _make_user(nonce: str, role: UserRole = UserRole.student) -> _TestUser:
    """Returns a plain dataclass — not a live SA model — so cross-session
    test helpers can reference id/email without DetachedInstanceError."""
    from app.auth.service import register_user

    with SessionLocal() as s:
        u = register_user(
            s,
            email=f"{role.value}-{nonce}@p08test.local",
            username=f"{role.value[:3]}{nonce}",
            password="Phase08-good-pw",
            role=role,
            request_id=None,
        )
        s.commit()
        # Read fresh + extract primitives BEFORE leaving the session.
        u = s.get(User, u.id)
        return _TestUser(id=u.id, email=u.email, role=u.role)


def _seed_exam(actor: _TestUser, nonce: str) -> tuple[int, list[int]]:
    """Provider/course/exam (published) + 3 single-choice qs (B is right) + 1 multi.

    Returns (exam_id, [question_ids in deterministic id order]).
    """
    with SessionLocal() as s:
        actor = s.get(User, actor.id)  # fresh attached instance
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name=f"P{nonce}", slug=f"p08t-{nonce}"
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug="c1"
        )
        # Topics need an exam_id; we create the topic after the exam below.
        exam = catalog_service.create_exam(
            s,
            actor=actor,
            request_id=None,
            course_id=course.id,
            name="E",
            slug="e1",
            passing_score_percent=Decimal("60.00"),
        )
        catalog_service.publish_exam(s, actor=actor, request_id=None, exam_id=exam.id)
        s.commit()
        topic = catalog_service.create_topic(
            s, actor=actor, request_id=None, exam_id=exam.id, name="T", slug="t1"
        )
        s.commit()

        qids: list[int] = []
        # 3 single-choice with B correct, all under topic.
        for i in range(3):
            q = Question(
                exam_id=exam.id,
                topic_id=topic.id,
                question_text=f"Single Q{i}-{nonce}",
                question_type=QuestionType.single,
                status=QuestionStatus.published,
                content_hash="0" * 63 + str(i),
            )
            s.add(q)
            s.flush()
            qids.append(q.id)
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
        # 1 multi-choice (A & C correct).
        q = Question(
            exam_id=exam.id,
            topic_id=topic.id,
            question_text=f"Multi Q-{nonce}",
            question_type=QuestionType.multiple,
            status=QuestionStatus.published,
            content_hash="0" * 62 + "ml",
        )
        s.add(q)
        s.flush()
        qids.append(q.id)
        s.add(
            QuestionOption(
                question_id=q.id, label="A", option_text="a", is_correct=True, order_index=0
            )
        )
        s.add(
            QuestionOption(
                question_id=q.id, label="B", option_text="b", is_correct=False, order_index=1
            )
        )
        s.add(
            QuestionOption(
                question_id=q.id, label="C", option_text="c", is_correct=True, order_index=2
            )
        )
        s.commit()
        return exam.id, qids


def _csrf(client: TestClient, path: str = "/auth/login") -> str:
    r = client.get(path)
    assert r.status_code == 200
    return r.cookies.get("exam_csrf") or ""


def _login(client: TestClient, user: _TestUser) -> None:
    csrf = _csrf(client, "/auth/login")
    r = client.post(
        "/auth/login",
        data={"identifier": user.email, "password": "Phase08-good-pw", "csrf_token": csrf},
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Scoring service tests
# ---------------------------------------------------------------------------


def test_all_correct_attempt_scores_100(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id, _ = _seed_exam(admin, nonce)
    with SessionLocal() as s:
        # keep student as _TestUser dataclass
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        attempt_id = attempt.id
        # Walk all 4 answers, picking correct labels.
        rows = list(
            s.scalars(
                select(AttemptAnswer)
                .where(AttemptAnswer.attempt_id == attempt_id)
                .order_by(AttemptAnswer.order_index)
            )
        )
        for r in rows:
            q = s.get(Question, r.question_id)
            if q.question_type == QuestionType.single:
                attempt_service.save_answer(
                    s,
                    actor=student,
                    request_id=None,
                    attempt_id=attempt_id,
                    order=r.order_index,
                    selected="B",
                )
            else:
                attempt_service.save_answer(
                    s,
                    actor=student,
                    request_id=None,
                    attempt_id=attempt_id,
                    order=r.order_index,
                    selected=["A", "C"],
                )
        s.commit()
        attempt_service.submit_attempt(s, actor=student, request_id=None, attempt_id=attempt_id)
        s.commit()
        a2 = s.get(Attempt, attempt_id)
        assert a2.score_percent == 100.0
        assert a2.passed is True
        assert a2.correct_count == 4
        assert a2.wrong_count == 0


def test_unanswered_counts_as_wrong(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id, _ = _seed_exam(admin, nonce)
    with SessionLocal() as s:
        # keep student as _TestUser dataclass
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        attempt_id = attempt.id
        attempt_service.submit_attempt(s, actor=student, request_id=None, attempt_id=attempt_id)
        s.commit()
        a = s.get(Attempt, attempt_id)
        assert a.score_percent == 0.0
        assert a.correct_count == 0
        assert a.wrong_count == 4
        assert a.passed is False


def test_multi_choice_all_or_nothing(nonce: str) -> None:
    """Picking only ONE of two correct labels is wrong on multi-choice."""
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id, _ = _seed_exam(admin, nonce)
    with SessionLocal() as s:
        # keep student as _TestUser dataclass
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        attempt_id = attempt.id
        rows = list(
            s.scalars(
                select(AttemptAnswer)
                .where(AttemptAnswer.attempt_id == attempt_id)
                .order_by(AttemptAnswer.order_index)
            )
        )
        # Find the multi-choice row, save only "A" (missing "C").
        for r in rows:
            q = s.get(Question, r.question_id)
            if q.question_type == QuestionType.multiple:
                attempt_service.save_answer(
                    s,
                    actor=student,
                    request_id=None,
                    attempt_id=attempt_id,
                    order=r.order_index,
                    selected="A",
                )
                break
        s.commit()
        attempt_service.submit_attempt(s, actor=student, request_id=None, attempt_id=attempt_id)
        s.commit()
        # Find the multi-choice attempt_answer.
        for r in rows:
            q = s.get(Question, r.question_id)
            if q.question_type == QuestionType.multiple:
                aa = s.get(AttemptAnswer, r.id)
                assert aa.is_correct is False
                break


def test_idempotent_resubmit_no_double_count(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id, _ = _seed_exam(admin, nonce)
    with SessionLocal() as s:
        # keep student as _TestUser dataclass
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        attempt_id = attempt.id
        attempt_service.submit_attempt(s, actor=student, request_id=None, attempt_id=attempt_id)
        s.commit()
        first_finish = s.get(Attempt, attempt_id).finished_at
        # Re-submit
        attempt_service.submit_attempt(s, actor=student, request_id=None, attempt_id=attempt_id)
        s.commit()
        a = s.get(Attempt, attempt_id)
        assert a.finished_at == first_finish  # not overwritten
        # Audit: exactly one ATTEMPT_SUBMITTED event.
        subs = list(
            s.scalars(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.ATTEMPT_SUBMITTED.value,
                    AuditLog.entity_id == attempt_id,
                )
            )
        )
        assert len(subs) == 1


def test_question_edit_after_attempt_does_not_change_order(nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id, _ = _seed_exam(admin, nonce)
    with SessionLocal() as s:
        # keep student as _TestUser dataclass
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        attempt_id = attempt.id
        before = [
            (r.order_index, r.question_id)
            for r in s.scalars(
                select(AttemptAnswer)
                .where(AttemptAnswer.attempt_id == attempt_id)
                .order_by(AttemptAnswer.order_index)
            )
        ]
    # Admin edits a question.
    with SessionLocal() as s:
        first_qid = before[0][1]
        q = s.get(Question, first_qid)
        q.question_text = "EDITED " + q.question_text
        s.commit()
    with SessionLocal() as s:
        after = [
            (r.order_index, r.question_id)
            for r in s.scalars(
                select(AttemptAnswer)
                .where(AttemptAnswer.attempt_id == attempt_id)
                .order_by(AttemptAnswer.order_index)
            )
        ]
        assert before == after


# ---------------------------------------------------------------------------
# HTTP-level: result + review pages
# ---------------------------------------------------------------------------


def test_result_page_renders_for_owner(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id, _ = _seed_exam(admin, nonce)
    with SessionLocal() as s:
        # keep student as _TestUser dataclass
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        attempt_service.submit_attempt(s, actor=student, request_id=None, attempt_id=attempt.id)
        s.commit()
        attempt_id = attempt.id

    _login(client, student)
    r = client.get(f"/attempts/{attempt_id}/result")
    assert r.status_code == 200
    assert "Result" in r.text
    assert "Topic breakdown" in r.text


def test_result_403_cross_user(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    alice = _make_user(nonce + "a", UserRole.student)
    bob = _make_user(nonce + "b", UserRole.student)
    exam_id, _ = _seed_exam(admin, nonce)
    with SessionLocal() as s:
        # keep alice as _TestUser dataclass
        attempt = attempt_service.start_attempt(
            s, actor=alice, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        attempt_service.submit_attempt(s, actor=alice, request_id=None, attempt_id=attempt.id)
        s.commit()
        attempt_id = attempt.id
    _login(client, bob)
    r = client.get(f"/attempts/{attempt_id}/result")
    assert r.status_code == 403


def test_result_401_anon(client: TestClient) -> None:
    assert client.get("/attempts/1/result").status_code == 401


def test_review_list_filter_wrong_only(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id, _ = _seed_exam(admin, nonce)
    with SessionLocal() as s:
        # keep student as _TestUser dataclass
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        attempt_id = attempt.id
        # Answer ONE single-choice correctly; leave the rest blank.
        rows = list(
            s.scalars(
                select(AttemptAnswer)
                .where(AttemptAnswer.attempt_id == attempt_id)
                .order_by(AttemptAnswer.order_index)
            )
        )
        first = rows[0]
        attempt_service.save_answer(
            s,
            actor=student,
            request_id=None,
            attempt_id=attempt_id,
            order=first.order_index,
            selected="B",
        )
        attempt_service.submit_attempt(s, actor=student, request_id=None, attempt_id=attempt_id)
        s.commit()

    _login(client, student)
    r_all = client.get(f"/attempts/{attempt_id}/review")
    assert r_all.status_code == 200
    r_wrong = client.get(f"/attempts/{attempt_id}/review?wrong_only=1")
    assert r_wrong.status_code == 200
    # The wrong-only page should show 3 wrong rows; the all page shows 4.
    assert r_wrong.text.count("<tr>") < r_all.text.count("<tr>")


def test_review_question_shows_selected_vs_correct(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id, _ = _seed_exam(admin, nonce)
    with SessionLocal() as s:
        # keep student as _TestUser dataclass
        attempt = attempt_service.start_attempt(
            s, actor=student, request_id=None, exam_id=exam_id, mode=AttemptMode.practice
        )
        s.commit()
        attempt_id = attempt.id
        attempt_service.save_answer(
            s,
            actor=student,
            request_id=None,
            attempt_id=attempt_id,
            order=1,
            selected="A",  # wrong on single-choice
        )
        attempt_service.submit_attempt(s, actor=student, request_id=None, attempt_id=attempt_id)
        s.commit()

    _login(client, student)
    r = client.get(f"/attempts/{attempt_id}/review/q/1")
    assert r.status_code == 200
    assert "you picked" in r.text
    assert "Wrong" in r.text


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def test_question_report_post_creates_row_and_audit(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id, qids = _seed_exam(admin, nonce)
    _login(client, student)
    csrf = _csrf(client, f"/exams/p08t-{nonce}/e1")  # any GET that issues csrf
    if not csrf:
        # Fallback to the auth/me page (we know auth/login issues csrf too).
        csrf = _csrf(client, "/auth/login")
    qid = qids[0]
    r = client.post(
        f"/questions/{qid}/reports",
        data={"reason": "wrong_answer", "comment": "looks off", "csrf_token": csrf},
    )
    assert r.status_code == 200
    assert "Report filed" in r.text
    with SessionLocal() as s:
        rows = list(s.scalars(select(QuestionReport).where(QuestionReport.question_id == qid)))
        assert len(rows) == 1
        audits = list(
            s.scalars(
                select(AuditLog).where(AuditLog.action == AuditAction.QUESTION_REPORT_FILED.value)
            )
        )
        assert len(audits) >= 1


def test_admin_reports_list_and_resolve(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    student = _make_user(nonce + "stu", UserRole.student)
    exam_id, qids = _seed_exam(admin, nonce)
    qid = qids[0]
    # Pre-create one report row.
    with SessionLocal() as s:
        # keep student as _TestUser dataclass
        from app.models.enums import ReportReason

        rpt = QuestionReport(
            question_id=qid,
            user_id=student.id,
            reason=ReportReason.wrong_answer,
            comment="x",
            status=ReportStatus.open,
        )
        s.add(rpt)
        s.flush()
        s.commit()
        rpt_id = rpt.id

    _login(client, admin)
    r = client.get("/admin/question-reports")
    assert r.status_code == 200
    assert f"report-{rpt_id}" in r.text or str(rpt_id) in r.text

    csrf = _csrf(client, "/admin/question-reports")
    r = client.post(
        f"/admin/question-reports/{rpt_id}/resolve",
        data={"csrf_token": csrf},
    )
    assert r.status_code == 200
    with SessionLocal() as s:
        rpt2 = s.get(QuestionReport, rpt_id)
        assert rpt2.status == ReportStatus.resolved
        assert rpt2.resolved_at is not None


def test_admin_reports_non_admin_403(client: TestClient, nonce: str) -> None:
    student = _make_user(nonce + "stu", UserRole.student)
    _login(client, student)
    r = client.get("/admin/question-reports")
    assert r.status_code == 403
