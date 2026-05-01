"""/vendors and /vendors/{slug} — provider listings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.auth.permissions import OptionalUser
from app.deps import SessionDep
from app.models.catalog import Course, Exam, Provider
from app.paths import TEMPLATES_DIR
from app.routers.public.catalog_query import (
    published_exam_filter,
    select_provider_with_published_exams,
)

router = APIRouter(prefix="/vendors", tags=["public"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("", response_class=HTMLResponse)
def list_vendors(request: Request, current: OptionalUser, session: SessionDep) -> HTMLResponse:
    providers = list(
        session.scalars(select_provider_with_published_exams().order_by(Provider.name))
    )
    return templates.TemplateResponse(
        request,
        "public/vendor_list.html",
        {"current_user": current, "providers": providers},
    )


@router.get("/{provider_slug}", response_class=HTMLResponse)
def vendor_detail(
    request: Request,
    provider_slug: str,
    current: OptionalUser,
    session: SessionDep,
) -> HTMLResponse:
    provider = session.scalar(select(Provider).where(Provider.slug == provider_slug))
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vendor not found")

    # All published, non-deleted exams under this provider, grouped by course.
    rows = session.execute(
        select(Exam, Course)
        .join(Course, Exam.course_id == Course.id)
        .where(Course.provider_id == provider.id)
        .where(published_exam_filter())
        .order_by(Course.name, Exam.name)
    ).all()

    # If every exam under this provider is unpublished/soft-deleted, the
    # provider has no public surface to render — return 404 to avoid an
    # empty "ghost" page.
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no published exams for vendor"
        )

    courses_map: dict[int, dict] = {}
    for exam, course in rows:
        bucket = courses_map.setdefault(course.id, {"course": course, "exams": []})
        bucket["exams"].append(exam)

    return templates.TemplateResponse(
        request,
        "public/vendor_detail.html",
        {
            "current_user": current,
            "provider": provider,
            "courses": list(courses_map.values()),
        },
    )
