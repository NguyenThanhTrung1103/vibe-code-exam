"""Excel import header (`imports`) + per-row staging (`import_items`).

`import_items` is **new** per Phase 02 plan §Architecture — row-level Excel
import tracking that lets confirm be idempotent and debug-traceable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    ImportItemStatus,
    ImportPublishStatus,
    ImportStatus,
    Visibility,
)


class Import(Base):
    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    uploaded_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Optional admin-supplied label; UI falls back to file_name when blank.
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set by parser detector at upload time — `xlsx` / `examtopics_html` /
    # `qblock_pdf` / `qblock_text` / NULL when detection is ambiguous.
    detected_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_exam_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("exams.id", ondelete="RESTRICT"), nullable=True
    )
    column_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="import_status", native_enum=True, create_type=True),
        nullable=False,
        default=ImportStatus.uploaded,
    )
    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility, name="visibility", native_enum=True, create_type=False),
        nullable=False,
        default=Visibility.private,
    )
    publish_status: Mapped[ImportPublishStatus] = mapped_column(
        Enum(
            ImportPublishStatus,
            name="import_publish_status",
            native_enum=True,
            create_type=True,
        ),
        nullable=False,
        default=ImportPublishStatus.draft,
    )
    total_questions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_questions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_questions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duplicates_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification_budget_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    verification_spent_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    import_source_claim: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_log: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportItem(Base, TimestampMixin):
    """Row-level staging — Phase 02 plan §Architecture (NEW)."""

    __tablename__ = "import_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("imports.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    normalized_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ImportItemStatus] = mapped_column(
        Enum(
            ImportItemStatus,
            name="import_item_status",
            native_enum=True,
            create_type=True,
        ),
        nullable=False,
        default=ImportItemStatus.parsed,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    question_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("questions.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("import_id", "row_number", "sheet_name", name="uq_import_items_row"),
        Index("ix_import_items_import_status", "import_id", "status"),
        Index("ix_import_items_content_hash", "content_hash"),
    )
