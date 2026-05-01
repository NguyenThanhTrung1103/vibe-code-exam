"""Admin CRUD for courses."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.catalog import Course, Provider
from app.routers.admin._common import flash_error, render_with_csrf, require_csrf, templates
from app.schemas.catalog import CourseCreate, CourseUpdate
from app.services import catalog_service

router = APIRouter(prefix="/admin/courses", tags=["admin", "catalog"])


@router.get("", response_class=HTMLResponse)
def list_courses(request: Request, user: RequireAdmin, session: SessionDep) -> HTMLResponse:
    rows = session.execute(
        select(Course, Provider)
        .join(Provider, Course.provider_id == Provider.id)
        .order_by(Course.name)
    ).all()
    providers = session.scalars(select(Provider).order_by(Provider.name)).all()
    return render_with_csrf(
        request,
        "admin/catalog/courses/list.html",
        {"rows": rows, "providers": providers, "current_user": user},
    )


@router.post("", response_class=HTMLResponse)
def create_course(
    request: Request,
    user: RequireAdmin,
    session: SessionDep,
    provider_id: int = Form(...),
    name: str = Form(...),
    slug: str = Form(""),
    description: str = Form(""),
    level: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = CourseCreate.model_validate(
            {
                "provider_id": provider_id,
                "name": name,
                "slug": slug or None,
                "description": description or None,
                "level": level or None,
            }
        )
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    assert payload.slug is not None  # set by _fill_slug validator
    try:
        course = catalog_service.create_course(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            provider_id=payload.provider_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            level=payload.level,
        )
    except catalog_service.DuplicateSlugError as exc:
        return flash_error(request, str(exc))
    session.commit()
    provider = session.get(Provider, course.provider_id)
    return templates.TemplateResponse(
        request, "admin/catalog/courses/_row.html", {"row": (course, provider)}
    )


@router.post("/{course_id}/edit", response_class=HTMLResponse)
def update_course(
    request: Request,
    course_id: int,
    user: RequireAdmin,
    session: SessionDep,
    name: str = Form(...),
    slug: str = Form(...),
    description: str = Form(""),
    level: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = CourseUpdate.model_validate(
            {
                "name": name,
                "slug": slug,
                "description": description or None,
                "level": level or None,
            }
        )
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    try:
        course = catalog_service.update_course(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            course_id=course_id,
            **payload.model_dump(exclude_unset=True, exclude_none=True),
        )
    except catalog_service.DuplicateSlugError as exc:
        return flash_error(request, str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    provider = session.get(Provider, course.provider_id)
    return templates.TemplateResponse(
        request, "admin/catalog/courses/_row.html", {"row": (course, provider)}
    )


@router.post("/{course_id}/delete", response_class=HTMLResponse)
def soft_delete_course(
    request: Request,
    course_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        catalog_service.soft_delete_course(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            course_id=course_id,
        )
    except ValueError as exc:
        return flash_error(request, str(exc))
    session.commit()
    return HTMLResponse("")
