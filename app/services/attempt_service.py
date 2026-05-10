"""Phase 07 — attempt orchestration service.

Public surface:
  start_attempt(...)        — validate exam + snapshot questions + insert Attempt
                               + N pre-created `attempt_answers` rows.
  resume_attempt(...)       — find an in-progress attempt for (user, exam).
  get_question_view(...)    — load attempt_answer at order_index, plus question
                               + options. Owner-checked.
  save_answer(...)          — validate selected labels, persist sorted as
                               comma-joined string. Idempotent.
  toggle_flag(...)          — flip `attempt_answers.flagged`.
  submit_attempt(...)       — set `finished_at` if NULL. Idempotent. The
                               actual scoring is wired in Phase 08 (this
                               service just sets a marker for now).
  ensure_not_expired(...)   — server-side timer enforcement: if exam mode
                               and `now() - started_at >= time_limit`, force
                               an idempotent submit and raise
                               `AttemptExpiredError`.

Owner check is the same on every method:
  attempt.user_id != current_user.id  →  AttemptForbiddenError (HTTP 403).

Caller commits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.models.attempts import Attempt, AttemptAnswer
from app.models.catalog import Exam
from app.models.enums import (
    ActorType,
    AttemptMode,
    ExamPublishStatus,
    UserRole,
)
from app.models.questions import Question, QuestionOption
from app.models.users import User
from app.services.question_selector import (
    list_published_active_questions,
    list_questions_for_admin_preview,
    shuffled_question_ids,
)

if TYPE_CHECKING:  # pragma: no cover
    pass


_OPTION_LABELS_VALID = ("A", "B", "C", "D", "E", "F", "G", "H")

# Mock Exam time budget: 1.5 minutes per question, computed from
# `attempt.total_questions` so a 30-question Mock Exam runs 45 minutes
# regardless of what `exams.time_limit_seconds` says. Keeps the timer
# fair when the learner picks a smaller subset on the setup page.
_MOCK_SECONDS_PER_QUESTION = 90


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AttemptError(Exception):
    """Base for Phase 07 attempt-service errors."""


class AttemptNotFoundError(AttemptError):
    pass


class AttemptForbiddenError(AttemptError):
    """Raised when current user does not own the attempt."""


class AttemptValidationError(AttemptError):
    pass


class AttemptExpiredError(AttemptError):
    """Raised when an exam-mode attempt is past its deadline.

    Routes catch this and redirect to the submitted page.
    """


# ---------------------------------------------------------------------------
# Read-only views
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class QuestionView:
    """One question's worth of view data — what the template renders."""

    attempt: Attempt
    answer: AttemptAnswer
    question: Question
    options: list[QuestionOption]
    total: int  # total questions in this attempt
    selected_labels: list[str]
    time_remaining_seconds: int | None  # only set in exam mode
    topic_label: str = "—"  # populated when caller resolves Topic; "—" otherwise


@dataclass(slots=True)
class PageView:
    """Phase 18.6 — a page of N QuestionViews + page metadata."""

    attempt: Attempt
    page_num: int
    page_size: int
    total_questions: int
    total_pages: int
    page_start: int  # 1-based first global position on this page
    page_end: int  # 1-based last global position on this page
    views: list[QuestionView]
    time_remaining_seconds: int | None  # only set in exam mode
    revealed_positions: set[int] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_attempt_or_raise(session: Session, attempt_id: int) -> Attempt:
    a = session.get(Attempt, attempt_id)
    if a is None:
        raise AttemptNotFoundError(f"attempt {attempt_id} not found")
    return a


def _check_owner(attempt: Attempt, user: User | None) -> None:
    """Owner check that accepts both authenticated users and guests.

    `user is None` means the route layer already proved guest ownership via
    the signed cookie (`get_attempt_owner` in `app.auth.permissions`); in
    that case the attempt must itself be a guest attempt (i.e. `user_id IS
    NULL`). Anything else is an attempt to read someone else's attempt.
    """
    if user is None:
        if attempt.user_id is not None:
            raise AttemptForbiddenError(
                f"attempt {attempt.id} is owned by a user, not a guest"
            )
        return
    if attempt.user_id != user.id:
        raise AttemptForbiddenError(f"attempt {attempt.id} does not belong to user {user.id}")


