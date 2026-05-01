"""/search/exams — minimal Postgres ILIKE search.

Phase 04 scope: NO full-text, NO Redis cache, NO ranking — just ILIKE on
provider name + exam code/name and return up to 20 hits as an HTMX partial.
Anything fancier ships when a real perf complaint forces it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select

from app.auth.permissions import OptionalUser
from app.deps import SessionDep
from app.models.catalog import Course, Exam, Provider
from app.paths import TEMPLATES_DIR
from app.routers.public.catalog_query import published_exam_filter
from app.security.rate_limits import RL_PUBLIC_SEARCH

router = APIRouter(prefix="/search", tags=["public"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_MAX_RESULTS = 20


@router.get(
    "/exams",
    response_class=HTMLResponse,
    dependencies=[Depends(RL_PUBLIC_SEARCH)],
)
def search_exams(
    request: Request,
    current: OptionalUser,
    session: SessionDep,
    q: str = Query("", max_length=128),
) -> HTMLResponse:
    query = q.strip()
    rows: list[tuple[Exam, Course, Provider]] = []
    if query:
        like = f"%{query}%"
        rows = session.execute(
            select(Exam, Course, Provider)
            .join(Course, Exam.course_id == Course.id)
            .join(Provider, Course.provider_id == Provider.id)
            .where(published_exam_filter())
            .where(
                or_(
                    Provider.name.ilike(like),
                    Exam.code.ilike(like),
                    Exam.name.ilike(like),
                )
            )
            .order_by(Provider.name, Exam.name)
            .limit(_MAX_RESULTS)
        ).all()  # type: ignore[assignment]

    return templates.TemplateResponse(
        request,
        "public/_search_results.html",
        {"current_user": current, "q": query, "rows": rows},
    )
