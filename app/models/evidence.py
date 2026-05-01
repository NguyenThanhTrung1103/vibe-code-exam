"""Source-domain trust list + question references + fetch logs.

`source_domains` is seeded with ~5 entries in Phase 02 — full trust list lands
in Phase 2. `question_references` and `evidence_fetch_logs` are schema-only
in Phase 1; the AI verifier in Phase 2 populates them.
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
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    EvidenceFetcher,
    FetchStatus,
    SourceType,
    TrustLevel,
)


class SourceDomain(Base, TimestampMixin):
    __tablename__ = "source_domains"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type", native_enum=True, create_type=True),
        nullable=False,
    )
    trust_level: Mapped[TrustLevel] = mapped_column(
        Enum(TrustLevel, name="trust_level", native_enum=True, create_type=True),
        nullable=False,
    )
    allowed_for_verification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuestionReference(Base):
    """Phase 2 — populated by AI verifier. Schema only here."""

    __tablename__ = "question_references"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    source_domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_domains.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Denormalized snapshot at fetch time so trust evaluations are reproducible.
    source_type: Mapped[SourceType | None] = mapped_column(
        Enum(SourceType, name="source_type", native_enum=True, create_type=False),
        nullable=True,
    )
    trust_level: Mapped[TrustLevel | None] = mapped_column(
        Enum(TrustLevel, name="trust_level", native_enum=True, create_type=False),
        nullable=True,
    )
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cached_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fetch_status: Mapped[FetchStatus | None] = mapped_column(
        Enum(FetchStatus, name="fetch_status", native_enum=True, create_type=True),
        nullable=True,
    )
    trust_policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_question_references_source_status", "source_domain_id", "fetch_status"),
    )


class EvidenceFetchLog(Base):
    """Phase 2 — fetch attempt log. Schema only."""

    __tablename__ = "evidence_fetch_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    http_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetcher: Mapped[EvidenceFetcher] = mapped_column(
        Enum(EvidenceFetcher, name="evidence_fetcher", native_enum=True, create_type=True),
        nullable=False,
        default=EvidenceFetcher.worker,
    )
