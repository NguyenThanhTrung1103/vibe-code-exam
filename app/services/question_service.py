"""Phase 06 — admin Question bank CRUD service.

Every mutation funnels through `write_audit_log()` in the same session as
the SQL change (same pattern as Phases 03–05).

Public surface:
  create_question(...)         — manual create with options + explanation
  update_question(...)         — text / type / topic / difficulty edits
  set_options(...)             — replace the option set + correct labels
  set_overall_explanation(...) — upsert the overall explanation row
  retire(...)                  — soft retire (sets `retired_at`,
                                  status=retired)
  restore(...)                 — clears `retired_at`, status back to
                                  `verified_low` (manual edits earn
                                  no automatic high confidence).
  assign_topic_bulk(...)       — assign topic to a set of questions

All callers commit. Errors:
  QuestionNotFoundError, QuestionValidationError.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.models.catalog import Topic
from app.models.enums import (
    ActorType,
    ConfidenceLevel,
    ExplanationStatus,
    QuestionDifficulty,
    QuestionStatus,
    QuestionType,
)
from app.models.questions import (
    Question,
    QuestionExplanation,
    QuestionOption,
)
from app.models.users import User

OPTION_LABELS = ("A", "B", "C", "D", "E", "F")


class QuestionNotFoundError(LookupError):
    pass


class QuestionValidationError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_for_hash(text: str) -> str:
    """Mirror Phase 05's normalization for hash purposes only — strip and
    collapse whitespace, lowercase. Intentionally lighter than the full
    `import_normalizer.normalize_text` because edits already arrived sanitized.
    """
    return " ".join(text.strip().split())


def _content_hash(question_text: str, options: list[tuple[str, str]]) -> str:
    """Same canonical recipe as `app/services/import_dedup.py:content_hash`.

    sha256(normalized_q + "|" + "||".join(sorted(non_empty_normalized_opts)))
    """
    q = _normalize_for_hash(question_text or "")
    opts = sorted(_normalize_for_hash(t) for _, t in options if t and t.strip())
    payload = q + "|" + "||".join(opts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_options(
    options: list[tuple[str, str]], correct: list[str], qtype: QuestionType
) -> None:
    """Raise `QuestionValidationError` if option set is malformed."""
    if not options or len(options) < 2:
        raise QuestionValidationError("at least two non-empty options required")
    if len(options) > 6:
        raise QuestionValidationError("at most six options allowed (A–F)")
    labels = [lbl for lbl, _ in options]
    if labels != sorted(labels) or labels != list(OPTION_LABELS[: len(labels)]):
        raise QuestionValidationError("option labels must be A,B,...; consecutive starting at A")
    valid = set(labels)
    if not correct:
        raise QuestionValidationError("correct_answer must reference at least one option")
    for c in correct:
        if c not in valid:
            raise QuestionValidationError(f"correct label {c!r} has no matching option")
    if qtype == QuestionType.single and len(correct) != 1:
        raise QuestionValidationError("single-choice question requires exactly one correct label")
    if qtype == QuestionType.multiple and len(correct) < 2:
        raise QuestionValidationError(
            "multiple-choice question requires at least two correct labels"
        )


def _get_or_raise(session: Session, question_id: int) -> Question:
    q = session.get(Question, question_id)
    if q is None:
        raise QuestionNotFoundError(f"question {question_id} not found")
    return q


def _get_active_or_raise(session: Session, question_id: int) -> Question:
    q = _get_or_raise(session, question_id)
    if q.deleted_at is not None:
        raise QuestionNotFoundError(f"question {question_id} not found (deleted)")
    return q


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def create_question(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    exam_id: int,
    question_text: str,
    options: list[tuple[str, str]],
    correct_answer: list[str],
    question_type: QuestionType,
    difficulty: QuestionDifficulty | None = None,
    topic_id: int | None = None,
    overall_explanation: str | None = None,
) -> Question:
    if not question_text or not question_text.strip():
        raise QuestionValidationError("question_text required")
    _validate_options(options, correct_answer, question_type)

    correct_set = set(correct_answer)
    q = Question(
        exam_id=exam_id,
        topic_id=topic_id,
        question_text=question_text,
        question_type=question_type,
        difficulty=difficulty,
        status=QuestionStatus.verified_low,
        confidence_level=ConfidenceLevel.unknown,
        content_hash=_content_hash(question_text, options),
        given_answer=",".join(correct_answer),
    )
    session.add(q)
    session.flush()

    for idx, (label, text) in enumerate(options):
        session.add(
            QuestionOption(
                question_id=q.id,
                label=label,
                option_text=text,
                is_correct=label in correct_set,
                order_index=idx,
            )
        )
    if overall_explanation:
        session.add(
            QuestionExplanation(
                question_id=q.id,
                overall_explanation=overall_explanation,
                status=ExplanationStatus.approved,
            )
        )

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.QUESTION_CREATED,
        entity_type="question",
        entity_id=q.id,
        new_value={
            "exam_id": exam_id,
            "topic_id": topic_id,
            "question_type": question_type.value,
            "difficulty": difficulty.value if difficulty else None,
            "correct_answer": correct_answer,
            "options": [list(o) for o in options],
        },
        request_id=request_id,
    )
    session.flush()
    return q


# ---------------------------------------------------------------------------
# Update — text / type / topic / difficulty
# ---------------------------------------------------------------------------


def update_question(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    question_id: int,
    question_text: str | None = None,
    question_type: QuestionType | None = None,
    difficulty: QuestionDifficulty | None = None,
    topic_id: int | None = None,
    status: QuestionStatus | None = None,
) -> Question:
    q = _get_active_or_raise(session, question_id)
    old: dict = {}
    new: dict = {}

    if question_text is not None:
        if not question_text.strip():
            raise QuestionValidationError("question_text cannot be empty")
        old["question_text"] = q.question_text
        new["question_text"] = question_text
        q.question_text = question_text
    if question_type is not None and question_type != q.question_type:
        old["question_type"] = q.question_type.value
        new["question_type"] = question_type.value
        q.question_type = question_type
    if difficulty is not None and difficulty != q.difficulty:
        old["difficulty"] = q.difficulty.value if q.difficulty else None
        new["difficulty"] = difficulty.value
        q.difficulty = difficulty
    if topic_id is not None and topic_id != q.topic_id:
        if topic_id == 0:  # 0 == clear
            old["topic_id"] = q.topic_id
            new["topic_id"] = None
            q.topic_id = None
        else:
            # Verify topic exists + belongs to same exam.
            t = session.get(Topic, topic_id)
            if t is None:
                raise QuestionValidationError(f"topic {topic_id} not found")
            if t.exam_id != q.exam_id:
                raise QuestionValidationError(f"topic {topic_id} belongs to a different exam")
            old["topic_id"] = q.topic_id
            new["topic_id"] = topic_id
            q.topic_id = topic_id
    if status is not None and status != q.status:
        old["status"] = q.status.value
        new["status"] = status.value
        q.status = status

    if "question_text" in new:
        # text edit changes the canonical hash
        existing_opts = list(
            session.scalars(
                select(QuestionOption)
                .where(QuestionOption.question_id == q.id)
                .order_by(QuestionOption.order_index)
            )
        )
        if existing_opts:
            opts = [(o.label or "", o.option_text or "") for o in existing_opts]
            q.content_hash = _content_hash(q.question_text, opts)

    if not new:
        return q

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.QUESTION_TEXT_EDITED
        if "question_text" in new
        else AuditAction.QUESTION_OPTION_EDITED,
        entity_type="question",
        entity_id=q.id,
        old_value=old,
        new_value=new,
        request_id=request_id,
    )
    return q


# ---------------------------------------------------------------------------
# Options — full replacement (simpler than per-row diff)
# ---------------------------------------------------------------------------


def set_options(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    question_id: int,
    options: list[tuple[str, str]],
    correct_answer: list[str],
) -> Question:
    q = _get_active_or_raise(session, question_id)
    _validate_options(options, correct_answer, q.question_type)

    existing = list(
        session.scalars(
            select(QuestionOption)
            .where(QuestionOption.question_id == q.id)
            .order_by(QuestionOption.order_index)
        )
    )
    old_opts = [(o.label or "", o.option_text or "", bool(o.is_correct)) for o in existing]
    correct_set = set(correct_answer)

    # Wipe + reinsert. Simpler than diff; option count is tiny (<6).
    session.execute(delete(QuestionOption).where(QuestionOption.question_id == q.id))
    session.flush()

    for idx, (label, text) in enumerate(options):
        session.add(
            QuestionOption(
                question_id=q.id,
                label=label,
                option_text=text,
                is_correct=label in correct_set,
                order_index=idx,
            )
        )
    q.given_answer = ",".join(correct_answer)
    q.content_hash = _content_hash(q.question_text, options)

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.QUESTION_OPTION_EDITED,
        entity_type="question",
        entity_id=q.id,
        old_value={"options": [[a, b, c] for (a, b, c) in old_opts]},
        new_value={
            "options": [[a, b] for (a, b) in options],
            "correct_answer": correct_answer,
        },
        request_id=request_id,
    )
    return q


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------


def set_overall_explanation(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    question_id: int,
    text: str,
) -> QuestionExplanation:
    q = _get_active_or_raise(session, question_id)
    text = (text or "").strip()
    if not text:
        raise QuestionValidationError("explanation cannot be empty")

    existing = session.scalars(
        select(QuestionExplanation).where(QuestionExplanation.question_id == q.id)
    ).first()
    old_text = existing.overall_explanation if existing else None
    if existing is None:
        existing = QuestionExplanation(
            question_id=q.id,
            overall_explanation=text,
            status=ExplanationStatus.approved,
        )
        session.add(existing)
    else:
        existing.overall_explanation = text
        existing.status = ExplanationStatus.approved

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.QUESTION_EXPLANATION_EDITED,
        entity_type="question",
        entity_id=q.id,
        old_value={"overall_explanation": old_text},
        new_value={"overall_explanation": text},
        request_id=request_id,
    )
    return existing


# ---------------------------------------------------------------------------
# Retire / restore
# ---------------------------------------------------------------------------


def retire(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    question_id: int,
    reason: str,
) -> Question:
    q = _get_active_or_raise(session, question_id)
    if q.retired_at is not None:
        return q
    reason = (reason or "").strip()[:500]
    q.retired_at = datetime.now(UTC)
    q.status = QuestionStatus.retired
    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.QUESTION_RETIRED,
        entity_type="question",
        entity_id=q.id,
        new_value={"reason": reason or None, "retired_at": q.retired_at.isoformat()},
        reason=reason or None,
        request_id=request_id,
    )
    return q


def restore(session: Session, *, actor: User, request_id: str | None, question_id: int) -> Question:
    q = _get_or_raise(session, question_id)
    if q.retired_at is None:
        return q
    q.retired_at = None
    q.status = QuestionStatus.verified_low
    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.QUESTION_RESTORED,
        entity_type="question",
        entity_id=q.id,
        request_id=request_id,
    )
    return q


# ---------------------------------------------------------------------------
# Bulk topic assign
# ---------------------------------------------------------------------------


def assign_topic_bulk(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    question_ids: list[int],
    topic_id: int | None,
) -> int:
    """Assign `topic_id` (or None) to all matching questions. Returns count.

    Validates that the topic belongs to the same exam as every question.
    """
    if not question_ids:
        return 0
    questions = list(
        session.scalars(
            select(Question)
            .where(Question.id.in_(question_ids))
            .where(Question.deleted_at.is_(None))
        )
    )
    if not questions:
        return 0
    if topic_id is not None and topic_id != 0:
        topic = session.get(Topic, topic_id)
        if topic is None:
            raise QuestionValidationError(f"topic {topic_id} not found")
        for q in questions:
            if q.exam_id != topic.exam_id:
                raise QuestionValidationError(
                    f"question {q.id} belongs to exam {q.exam_id}; "
                    f"topic {topic_id} belongs to exam {topic.exam_id}"
                )
        new_topic = topic_id
    else:
        new_topic = None

    session.execute(
        update(Question)
        .where(Question.id.in_([q.id for q in questions]))
        .values(topic_id=new_topic)
    )

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.QUESTION_TOPIC_ASSIGNED,
        entity_type="question",
        entity_id=None,
        new_value={
            "question_ids": [q.id for q in questions],
            "topic_id": new_topic,
        },
        request_id=request_id,
    )
    return len(questions)


__all__ = [
    "QuestionNotFoundError",
    "QuestionValidationError",
    "assign_topic_bulk",
    "create_question",
    "restore",
    "retire",
    "set_options",
    "set_overall_explanation",
    "update_question",
]
