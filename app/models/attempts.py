"""User attempts + per-question answers (with frozen `order_index`).

`attempt_answers.order_index` is the source of truth for question order in a
given attempt — set once at start, never changes (Phase 02 plan addition).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import AttemptMode


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Either user_id (authenticated owner) or guest_token (anonymous owner) is
    # set — DB CHECK constraint `ck_attempts_owner` enforces this. Migration
    # 0008_attempts_guest_token relaxed user_id to NULLABLE.
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    guest_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exam_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("exams.id", ondelete="RESTRICT"), nullable=False
    )
    exam_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mode: Mapped[AttemptMode] = mapped_column(
        Enum(AttemptMode, name="attempt_mode", native_enum=True, create_type=True),
        nullable=False,
        default=AttemptMode.practice,
    )
    score_percent: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    total_questions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correct_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wrong_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    question_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    selected_options: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Phase 02 plan addition: 1..N presentation order, frozen at attempt start.
    # This is the source of truth for question ordering within an attempt.
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("attempt_id", "order_index", name="uq_attempt_answers_attempt_order"),
        Index("ix_attempt_answers_question_correct", "question_id", "is_correct"),
    )
