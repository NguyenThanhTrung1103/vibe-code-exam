"""Question content + options + explanations + duplicate-group stub."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.enums import (
    ConfidenceLevel,
    DetectionMethod,
    ExplanationStatus,
    QuestionDifficulty,
    QuestionStatus,
    QuestionType,
    StaleStatus,
)


class Question(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # FKs
    exam_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("exams.id", ondelete="RESTRICT"), nullable=False
    )
    topic_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("topics.id", ondelete="RESTRICT"), nullable=True
    )

    # Content
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[QuestionType] = mapped_column(
        Enum(QuestionType, name="question_type", native_enum=True, create_type=True),
        nullable=False,
    )
    difficulty: Mapped[QuestionDifficulty | None] = mapped_column(
        Enum(QuestionDifficulty, name="question_difficulty", native_enum=True, create_type=True),
        nullable=True,
    )

    # Versioning
    question_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    product_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("product_versions.id", ondelete="RESTRICT"), nullable=True
    )
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_against_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    superseded_by_question_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Dedup
    content_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    duplicate_group_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("question_duplicate_groups.id", ondelete="RESTRICT"),
        nullable=True,
    )
    canonical_question_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=True
    )

    # AI / verification state
    status: Mapped[QuestionStatus] = mapped_column(
        Enum(QuestionStatus, name="question_status", native_enum=True, create_type=True),
        nullable=False,
        default=QuestionStatus.imported,
    )
    source_import_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("imports.id", ondelete="RESTRICT"), nullable=True
    )
    given_answer: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_verified_answer: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    confidence_level: Mapped[ConfidenceLevel | None] = mapped_column(
        Enum(ConfidenceLevel, name="confidence_level", native_enum=True, create_type=True),
        nullable=True,
    )
    needs_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Staleness
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_verification_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verification_ttl_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    stale_status: Mapped[StaleStatus] = mapped_column(
        Enum(StaleStatus, name="stale_status", native_enum=True, create_type=True),
        nullable=False,
        default=StaleStatus.fresh,
    )

    # Phase 02 plan addition: back-trace to import row.
    # {import_id, import_item_id, file_name, sheet_name, row_number}
    source_locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_questions_exam_status_deleted", "exam_id", "status", "deleted_at"),
        Index("ix_questions_review_queue", "needs_human_review", "confidence_level"),
        Index("ix_questions_content_hash", "content_hash"),
        Index(
            "ix_questions_due_partial",
            "next_verification_due_at",
            postgresql_where=text("stale_status <> 'fresh'"),
        ),
    )


class QuestionOption(Base):
    __tablename__ = "question_options"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(CHAR(1), nullable=True)
    option_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int | None] = mapped_column(Integer, nullable=True)


class QuestionExplanation(Base, TimestampMixin):
    __tablename__ = "question_explanations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    correct_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    overall_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[ExplanationStatus] = mapped_column(
        Enum(ExplanationStatus, name="explanation_status", native_enum=True, create_type=True),
        nullable=False,
        default=ExplanationStatus.draft,
    )


class QuestionDuplicateGroup(Base, TimestampMixin):
    """Phase 2 schema-stub — groups near-duplicate questions."""

    __tablename__ = "question_duplicate_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_question_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=True
    )
    detection_method: Mapped[DetectionMethod] = mapped_column(
        Enum(DetectionMethod, name="detection_method", native_enum=True, create_type=True),
        nullable=False,
        default=DetectionMethod.hash,
    )
