"""Public home page — hero, search input, vendor grid, popular exams."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select

from app.auth.permissions import OptionalUser
from app.deps import SessionDep
from app.models.catalog import Course, Exam, Provider
from app.paths import TEMPLATES_DIR
from app.routers.public.catalog_query import (
    published_exam_filter,
    select_provider_with_published_exams,
)
from app.security.rate_limits import RL_PUBLIC_LANDING

router = APIRouter(tags=["public"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get(
    "/",
    response_class=HTMLResponse,
    dependencies=[Depends(RL_PUBLIC_LANDING)],
)
def home(request: Request, current: OptionalUser, session: SessionDep) -> HTMLResponse:
    providers = list(
        session.scalars(select_provider_with_published_exams().order_by(Provider.name).limit(12))
    )

    # "Popular exams" — Phase 1 stub: alphabetical by name. attempts.count
    # weighting arrives in Phase 03/08; until then we'd ship false leaderboards.
    popular = list(
        session.execute(
            select(Exam, Course, Provider, func.count(Exam.id).over().label("_total"))
            .join(Course, Exam.course_id == Course.id)
            .join(Provider, Course.provider_id == Provider.id)
            .where(published_exam_filter())
            .order_by(desc(Exam.last_verified_at).nulls_last(), Exam.name)
            .limit(8)
        ).all()
    )

    return templates.TemplateResponse(
        request,
        "public/home.html",
        {
            "current_user": current,
            "providers": providers,
            "popular_exams": [(e, c, p) for (e, c, p, _t) in popular],
        },
    )