def _audit_actor(user: User | None) -> tuple[ActorType, int | None]:
    """Resolve `(actor_type, actor_id)` for audit-log writes.

    Guests audit as `system` with `actor_id=None` — we don't have a stable
    principal for them, and the existing schema has `ActorType.{user, ai,
    system}` only.
    """
    if user is None:
        return ActorType.system, None
    return ActorType.user, user.id


def _parse_selected_labels(raw: str | list[str] | None) -> list[str]:
    """Normalise to sorted unique upper-case labels in {'A'..'H'}.

    Accepts:
      None         → []          (clear selection)
      ""           → []
      "A"          → ["A"]
      "A,C"        → ["A", "C"]
      ["A","C"]    → ["A", "C"]
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    else:
        parts = [str(p).strip().upper() for p in raw if str(p).strip()]
    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        unique.append(p)
    return sorted(unique)


def _question_option_labels(session: Session, question_id: int) -> set[str]:
    rows = session.scalars(
        select(QuestionOption.label).where(QuestionOption.question_id == question_id)
    )
    return {r for r in rows if r}


def _exam_publishable(exam: Exam) -> bool:
    return exam.publish_status == ExamPublishStatus.published and exam.deleted_at is None


# ---------------------------------------------------------------------------
# Start / resume
# ---------------------------------------------------------------------------


def start_attempt(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    exam_id: int,
    mode: AttemptMode,
    question_count: int | None = None,
) -> Attempt:
    """Create a new attempt with frozen `order_index`. Caller commits.

    Raises `AttemptValidationError` for empty / unpublished exams.
    Resumes an existing in-progress attempt if one exists for (user, exam).

    `question_count` is an optional cap on the number of questions in the
    attempt — used by Mock Exam mode to randomly subset (e.g. 35 of 57).
    None = use all available questions.
    """
    exam = session.get(Exam, exam_id)
    if exam is None or not _exam_publishable(exam):
        raise AttemptValidationError(f"exam {exam_id} is not available for attempts")

    if mode not in (AttemptMode.practice, AttemptMode.exam):
        raise AttemptValidationError(
            f"mode {mode!r} not supported in Phase 07 (use practice or exam)"
        )

    existing = session.scalars(
        select(Attempt)
        .where(
            and_(
                Attempt.user_id == actor.id,
                Attempt.exam_id == exam_id,
                Attempt.finished_at.is_(None),
            )
        )
        .order_by(Attempt.id.desc())
        .limit(1)
    ).first()
    if existing is not None:
        write_audit_log(
            session,
            actor_type=ActorType.user,
            actor_id=actor.id,
            action=AuditAction.ATTEMPT_RESUMED,
            entity_type="attempt",
            entity_id=existing.id,
            new_value={"exam_id": exam_id, "mode": existing.mode.value},
            request_id=request_id,
        )
        return existing

    questions = list_published_active_questions(session, exam_id=exam_id)
    if not questions:
        raise AttemptValidationError("no questions available yet for this exam")

    by_id = {q.id: q for q in questions}
    ordered_ids = shuffled_question_ids(questions)
    if question_count is not None and question_count > 0:
        ordered_ids = ordered_ids[:question_count]

    attempt = Attempt(
        user_id=actor.id,
        exam_id=exam_id,
        exam_version=exam.exam_version,
        mode=mode,
        started_at=datetime.now(UTC),
        total_questions=len(ordered_ids),
    )
    session.add(attempt)
    session.flush()  # need attempt.id

    for idx, qid in enumerate(ordered_ids, start=1):
        q = by_id[qid]
        session.add(
            AttemptAnswer(
                attempt_id=attempt.id,
                question_id=q.id,
                question_version=q.question_version,
                order_index=idx,
                selected_options=None,
                is_correct=None,
                flagged=False,
            )
        )

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.ATTEMPT_STARTED,
        entity_type="attempt",
        entity_id=attempt.id,
        new_value={
            "exam_id": exam_id,
            "mode": mode.value,
            "total_questions": len(ordered_ids),
            "exam_version": exam.exam_version,
        },
        request_id=request_id,
    )
    session.flush()
    return attempt


def start_guest_attempt(
    session: Session,
    *,
    request_id: str | None,
    exam_id: int,
    guest_token: str,
    mode: AttemptMode = AttemptMode.practice,
    question_count: int | None = None,
) -> Attempt:
    """Phase 18 — start (or resume) an attempt for an anonymous guest.

    Same shape as `start_attempt(actor=user, mode=...)` but:
      * `attempt.user_id = None`, `attempt.guest_token = guest_token`
      * Resumes the most recent in-progress attempt for
        `(exam_id, guest_token)` so refreshing the start endpoint with
        the same cookie does not stack new attempts.
      * Audits as `ActorType.system` because there is no stable principal.

    `mode` defaults to practice (Learning Mode); pass `AttemptMode.exam` for
    Mock Exam Mode. `question_count` optionally caps the random subset
    (e.g. 35 of 57) — used by Mock Exam.

    Caller is responsible for verifying the cookie signature before
    calling this. `guest_token` is the raw UUID, not the signed cookie.
    """
    if not guest_token:
        raise AttemptValidationError("guest_token required")
    if mode not in (AttemptMode.practice, AttemptMode.exam):
        raise AttemptValidationError(
            f"mode {mode!r} not supported for guests (use practice or exam)"
        )

    exam = session.get(Exam, exam_id)
    if exam is None or not _exam_publishable(exam):
        raise AttemptValidationError(f"exam {exam_id} is not available for attempts")

    existing = session.scalars(
        select(Attempt)
        .where(
            and_(
                Attempt.guest_token == guest_token,
                Attempt.exam_id == exam_id,
                Attempt.finished_at.is_(None),
            )
        )
        .order_by(Attempt.id.desc())
        .limit(1)
    ).first()
    if existing is not None:
        write_audit_log(
            session,
            actor_type=ActorType.system,
            actor_id=None,
            action=AuditAction.ATTEMPT_RESUMED,
            entity_type="attempt",
            entity_id=existing.id,
            new_value={"exam_id": exam_id, "mode": existing.mode.value, "guest": True},
            request_id=request_id,
        )
        return existing

    questions = list_published_active_questions(session, exam_id=exam_id)
    if not questions:
        raise AttemptValidationError("no questions available yet for this exam")

    by_id = {q.id: q for q in questions}
    ordered_ids = shuffled_question_ids(questions)
    if question_count is not None and question_count > 0:
        ordered_ids = ordered_ids[:question_count]

    attempt = Attempt(
        user_id=None,
        guest_token=guest_token,
        exam_id=exam_id,
        exam_version=exam.exam_version,
        mode=mode,
        started_at=datetime.now(UTC),
        total_questions=len(ordered_ids),
    )
    session.add(attempt)
    session.flush()

    for idx, qid in enumerate(ordered_ids, start=1):
        q = by_id[qid]
        session.add(
            AttemptAnswer(
                attempt_id=attempt.id,
                question_id=q.id,
                question_version=q.question_version,
                order_index=idx,
                selected_options=None,
                is_correct=None,
                flagged=False,
            )
        )

    write_audit_log(
        session,
        actor_type=ActorType.system,
        actor_id=None,
        action=AuditAction.ATTEMPT_STARTED,
        entity_type="attempt",
        entity_id=attempt.id,
        new_value={
            "exam_id": exam_id,
            "mode": mode.value,
            "total_questions": len(ordered_ids),
            "exam_version": exam.exam_version,
            "guest": True,
        },
        request_id=request_id,
    )
    session.flush()
    return attempt


def start_admin_preview_attempt(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    exam_id: int,
) -> Attempt:
    """Start (or resume) a practice attempt on a draft/private exam — admin only.

    Bypasses `publish_status` / visibility checks so operators can smoke-test
    freshly imported `QuestionStatus.imported` rows. Regular `/attempts/start`
    remains restricted to published exams for non-preview flows.
    """
    if actor.role != UserRole.admin:
        raise AttemptForbiddenError("practice preview is limited to administrators")

    exam = session.get(Exam, exam_id)
    if exam is None or exam.deleted_at is not None:
        raise AttemptValidationError(f"exam {exam_id} not found")

    mode = AttemptMode.practice
    existing = session.scalars(
        select(Attempt)
        .where(
            and_(
                Attempt.user_id == actor.id,
                Attempt.exam_id == exam_id,
                Attempt.finished_at.is_(None),
            )
        )
        .order_by(Attempt.id.desc())
        .limit(1)
    ).first()
    if existing is not None:
        write_audit_log(
            session,
            actor_type=ActorType.user,
            actor_id=actor.id,
            action=AuditAction.ATTEMPT_RESUMED,
            entity_type="attempt",
            entity_id=existing.id,
            new_value={"exam_id": exam_id, "mode": existing.mode.value, "admin_preview": True},
            request_id=request_id,
        )
        return existing

    questions = list_questions_for_admin_preview(session, exam_id=exam_id)
    if not questions:
        raise AttemptValidationError("no questions in this exam yet for preview")

    by_id = {q.id: q for q in questions}
    ordered_ids = shuffled_question_ids(questions)

    attempt = Attempt(
        user_id=actor.id,
        exam_id=exam_id,
        exam_version=exam.exam_version,
        mode=mode,
        started_at=datetime.now(UTC),
        total_questions=len(ordered_ids),
    )
    session.add(attempt)
    session.flush()

    for idx, qid in enumerate(ordered_ids, start=1):
        q = by_id[qid]
        session.add(
            AttemptAnswer(
                attempt_id=attempt.id,
                question_id=q.id,
                question_version=q.question_version,
                order_index=idx,
                selected_options=None,
                is_correct=None,
                flagged=False,
            )
        )

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.ATTEMPT_STARTED,
        entity_type="attempt",
        entity_id=attempt.id,
        new_value={
            "exam_id": exam_id,
            "mode": mode.value,
            "total_questions": len(ordered_ids),
            "exam_version": exam.exam_version,
            "admin_preview": True,
        },
        request_id=request_id,
    )
    session.flush()
    return attempt


# ---------------------------------------------------------------------------
# Question view
# ---------------------------------------------------------------------------


def get_question_view(
    session: Session,
    *,
    actor: User | None,
    attempt_id: int,
    order: int,
) -> QuestionView:
    a = _get_attempt_or_raise(session, attempt_id)
    _check_owner(a, actor)

    answer = session.scalars(
        select(AttemptAnswer)
        .where(AttemptAnswer.attempt_id == a.id)
        .where(AttemptAnswer.order_index == order)
    ).first()
    if answer is None:
        raise AttemptNotFoundError(f"attempt {a.id} has no question at order {order}")

    q = session.get(Question, answer.question_id)
    if q is None:
        raise AttemptNotFoundError(f"question {answer.question_id} missing for attempt {a.id}")
    options = list(
        session.scalars(
            select(QuestionOption)
            .where(QuestionOption.question_id == q.id)
            .order_by(QuestionOption.order_index)
        )
    )
    total = (
        session.scalar(select(_count(AttemptAnswer.id)).where(AttemptAnswer.attempt_id == a.id))
        or 0
    )

    return QuestionView(
        attempt=a,
        answer=answer,
        question=q,
        options=options,
        total=int(total),
        selected_labels=_parse_selected_labels(answer.selected_options),
        time_remaining_seconds=_time_remaining_seconds(session, a),
        topic_label=_resolve_topic_label(session, q.topic_id),
    )


def get_page_views(
    session: Session,
    *,
    actor: User | None,
    attempt_id: int,
    page_num: int,
    page_size: int = 5,
    revealed_positions: set[int] | None = None,
) -> PageView:
    """Phase 18.6 — load a page of N consecutive questions for the practice UI.

    Batches DB reads:
      * one SELECT for the slice of attempt_answers
      * one SELECT for all questions in the slice
      * one SELECT for all options across those questions
      * one SELECT for all referenced topics
    so render cost is O(1) round-trips per page rather than per-question.
    """
    if page_size < 1:
        raise AttemptValidationError("page_size must be >= 1")
    a = _get_attempt_or_raise(session, attempt_id)
    _check_owner(a, actor)

    total = (
        session.scalar(select(_count(AttemptAnswer.id)).where(AttemptAnswer.attempt_id == a.id))
        or 0
    )
    total = int(total)
    total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 1
    if page_num < 1 or page_num > total_pages:
        raise AttemptNotFoundError(f"attempt {a.id} has no page {page_num}")

    start = (page_num - 1) * page_size + 1
    end = min(start + page_size - 1, total) if total > 0 else 0

    answers: list[AttemptAnswer] = []
    questions_by_id: dict[int, Question] = {}
    options_by_qid: dict[int, list[QuestionOption]] = {}
    topics_by_id: dict[int, str] = {}

    if total > 0:
        answers = list(
            session.scalars(
                select(AttemptAnswer)
                .where(AttemptAnswer.attempt_id == a.id)
                .where(AttemptAnswer.order_index >= start)
                .where(AttemptAnswer.order_index <= end)
                .order_by(AttemptAnswer.order_index)
            )
        )
        if not answers:
            raise AttemptNotFoundError(f"attempt {a.id} page {page_num} is empty")

        qids = [ans.question_id for ans in answers]
        questions_by_id = {
            q.id: q
            for q in session.scalars(select(Question).where(Question.id.in_(qids)))
        }
        for opt in session.scalars(
            select(QuestionOption)
            .where(QuestionOption.question_id.in_(qids))
            .order_by(QuestionOption.question_id, QuestionOption.order_index)
        ):
            options_by_qid.setdefault(opt.question_id, []).append(opt)

        topic_ids = {q.topic_id for q in questions_by_id.values() if q.topic_id is not None}
        if topic_ids:
            from app.models.catalog import (
                Topic,  # noqa: PLC0415 — lazy import keeps catalog out of hot path
            )

            for t in session.scalars(select(Topic).where(Topic.id.in_(topic_ids))):
                topics_by_id[t.id] = t.name or "—"

    revealed = set(revealed_positions or [])
    views: list[QuestionView] = []
    for ans in answers:
        q = questions_by_id.get(ans.question_id)
        if q is None:
            raise AttemptNotFoundError(
                f"question {ans.question_id} missing for attempt {a.id}"
            )
        topic_label = (
            topics_by_id.get(q.topic_id, "—") if q.topic_id is not None else "—"
        )
        views.append(
            QuestionView(
                attempt=a,
                answer=ans,
                question=q,
                options=options_by_qid.get(q.id, []),
                total=total,
                selected_labels=_parse_selected_labels(ans.selected_options),
                time_remaining_seconds=None,  # exposed on PageView, not per-q
                topic_label=topic_label,
            )
        )

    return PageView(
        attempt=a,
        page_num=page_num,
        page_size=page_size,
        total_questions=total,
        total_pages=total_pages,
        page_start=start if total > 0 else 0,
        page_end=end,
        views=views,
        time_remaining_seconds=_time_remaining_seconds(session, a),
        revealed_positions=revealed,
    )


def _resolve_topic_label(session: Session, topic_id: int | None) -> str:
    if topic_id is None:
        return "—"
    from app.models.catalog import (
        Topic,  # noqa: PLC0415 — lazy import keeps catalog out of hot path
    )

    topic = session.get(Topic, topic_id)
    return (topic.name if topic and topic.name else "—") or "—"


def _count(col):
    from sqlalchemy import func

    return func.count(col)


def _time_remaining_seconds(session: Session, attempt: Attempt) -> int | None:
    """Remaining seconds for exam mode; None for practice.

    Mock Exam budget = `_MOCK_SECONDS_PER_QUESTION × attempt.total_questions`
    (1.5 min × N). Falls back to `exam.time_limit_seconds` only if total_questions
    is missing, so legacy attempts without a frozen count still get a timer.
    """
    if attempt.mode != AttemptMode.exam:
        return None
    n = attempt.total_questions or 0
    if n > 0:
        budget = n * _MOCK_SECONDS_PER_QUESTION
    else:
        exam = session.get(Exam, attempt.exam_id)
        if exam is None or not exam.time_limit_seconds:
            return None
        budget = exam.time_limit_seconds
    if attempt.started_at is None:
        return budget
    elapsed = (datetime.now(UTC) - attempt.started_at).total_seconds()
    remaining = int(budget - elapsed)
    return max(0, remaining)


# ---------------------------------------------------------------------------
# Save / flag
# ---------------------------------------------------------------------------


def save_answer(
    session: Session,
    *,
    actor: User | None,
    request_id: str | None,
    attempt_id: int,
    order: int,
    selected: str | list[str] | None,
) -> AttemptAnswer:
    """Persist `selected` labels onto the matching attempt_answers row.

    Idempotent — same input twice produces the same DB state. Validates each
    label exists on the question. Raises:
      * AttemptForbiddenError on cross-user
      * AttemptNotFoundError on bad order
      * AttemptValidationError on bogus label
      * AttemptExpiredError on time-up (also forces submit; caller redirects)
    """
    a = _get_attempt_or_raise(session, attempt_id)
    _check_owner(a, actor)
    if a.finished_at is not None:
        raise AttemptValidationError(f"attempt {a.id} already submitted")
    ensure_not_expired(session, actor=actor, request_id=request_id, attempt=a)

    answer = session.scalars(
        select(AttemptAnswer)
        .where(AttemptAnswer.attempt_id == a.id)
        .where(AttemptAnswer.order_index == order)
    ).first()
    if answer is None:
        raise AttemptNotFoundError(f"attempt {a.id} has no question at order {order}")

    labels = _parse_selected_labels(selected)
    valid_labels = _question_option_labels(session, answer.question_id)
    invalid = [lbl for lbl in labels if lbl not in valid_labels]
    if invalid:
        raise AttemptValidationError(f"selected label(s) {invalid!r} not on this question")

    answer.selected_options = ",".join(labels) if labels else None
    return answer


def toggle_flag(
    session: Session,
    *,
    actor: User | None,
    request_id: str | None,
    attempt_id: int,
    order: int,
) -> AttemptAnswer:
    a = _get_attempt_or_raise(session, attempt_id)
    _check_owner(a, actor)
    answer = session.scalars(
        select(AttemptAnswer)
        .where(AttemptAnswer.attempt_id == a.id)
        .where(AttemptAnswer.order_index == order)
    ).first()
    if answer is None:
        raise AttemptNotFoundError(f"attempt {a.id} has no question at order {order}")
    answer.flagged = not answer.flagged
    return answer


# ---------------------------------------------------------------------------
# Timer enforcement + submit
# ---------------------------------------------------------------------------


def ensure_not_expired(
    session: Session,
    *,
    actor: User | None,
    request_id: str | None,
    attempt: Attempt,
) -> None:
    """If exam mode and time expired, force idempotent submit + raise."""
    if attempt.finished_at is not None:
        return
    remaining = _time_remaining_seconds(session, attempt)
    if remaining is None or remaining > 0:
        return
    # Time's up — submit without exception, then raise so caller can redirect.
    _submit_idempotent(
        session,
        actor=actor,
        request_id=request_id,
        attempt=attempt,
        action=AuditAction.ATTEMPT_EXPIRED,
    )
    raise AttemptExpiredError(f"attempt {attempt.id} time expired")


def submit_attempt(
    session: Session,
    *,
    actor: User | None,
    request_id: str | None,
    attempt_id: int,
) -> Attempt:
    """Idempotent submit — sets `finished_at` and audits.

    Phase 08 will hook into this AFTER the row is finalised here to compute
    score / pass-fail. For Phase 07 alone, finishing the attempt is enough.
    """
    a = _get_attempt_or_raise(session, attempt_id)
    _check_owner(a, actor)
    _submit_idempotent(
        session,
        actor=actor,
        request_id=request_id,
        attempt=a,
        action=AuditAction.ATTEMPT_SUBMITTED,
    )
    return a


def _submit_idempotent(
    session: Session,
    *,
    actor: User | None,
    request_id: str | None,
    attempt: Attempt,
    action: AuditAction,
) -> None:
    if attempt.finished_at is not None:
        return  # already submitted; do nothing
    now = datetime.now(UTC)
    attempt.finished_at = now
    if attempt.started_at is not None:
        attempt.duration_seconds = max(0, int((now - attempt.started_at).total_seconds()))
    actor_type, actor_id = _audit_actor(actor)
    write_audit_log(
        session,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type="attempt",
        entity_id=attempt.id,
        new_value={
            "finished_at": now.isoformat(),
            "duration_seconds": attempt.duration_seconds,
        },
        request_id=request_id,
    )
    # Phase 08 — compute score in the same transaction as the submit.
    # Local import keeps the call optional if scoring_service is rolled back.
    from app.services import scoring_service  # noqa: PLC0415

    scoring_service.compute_attempt_score(
        session,
        actor=actor,
        request_id=request_id,
        attempt_id=attempt.id,
    )


__all__ = [
    "AttemptError",
    "AttemptExpiredError",
    "AttemptForbiddenError",
    "AttemptNotFoundError",
    "AttemptValidationError",
    "PageView",
    "QuestionView",
    "ensure_not_expired",
    "get_page_views",
    "get_question_view",
    "save_answer",
    "start_admin_preview_attempt",
    "start_attempt",
    "start_guest_attempt",
    "submit_attempt",
    "toggle_flag",
]
