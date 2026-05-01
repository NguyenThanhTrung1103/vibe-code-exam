"""Phase 07 — snapshot + shuffle helper for attempt creation.

`list_published_active_questions` returns the publishable subset of an
exam's questions in a deterministic id-asc order — caller shuffles once
and persists `order_index` on `attempt_answers`.

A question is "publishable" iff:
  * `Question.exam_id == exam_id`
  * `Question.deleted_at IS NULL`
  * `Question.retired_at IS NULL`
  * `Question.status == 'published'`

Phase 07 freezes this snapshot via `attempt_answers.order_index`.
Subsequent admin edits / retirements MUST NOT mutate that snapshot —
this is enforced by `attempt_answers` referencing `question_id` directly
(no JOIN-on-publish-status filter at read time during attempts).
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.enums import QuestionStatus
from app.models.questions import Question


def publishable_question_filter():
    """Composable WHERE clause — usable in any SELECT for attempt eligibility."""
    return and_(
        Question.deleted_at.is_(None),
        Question.retired_at.is_(None),
        Question.status == QuestionStatus.published,
    )


def list_published_active_questions(session: Session, *, exam_id: int) -> list[Question]:
    """Return the publishable question snapshot for `exam_id`, ordered by id.

    Caller shuffles + persists `order_index` 1..N immediately after this call,
    inside the same transaction that creates the `Attempt` row.
    """
    return list(
        session.scalars(
            select(Question)
            .where(Question.exam_id == exam_id)
            .where(publishable_question_filter())
            .order_by(Question.id)
        )
    )


def shuffled_question_ids(
    questions: Sequence[Question], *, rng: random.Random | None = None
) -> list[int]:
    """One-shot permutation of question ids. Optional `rng` for reproducible tests."""
    rng = rng or random.Random()
    ids = [q.id for q in questions]
    rng.shuffle(ids)
    return ids


__all__ = [
    "list_published_active_questions",
    "publishable_question_filter",
    "shuffled_question_ids",
]
