"""Phase 08 — attempt scoring + topic breakdown.

Pure compute over the frozen Phase-07 snapshot:
  * Per question: `is_correct = set(selected_labels) == set(correct_labels)`
    — all-or-nothing.
  * Aggregate: total / correct / wrong / score_percent / passed.
  * Topic breakdown via `attempt_answers → questions → topics`
    (questions without `topic_id` roll into "Untagged").

Public surface:
  * `compute_attempt_score(session, *, attempt_id)` — write `is_correct`
     onto every `attempt_answer`, persist aggregates onto `attempts`.
     Idempotent on re-run.
  * `topic_breakdown(session, *, attempt_id)` — returns list of
     `TopicBreakdown` named tuples for the result page.
  * `weak_topic_recommendations(...)` — top 2 weakest topics with
     ≥3 questions each AND ≥10 pp below overall.

Caller commits.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.models.attempts import Attempt, AttemptAnswer
from app.models.catalog import Exam, Topic
from app.models.enums import ActorType
from app.models.questions import Question, QuestionOption
from app.models.users import User

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class AttemptScore:
    total: int
    correct: int
    wrong: int  # answered-but-wrong + unanswered both count as wrong
    score_percent: float  # 0..100, two decimals
    passed: bool | None  # None when exam has no passing_score_percent set


@dataclass(slots=True, frozen=True)
class TopicBreakdown:
    topic_id: int | None  # None = "Untagged"
    topic_name: str
    weight: float | None
    total: int
    correct: int

    @property
    def percent(self) -> float:
        return round(100.0 * self.correct / self.total, 2) if self.total else 0.0


@dataclass(slots=True, frozen=True)
class WeakTopicRecommendation:
    topic_id: int | None
    topic_name: str
    score_gap_pp: float  # how many percentage points below overall
    correct: int
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_selected_set(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {p.strip().upper() for p in raw.split(",") if p.strip()}


def _correct_labels_per_question(
    session: Session, *, question_ids: list[int]
) -> dict[int, set[str]]:
    """One query: load all option rows for the involved questions."""
    if not question_ids:
        return {}
    rows = list(
        session.execute(
            select(
                QuestionOption.question_id, QuestionOption.label, QuestionOption.is_correct
            ).where(QuestionOption.question_id.in_(question_ids))
        )
    )
    out: dict[int, set[str]] = {}
    for qid, label, is_correct in rows:
        if is_correct and label:
            out.setdefault(qid, set()).add(label.upper())
        else:
            # Ensure every question_id has an entry so the score logic
            # treats "no correct option" deterministically (all wrong).
            out.setdefault(qid, set())
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def compute_attempt_score(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    attempt_id: int,
) -> AttemptScore:
    """Idempotent score computation. Caller commits."""
    attempt = session.get(Attempt, attempt_id)
    if attempt is None:
        raise LookupError(f"attempt {attempt_id} not found")

    answers = list(
        session.scalars(
            select(AttemptAnswer)
            .where(AttemptAnswer.attempt_id == attempt_id)
            .order_by(AttemptAnswer.order_index)
        )
    )
    qids = [a.question_id for a in answers]
    correct_map = _correct_labels_per_question(session, question_ids=qids)

    correct_count = 0
    for a in answers:
        selected = _parse_selected_set(a.selected_options)
        truth = correct_map.get(a.question_id, set())
        is_correct = bool(truth) and selected == truth
        a.is_correct = is_correct
        if is_correct:
            correct_count += 1

    total = len(answers)
    wrong = total - correct_count
    score_percent = round(100.0 * correct_count / total, 2) if total else 0.0
    passed: bool | None = None
    exam = session.get(Exam, attempt.exam_id)
    if exam is not None and exam.passing_score_percent is not None:
        threshold = float(exam.passing_score_percent)
        passed = score_percent >= threshold

    attempt.total_questions = total
    attempt.correct_count = correct_count
    attempt.wrong_count = wrong
    attempt.score_percent = float(score_percent)
    attempt.passed = passed

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.ATTEMPT_SCORED,
        entity_type="attempt",
        entity_id=attempt.id,
        new_value={
            "total": total,
            "correct": correct_count,
            "wrong": wrong,
            "score_percent": float(score_percent),
            "passed": passed,
        },
        request_id=request_id,
    )

    return AttemptScore(
        total=total,
        correct=correct_count,
        wrong=wrong,
        score_percent=score_percent,
        passed=passed,
    )


# ---------------------------------------------------------------------------
# Topic breakdown
# ---------------------------------------------------------------------------


def topic_breakdown(session: Session, *, attempt_id: int) -> list[TopicBreakdown]:
    """Aggregate by topic. Questions without topic_id roll into "Untagged"."""
    rows = list(
        session.execute(
            select(
                Question.topic_id,
                AttemptAnswer.is_correct,
            )
            .join(Question, Question.id == AttemptAnswer.question_id)
            .where(AttemptAnswer.attempt_id == attempt_id)
        )
    )
    by_topic: dict[int | None, list[bool]] = {}
    for topic_id, is_correct in rows:
        by_topic.setdefault(topic_id, []).append(bool(is_correct))

    topic_ids = [tid for tid in by_topic if tid is not None]
    topics = {
        t.id: t for t in session.scalars(select(Topic).where(Topic.id.in_(topic_ids or [-1])))
    }

    out: list[TopicBreakdown] = []
    for tid, results in by_topic.items():
        total = len(results)
        correct = sum(1 for r in results if r)
        if tid is None:
            out.append(
                TopicBreakdown(
                    topic_id=None,
                    topic_name="Untagged",
                    weight=None,
                    total=total,
                    correct=correct,
                )
            )
        else:
            t = topics.get(tid)
            out.append(
                TopicBreakdown(
                    topic_id=tid,
                    topic_name=t.name if t else f"Topic {tid}",
                    weight=float(t.weight) if t and t.weight is not None else None,
                    total=total,
                    correct=correct,
                )
            )
    # Sort weakest-first.
    out.sort(key=lambda b: (b.percent, -b.total))
    return out


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


def weak_topic_recommendations(
    breakdown: list[TopicBreakdown], *, overall_percent: float
) -> list[WeakTopicRecommendation]:
    """Top 2 topics where total ≥3 AND topic_percent ≤ overall - 10pp."""
    candidates: list[WeakTopicRecommendation] = []
    for b in breakdown:
        if b.total < 3:
            continue
        gap = round(overall_percent - b.percent, 2)
        if gap < 10:
            continue
        candidates.append(
            WeakTopicRecommendation(
                topic_id=b.topic_id,
                topic_name=b.topic_name,
                score_gap_pp=gap,
                correct=b.correct,
                total=b.total,
            )
        )
    candidates.sort(key=lambda c: c.score_gap_pp, reverse=True)
    return candidates[:2]


__all__ = [
    "AttemptScore",
    "TopicBreakdown",
    "WeakTopicRecommendation",
    "compute_attempt_score",
    "topic_breakdown",
    "weak_topic_recommendations",
]
