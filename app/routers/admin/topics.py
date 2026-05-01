"""Admin CRUD for topics (per-exam, flat — no nesting in MVP)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.catalog import Course, Exam, Provider, Topic
from app.routers.admin._common import flash_error, render_with_csrf, require_csrf, templates
from app.schemas.catalog import TopicCreate, TopicUpdate
from app.services import catalog_service

router = APIRouter(prefix="/admin/topics", tags=["admin", "catalog"])


@router.get("", response_class=HTMLResponse)
def list_topics(request: Request, user: RequireAdmin, session: SessionDep) -> HTMLResponse:
    rows = session.execute(
        select(Topic, Exam, Course, Provider)
        .join(Exam, Topic.exam_id == Exam.id)
        .join(Course, Exam.course_id == Course.id)
        .join(Provider, Course.provider_id == Provider.id)
        .where(Exam.deleted_at.is_(None))
        .order_by(Provider.name, Course.name, Exam.name, Topic.name)
    ).all()
    exams = session.scalars(select(Exam).where(Exam.deleted_at.is_(None)).order_by(Exam.name)).all()
    return render_with_csrf(
        request,
        "admin/catalog/topics/list.html",
        {"rows": rows, "exams": exams, "current_user": user},
    )


@router.post("", response_class=HTMLResponse)
def create_topic(
    request: Request,
    user: RequireAdmin,
    session: SessionDep,
    exam_id: int = Form(...),
    name: str = Form(...),
    slug: str = Form(""),
    description: str = Form(""),
    weight: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = TopicCreate.model_validate(
            {
                "exam_id": exam_id,
                "name": name,
                "slug": slug or None,
                "description": description or None,
                "weight": _parse_decimal(weight),
            }
        )
    except (ValidationError, InvalidOperation, ValueError) as exc:
        return flash_error(request, _first_message(exc))
    assert payload.slug is not None  # set by _fill_slug validator
    try:
        topic = catalog_service.create_topic(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            exam_id=payload.exam_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            weight=payload.weight,
        )
    except catalog_service.DuplicateSlugError as exc:
        return flash_error(request, str(exc))
    session.commit()
    return _row_partial(request, session, topic)


@router.post("/{topic_id}/edit", response_class=HTMLResponse)
def update_topic(
    request: Request,
    topic_id: int,
    user: RequireAdmin,
    session: SessionDep,
    name: str = Form(...),
    slug: str = Form(...),
    description: str = Form(""),
    weight: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = TopicUpdate(
            name=name,
            slug=slug,
            description=description or None,
            weight=_parse_decimal(weight),
        )
    except (ValidationError, InvalidOperation, ValueError) as exc:
        return flash_error(request, _first_message(exc))
    try:
        topic = catalog_service.update_topic(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            topic_id=topic_id,
            **payload.model_dump(exclude_unset=True, exclude_none=True),
        )
    except catalog_service.DuplicateSlugError as exc:
        return flash_error(request, str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    return _row_partial(request, session, topic)


@router.post("/{topic_id}/delete", response_class=HTMLResponse)
def soft_delete_topic(
    request: Request,
    topic_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        catalog_service.soft_delete_topic(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            topic_id=topic_id,
        )
    except ValueError as exc:
        return flash_error(request, str(exc))
    session.commit()
    return HTMLResponse("")


def _parse_decimal(value: str) -> Decimal | None:
    if not value:
        return None
    return Decimal(value)


def _first_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return str(exc.errors()[0]["msg"])
    return str(exc)


def _row_partial(request: Request, session, topic: Topic) -> HTMLResponse:
    exam = session.get(Exam, topic.exam_id)
    course = session.get(Course, exam.course_id) if exam else None
    provider = session.get(Provider, course.provider_id) if course else None
    return templates.TemplateResponse(
        request,
        "admin/catalog/topics/_row.html",
        {"row": (topic, exam, course, provider)},
    )
