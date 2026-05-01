"""Catalog write-funnel: every admin mutation passes through here.

Each `create_*` / `update_*` / `soft_delete_*` / `publish_*` /
`unpublish_*` function:
  1. Performs the SA change(s).
  2. Calls `write_audit_log()` in the same session.
  3. Returns the entity (or None for soft-delete).

The caller (route handler) is responsible for `session.commit()` — that's
how Phase 03's same-transaction audit guarantee survives. If the route
catches an error and rolls back, the audit row rolls back with it.

Errors:
  * `DuplicateSlugError` — caller should map to 400 with a friendly message.
  * Any other `IntegrityError` propagates — usually a programmer bug.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.models.catalog import Course, Exam, ProductVersion, Provider, Topic
from app.models.enums import ActorType, ExamPublishStatus
from app.models.users import User


class DuplicateSlugError(ValueError):
    """Raised when a unique constraint on a slug pair fires."""


# ---------------------------------------------------------------------------
# Query helpers — soft-delete filter + lookups
# ---------------------------------------------------------------------------


def _active_provider_query() -> Select:
    return select(Provider)  # Provider has no SoftDeleteMixin


def _active_exam_query() -> Select:
    return select(Exam).where(Exam.deleted_at.is_(None))


def _common_audit_kwargs(actor: User, request_id: str | None) -> dict[str, Any]:
    return {
        "actor_type": ActorType.user,
        "actor_id": actor.id,
        "request_id": request_id,
    }


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


def create_provider(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    name: str,
    slug: str,
    description: str | None = None,
    logo_url: str | None = None,
) -> Provider:
    p = Provider(name=name, slug=slug, description=description, logo_url=logo_url)
    session.add(p)
    try:
        session.flush()
    except IntegrityError as e:
        session.rollback()
        if (
            "uq_providers_slug" in str(e.orig).lower()
            or "providers_slug_key" in str(e.orig).lower()
        ):
            raise DuplicateSlugError(f"provider slug {slug!r} already in use") from e
        raise

    write_audit_log(
        session,
        action=AuditAction.PROVIDER_CREATED,
        entity_type="provider",
        entity_id=p.id,
        new_value={"name": name, "slug": slug},
        **_common_audit_kwargs(actor, request_id),
    )
    return p


def update_provider(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    provider_id: int,
    **changes: Any,
) -> Provider:
    p = session.get(Provider, provider_id)
    if p is None:
        raise ValueError(f"provider {provider_id} not found")

    old = {k: getattr(p, k) for k in changes}
    for k, v in changes.items():
        setattr(p, k, v)
    try:
        session.flush()
    except IntegrityError as e:
        session.rollback()
        if "providers_slug_key" in str(e.orig).lower():
            raise DuplicateSlugError(f"provider slug {changes.get('slug')!r} already in use") from e
        raise

    write_audit_log(
        session,
        action=AuditAction.PROVIDER_UPDATED,
        entity_type="provider",
        entity_id=p.id,
        old_value=_jsonable(old),
        new_value=_jsonable(changes),
        **_common_audit_kwargs(actor, request_id),
    )
    return p


def soft_delete_provider(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    provider_id: int,
) -> None:
    p = session.get(Provider, provider_id)
    if p is None:
        return
    # Provider has no `deleted_at`. We delete the row.
    # Cascade: protected by FK ondelete=RESTRICT — caller must clear children
    # first, OR (Phase 1 stance) we just refuse delete if any course exists.
    has_children = session.scalars(
        select(Course.id).where(Course.provider_id == provider_id).limit(1)
    ).first()
    if has_children is not None:
        raise ValueError("cannot delete provider with courses; soft-delete the courses first")
    session.delete(p)

    write_audit_log(
        session,
        action=AuditAction.PROVIDER_SOFT_DELETED,
        entity_type="provider",
        entity_id=provider_id,
        old_value={"name": p.name, "slug": p.slug},
        **_common_audit_kwargs(actor, request_id),
    )


# ---------------------------------------------------------------------------
# ProductVersion
# ---------------------------------------------------------------------------


def create_product_version(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    provider_id: int,
    product_name: str,
    product_version: str,
    documentation_base_url: str | None = None,
    release_date=None,
) -> ProductVersion:
    pv = ProductVersion(
        provider_id=provider_id,
        product_name=product_name,
        product_version=product_version,
        documentation_base_url=documentation_base_url,
        release_date=release_date,
    )
    session.add(pv)
    try:
        session.flush()
    except IntegrityError as e:
        session.rollback()
        if "uq_product_versions_provider_name_version" in str(e.orig).lower():
            raise DuplicateSlugError(
                f"product_version {product_name} {product_version} already exists for provider"
            ) from e
        raise
    write_audit_log(
        session,
        action=AuditAction.PRODUCT_VERSION_CREATED,
        entity_type="product_version",
        entity_id=pv.id,
        new_value={
            "provider_id": provider_id,
            "product_name": product_name,
            "product_version": product_version,
        },
        **_common_audit_kwargs(actor, request_id),
    )
    return pv


def update_product_version(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    product_version_id: int,
    **changes: Any,
) -> ProductVersion:
    pv = session.get(ProductVersion, product_version_id)
    if pv is None:
        raise ValueError(f"product_version {product_version_id} not found")
    old = {k: getattr(pv, k) for k in changes}
    for k, v in changes.items():
        setattr(pv, k, v)
    try:
        session.flush()
    except IntegrityError as e:
        session.rollback()
        if "uq_product_versions_provider_name_version" in str(e.orig).lower():
            raise DuplicateSlugError("product_version unique conflict") from e
        raise
    write_audit_log(
        session,
        action=AuditAction.PRODUCT_VERSION_UPDATED,
        entity_type="product_version",
        entity_id=pv.id,
        old_value=_jsonable(old),
        new_value=_jsonable(changes),
        **_common_audit_kwargs(actor, request_id),
    )
    return pv


def soft_delete_product_version(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    product_version_id: int,
) -> None:
    pv = session.get(ProductVersion, product_version_id)
    if pv is None:
        return
    session.delete(pv)
    write_audit_log(
        session,
        action=AuditAction.PRODUCT_VERSION_SOFT_DELETED,
        entity_type="product_version",
        entity_id=product_version_id,
        old_value={"product_name": pv.product_name, "product_version": pv.product_version},
        **_common_audit_kwargs(actor, request_id),
    )


# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------


def create_course(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    provider_id: int,
    name: str,
    slug: str,
    description: str | None = None,
    level: str | None = None,
    status: str | None = None,
) -> Course:
    c = Course(
        provider_id=provider_id,
        name=name,
        slug=slug,
        description=description,
        level=level,
        status=status,
    )
    session.add(c)
    try:
        session.flush()
    except IntegrityError as e:
        session.rollback()
        if "uq_courses_provider_slug" in str(e.orig).lower():
            raise DuplicateSlugError(
                f"course slug {slug!r} already used under this provider"
            ) from e
        raise
    write_audit_log(
        session,
        action=AuditAction.COURSE_CREATED,
        entity_type="course",
        entity_id=c.id,
        new_value={"provider_id": provider_id, "name": name, "slug": slug, "level": level},
        **_common_audit_kwargs(actor, request_id),
    )
    return c


def update_course(
    session: Session, *, actor: User, request_id: str | None, course_id: int, **changes: Any
) -> Course:
    c = session.get(Course, course_id)
    if c is None:
        raise ValueError(f"course {course_id} not found")
    old = {k: getattr(c, k) for k in changes}
    for k, v in changes.items():
        setattr(c, k, v)
    try:
        session.flush()
    except IntegrityError as e:
        session.rollback()
        if "uq_courses_provider_slug" in str(e.orig).lower():
            raise DuplicateSlugError(
                f"course slug {changes.get('slug')!r} already used under this provider"
            ) from e
        raise
    write_audit_log(
        session,
        action=AuditAction.COURSE_UPDATED,
        entity_type="course",
        entity_id=c.id,
        old_value=_jsonable(old),
        new_value=_jsonable(changes),
        **_common_audit_kwargs(actor, request_id),
    )
    return c


def soft_delete_course(
    session: Session, *, actor: User, request_id: str | None, course_id: int
) -> None:
    c = session.get(Course, course_id)
    if c is None:
        return
    has_children = session.scalars(
        select(Exam.id).where(and_(Exam.course_id == course_id, Exam.deleted_at.is_(None))).limit(1)
    ).first()
    if has_children is not None:
        raise ValueError("cannot delete course with active exams; soft-delete those first")
    session.delete(c)
    write_audit_log(
        session,
        action=AuditAction.COURSE_SOFT_DELETED,
        entity_type="course",
        entity_id=course_id,
        old_value={"name": c.name, "slug": c.slug},
        **_common_audit_kwargs(actor, request_id),
    )


# ---------------------------------------------------------------------------
# Exam (has SoftDeleteMixin + publish toggle)
# ---------------------------------------------------------------------------


def create_exam(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    course_id: int,
    name: str,
    slug: str,
    code: str | None = None,
    description: str | None = None,
    vendor_exam_code: str | None = None,
    valid_from=None,
    valid_until=None,
    time_limit_seconds: int | None = None,
    passing_score_percent: Decimal | None = None,
) -> Exam:
    e = Exam(
        course_id=course_id,
        name=name,
        slug=slug,
        code=code,
        description=description,
        vendor_exam_code=vendor_exam_code,
        valid_from=valid_from,
        valid_until=valid_until,
        time_limit_seconds=time_limit_seconds,
        passing_score_percent=passing_score_percent,
    )
    session.add(e)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if "uq_exams_course_slug" in str(exc.orig).lower():
            raise DuplicateSlugError(f"exam slug {slug!r} already used under this course") from exc
        raise
    write_audit_log(
        session,
        action=AuditAction.EXAM_CREATED,
        entity_type="exam",
        entity_id=e.id,
        new_value={"course_id": course_id, "name": name, "slug": slug, "code": code},
        **_common_audit_kwargs(actor, request_id),
    )
    return e


def update_exam(
    session: Session, *, actor: User, request_id: str | None, exam_id: int, **changes: Any
) -> Exam:
    e = session.get(Exam, exam_id)
    if e is None or e.deleted_at is not None:
        raise ValueError(f"exam {exam_id} not found")
    old = {k: getattr(e, k) for k in changes}
    for k, v in changes.items():
        setattr(e, k, v)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if "uq_exams_course_slug" in str(exc.orig).lower():
            raise DuplicateSlugError(
                f"exam slug {changes.get('slug')!r} already used under this course"
            ) from exc
        raise
    write_audit_log(
        session,
        action=AuditAction.EXAM_UPDATED,
        entity_type="exam",
        entity_id=e.id,
        old_value=_jsonable(old),
        new_value=_jsonable(changes),
        **_common_audit_kwargs(actor, request_id),
    )
    return e


def publish_exam(session: Session, *, actor: User, request_id: str | None, exam_id: int) -> Exam:
    e = session.get(Exam, exam_id)
    if e is None or e.deleted_at is not None:
        raise ValueError(f"exam {exam_id} not found")
    if e.publish_status == ExamPublishStatus.published:
        return e
    old = {"publish_status": e.publish_status.value}
    e.publish_status = ExamPublishStatus.published
    e.last_verified_at = datetime.now(UTC)
    write_audit_log(
        session,
        action=AuditAction.EXAM_PUBLISHED,
        entity_type="exam",
        entity_id=e.id,
        old_value=old,
        new_value={"publish_status": "published"},
        **_common_audit_kwargs(actor, request_id),
    )
    return e


def unpublish_exam(session: Session, *, actor: User, request_id: str | None, exam_id: int) -> Exam:
    e = session.get(Exam, exam_id)
    if e is None or e.deleted_at is not None:
        raise ValueError(f"exam {exam_id} not found")
    if e.publish_status != ExamPublishStatus.published:
        return e
    e.publish_status = ExamPublishStatus.draft
    write_audit_log(
        session,
        action=AuditAction.EXAM_UNPUBLISHED,
        entity_type="exam",
        entity_id=e.id,
        old_value={"publish_status": "published"},
        new_value={"publish_status": "draft"},
        **_common_audit_kwargs(actor, request_id),
    )
    return e


def soft_delete_exam(
    session: Session, *, actor: User, request_id: str | None, exam_id: int
) -> None:
    e = session.get(Exam, exam_id)
    if e is None or e.deleted_at is not None:
        return
    e.deleted_at = datetime.now(UTC)
    write_audit_log(
        session,
        action=AuditAction.EXAM_SOFT_DELETED,
        entity_type="exam",
        entity_id=exam_id,
        old_value={"name": e.name, "slug": e.slug},
        **_common_audit_kwargs(actor, request_id),
    )


# ---------------------------------------------------------------------------
# Topic
# ---------------------------------------------------------------------------


def create_topic(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    exam_id: int,
    name: str,
    slug: str,
    description: str | None = None,
    weight: Decimal | None = None,
) -> Topic:
    t = Topic(exam_id=exam_id, name=name, slug=slug, description=description, weight=weight)
    session.add(t)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if "uq_topics_exam_slug" in str(exc.orig).lower():
            raise DuplicateSlugError(f"topic slug {slug!r} already used under this exam") from exc
        raise
    write_audit_log(
        session,
        action=AuditAction.TOPIC_CREATED,
        entity_type="topic",
        entity_id=t.id,
        new_value={"exam_id": exam_id, "name": name, "slug": slug},
        **_common_audit_kwargs(actor, request_id),
    )
    return t


def update_topic(
    session: Session, *, actor: User, request_id: str | None, topic_id: int, **changes: Any
) -> Topic:
    t = session.get(Topic, topic_id)
    if t is None:
        raise ValueError(f"topic {topic_id} not found")
    old = {k: getattr(t, k) for k in changes}
    for k, v in changes.items():
        setattr(t, k, v)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if "uq_topics_exam_slug" in str(exc.orig).lower():
            raise DuplicateSlugError(
                f"topic slug {changes.get('slug')!r} already used under this exam"
            ) from exc
        raise
    write_audit_log(
        session,
        action=AuditAction.TOPIC_UPDATED,
        entity_type="topic",
        entity_id=t.id,
        old_value=_jsonable(old),
        new_value=_jsonable(changes),
        **_common_audit_kwargs(actor, request_id),
    )
    return t


def soft_delete_topic(
    session: Session, *, actor: User, request_id: str | None, topic_id: int
) -> None:
    t = session.get(Topic, topic_id)
    if t is None:
        return
    session.delete(t)
    write_audit_log(
        session,
        action=AuditAction.TOPIC_SOFT_DELETED,
        entity_type="topic",
        entity_id=topic_id,
        old_value={"name": t.name, "slug": t.slug},
        **_common_audit_kwargs(actor, request_id),
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _jsonable(values: dict[str, Any]) -> dict[str, Any]:
    """Coerce SA values into JSON-friendly primitives for audit_logs.{old,new}_value."""
    out: dict[str, Any] = {}
    for k, v in values.items():
        if v is None or isinstance(v, str | int | float | bool):
            out[k] = v
        elif isinstance(v, Decimal):
            out[k] = str(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif hasattr(v, "value"):
            out[k] = v.value  # Enum
        else:
            out[k] = str(v)
    return out
