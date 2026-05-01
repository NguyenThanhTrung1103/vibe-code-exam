"""Glossary terms — Phase 3 schema-stub. No service code in Phase 1."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Enum,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import GlossaryStatus


class GlossaryTerm(Base, TimestampMixin):
    __tablename__ = "glossary_terms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    term_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    term_vi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[GlossaryStatus] = mapped_column(
        Enum(GlossaryStatus, name="glossary_status", native_enum=True, create_type=True),
        nullable=False,
        default=GlossaryStatus.pending,
    )
