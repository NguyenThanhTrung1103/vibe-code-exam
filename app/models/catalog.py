"""Catalog hierarchy: Provider → ProductVersion + Course → Exam → Topic."""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.enums import ExamPublishStatus, Visibility


class Provider(Base, TimestampMixin):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ProductVersion(Base, TimestampMixin):
    __tablename__ = "product_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    product_name: Mapped[str] = mapped_column(String(128), nullable=False)
    product_version: Mapped[str] = mapped_column(String(64), nullable=False)
    documentation_base_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retired_at: Mapped[date | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "product_name",
            "product_version",
            name="uq_product_versions_provider_name_version",
        ),
    )


class Course(Base, TimestampMixin):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (UniqueConstraint("provider_id", "slug", name="uq_courses_provider_slug"),)


class Exam(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    exam_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    vendor_exam_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passing_score_percent: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility, name="visibility", native_enum=True, create_type=True),
        nullable=False,
        default=Visibility.private,
    )
    publish_status: Mapped[ExamPublishStatus] = mapped_column(
        Enum(ExamPublishStatus, name="exam_publish_status", native_enum=True, create_type=True),
        nullable=False,
        default=ExamPublishStatus.draft,
    )
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_verified_at: Mapped[date | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("course_id", "slug", name="uq_exams_course_slug"),)


class Topic(Base, TimestampMixin):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("exams.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    __table_args__ = (UniqueConstraint("exam_id", "slug", name="uq_topics_exam_slug"),)
