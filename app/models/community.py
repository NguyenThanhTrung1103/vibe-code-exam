"""Phase 13 — community discussion sources (CDEA Sprint-1).

`community_discussion_sources` caches the community-signal evidence for a
question (votes, discussion URL, optional summary). Phase 13 only writes
the `pending` candidate row from the import pipeline; Phase 14 fetches,
Phase 15 analyses, Phase 16 displays.

Schema follows NewPRD v2 §10.2 with red-team v2 fixes already applied:
  * FK question_id ON DELETE RESTRICT (red-team #6).
  * total_votes is a regular INT column populated by Python (red-team #10).
  * approved_at_confidence + row_version for approval-race safety (red-team #11).
  * fetch_lease_expires_at + index for worker reconcile (red-team #5).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CommunitySourceName(enum.StrEnum):
    examtopics = "examtopics"
    vendor_forum = "vendor_forum"
    reddit = "reddit"
    blog = "blog"
    other = "other"


class CommunityFetchStatus(enum.StrEnum):
    pending = "pending"
    fetching = "fetching"
    ok = "ok"
    blocked = "blocked"
    not_found = "not_found"
    timeout = "timeout"
    parse_error = "parse_error"
    rate_limited = "rate_limited"


class CommunityConsensus(enum.StrEnum):
    agrees_with_given = "agrees_with_given"
    disagrees_with_given = "disagrees_with_given"
    # `split` shadows the inherited `str.split` method in mypy's view; the
    # enum value is required by spec (NewPRD §10.2). Suppress the false
    # positive — runtime behavior is correct.
    split = "split"  # type: ignore[assignment]
    unknown = "unknown"


class CommunityConfidence(enum.StrEnum):
    """Order matters — `unknown` < `low` < `medium` < `high` so DESC sort
    surfaces high-confidence rows first in the review queue.
    """

    unknown = "unknown"
    low = "low"
    medium = "medium"
    high = "high"


class CommunityDiscussionSource(Base, TimestampMixin):
    __tablename__ = "community_discussion_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    question_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_name: Mapped[CommunitySourceName] = mapped_column(
        Enum(
            CommunitySourceName,
            name="community_source_name",
            native_enum=True,
            create_type=True,
        ),
        nullable=False,
        default=CommunitySourceName.examtopics,
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    external_question_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    discussion_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vote_distribution: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    total_votes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetch_status: Mapped[CommunityFetchStatus] = mapped_column(
        Enum(
            CommunityFetchStatus,
            name="community_fetch_status",
            native_enum=True,
            create_type=True,
        ),
        nullable=False,
        default=CommunityFetchStatus.pending,
    )
    last_fetch_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fetch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetch_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    community_answer: Mapped[str | None] = mapped_column(String(20), nullable=True)
    community_confidence: Mapped[CommunityConfidence] = mapped_column(
        Enum(
            CommunityConfidence,
            name="community_confidence",
            native_enum=True,
            create_type=True,
        ),
        nullable=False,
        default=CommunityConfidence.unknown,
    )
    community_consensus: Mapped[CommunityConsensus] = mapped_column(
        Enum(
            CommunityConsensus,
            name="community_consensus",
            native_enum=True,
            create_type=True,
        ),
        nullable=False,
        default=CommunityConsensus.unknown,
    )
    answer_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    common_arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_for_student: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_at_confidence: Mapped[CommunityConfidence | None] = mapped_column(
        Enum(
            CommunityConfidence,
            name="community_confidence",
            native_enum=True,
            create_type=False,
        ),
        nullable=True,
    )
    ignored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "source_name",
            "source_url",
            name="uq_community_sources_question_url",
        ),
        CheckConstraint(
            "vote_distribution IS NULL OR jsonb_typeof(vote_distribution) = 'object'",
            name="ck_vote_distribution_object",
        ),
        Index("ix_cds_question", "question_id"),
        Index("ix_cds_status", "fetch_status"),
        Index(
            "ix_cds_review_queue",
            "needs_review",
            postgresql_where=text("needs_review = TRUE"),
        ),
        Index(
            "ix_cds_approved",
            "question_id",
            postgresql_where=text("approved_for_student = TRUE"),
        ),
        Index("ix_cds_external_id", "external_question_id"),
        Index(
            "ix_cds_lease",
            "fetch_lease_expires_at",
            postgresql_where=text("fetch_status IN ('fetching')"),
        ),
    )


__all__ = [
    "CommunityConfidence",
    "CommunityConsensus",
    "CommunityDiscussionSource",
    "CommunityFetchStatus",
    "CommunitySourceName",
]
