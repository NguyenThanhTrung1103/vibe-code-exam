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

from dataclasses import dataclass
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
)
from app.models.questions import Question, QuestionOption
from app.models.users import User
from app.services.question_selector import (
    list_published_active_questions,
    shuffled_question_ids,
)

if TYPE_CHECKING:  # pragma: no cover
    pass


_OPTION_LABELS_VALID = ("A", "B", "C", "D", "E")


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_attempt_or_raise(session: Session, attempt_id: int) -> Attempt:
    a = session.get(Attempt, attempt_id)
    if a is None:
        raise AttemptNotFoundError(f"attempt {attempt_id} not found")
    return a


def _check_owner(attempt: Attempt, user: User) -> None:
    if attempt.user_id != user.id:
        raise AttemptForbiddenError(f"attempt {attempt.id} does not belong to user {user.id}")


def _parse_selected_labels(raw: str | list[str] | None) -> list[str]:
    """Normalise to sorted unique upper-case labels in {'A'..'E'}.

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
) -> Attempt:
    """Create a new attempt with frozen `order_index`. Caller commits.

    Raises `AttemptValidationError` for empty / unpublished exams.
    Resumes an existing in-progress attempt if one exists for (user, exam).
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


# ---------------------------------------------------------------------------
# Question view
# ---------------------------------------------------------------------------


def get_question_view(
    session: Session,
    *,
    actor: User,
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
    )


def _count(col):
    from sqlalchemy import func

    return func.count(col)


def _time_remaining_seconds(session: Session, attempt: Attempt) -> int | None:
    """Remaining seconds for exam mode; None for practice or unset limit."""
    if attempt.mode != AttemptMode.exam:
        return None
    exam = session.get(Exam, attempt.exam_id)
    if exam is None or not exam.time_limit_seconds:
        return None
    if attempt.started_at is None:
        return exam.time_limit_seconds
    elapsed = (datetime.now(UTC) - attempt.started_at).total_seconds()
    remaining = int(exam.time_limit_seconds - elapsed)
    return max(0, remaining)


# ---------------------------------------------------------------------------
# Save / flag
# ---------------------------------------------------------------------------


def save_answer(
    session: Session,
    *,
    actor: User,
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
    actor: User,
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
    actor: User,
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
    actor: User,
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
    actor: User,
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
    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
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
    "QuestionView",
    "ensure_not_expired",
    "get_question_view",
    "save_answer",
    "start_attempt",
    "submit_attempt",
    "toggle_flag",
]
