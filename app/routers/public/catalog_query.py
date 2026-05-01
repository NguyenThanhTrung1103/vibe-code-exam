"""Shared SELECT helpers for public catalog routes.

Centralising the visibility filters (`publish_status='published'` AND
`deleted_at IS NULL`) keeps "draft / soft-deleted leakage" bugs out — every
public query funnels through the same Select objects.

Soft-delete behaviour for Phase 04:
  * `Exam` has a `deleted_at` column; we filter it explicitly here.
  * `Provider`/`Course`/`Topic` use refuse-if-children hard-delete (see
    catalog_service); a deleted row simply does not exist, so no extra
    filter is needed for them.
"""

from __future__ import annotations

from sqlalchemy import Select, and_, select

from app.models.catalog import Course, Exam, Provider, Topic
from app.models.enums import ExamPublishStatus


def published_exam_filter():
    """Composable filter — used in joins/scalars to keep the rule explicit."""
    return and_(
        Exam.publish_status == ExamPublishStatus.published,
        Exam.deleted_at.is_(None),
    )


def select_published_exams() -> Select:
    return select(Exam).where(published_exam_filter())


def select_provider_with_published_exams() -> Select:
    """Distinct providers that have at least one published, non-deleted exam."""
    return (
        select(Provider)
        .join(Course, Course.provider_id == Provider.id)
        .join(Exam, Exam.course_id == Course.id)
        .where(published_exam_filter())
        .distinct()
    )


def select_topics_for_exam(exam_id: int) -> Select:
    return select(Topic).where(Topic.exam_id == exam_id).order_by(Topic.name)
