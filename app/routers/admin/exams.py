"""Admin CRUD for exams + publish/unpublish."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.catalog import Course, Exam, Provider
from app.routers.admin._common import flash_error, render_with_csrf, require_csrf, templates
from app.schemas.catalog import ExamCreate, ExamUpdate
from app.services import catalog_service

router = APIRouter(prefix="/admin/exams", tags=["admin", "catalog"])


@router.get("", response_class=HTMLResponse)
def list_exams(request: Request, user: RequireAdmin, session: SessionDep) -> HTMLResponse:
    rows = session.execute(
        select(Exam, Course, Provider)
        .join(Course, Exam.course_id == Course.id)
        .join(Provider, Course.provider_id == Provider.id)
        .where(Exam.deleted_at.is_(None))
        .order_by(Exam.name)
    ).all()
    courses = session.scalars(select(Course).order_by(Course.name)).all()
    return render_with_csrf(
        request,
        "admin/catalog/exams/list.html",
        {"rows": rows, "courses": courses, "current_user": user},
    )


@router.post("", response_class=HTMLResponse)
def create_exam(
    request: Request,
    user: RequireAdmin,
    session: SessionDep,
    course_id: int = Form(...),
    name: str = Form(...),
    slug: str = Form(""),
    code: str = Form(""),
    description: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = ExamCreate.model_validate(
            {
                "course_id": course_id,
                "name": name,
                "slug": slug or None,
                "code": code or None,
                "description": description or None,
            }
        )
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    assert payload.slug is not None  # set by _check_dates_and_slug validator
    try:
        exam = catalog_service.create_exam(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            course_id=payload.course_id,
            name=payload.name,
            slug=payload.slug,
            code=payload.code,
            description=payload.description,
        )
    except catalog_service.DuplicateSlugError as exc:
        return flash_error(request, str(exc))
    session.commit()
    return _row_partial(request, session, exam)


@router.post("/{exam_id}/edit", response_class=HTMLResponse)
def update_exam(
    request: Request,
    exam_id: int,
    user: RequireAdmin,
    session: SessionDep,
    name: str = Form(...),
    slug: str = Form(...),
    code: str = Form(""),
    description: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = ExamUpdate(
            name=name, slug=slug, code=code or None, description=description or None
        )
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    try:
        exam = catalog_service.update_exam(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            exam_id=exam_id,
            **payload.model_dump(exclude_unset=True, exclude_none=True),
        )
    except catalog_service.DuplicateSlugError as exc:
        return flash_error(request, str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    return _row_partial(request, session, exam)


@router.post("/{exam_id}/publish", response_class=HTMLResponse)
def publish_exam(
    request: Request,
    exam_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        exam = catalog_service.publish_exam(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            exam_id=exam_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    return _row_partial(request, session, exam)


@router.post("/{exam_id}/unpublish", response_class=HTMLResponse)
def unpublish_exam(
    request: Request,
    exam_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        exam = catalog_service.unpublish_exam(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            exam_id=exam_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    return _row_partial(request, session, exam)


@router.post("/{exam_id}/delete", response_class=HTMLResponse)
def soft_delete_exam(
    request: Request,
    exam_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        catalog_service.soft_delete_exam(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            exam_id=exam_id,
        )
    except ValueError as exc:
        return flash_error(request, str(exc))
    session.commit()
    return HTMLResponse("")


def _row_partial(request: Request, session, exam: Exam) -> HTMLResponse:
    course = session.get(Course, exam.course_id)
    provider = session.get(Provider, course.provider_id) if course else None
    return templates.TemplateResponse(
        request,
        "admin/catalog/exams/_row.html",
        {"row": (exam, course, provider)},
    )
