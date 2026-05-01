"""/exams/{provider_slug}/{exam_slug} — exam detail public page.

Visibility rule: only published, non-deleted exams are reachable. Anything
else returns 404 — never "draft" or "soft-deleted" leakage.

If the exam has no published questions yet (Phase 06 hasn't populated it),
the template MUST show a "Coming soon / No questions available yet" badge
and MUST NOT imply the learner can start a practice session.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.auth.csrf import CSRF_FORM_FIELD, issue_csrf_token
from app.auth.permissions import OptionalUser
from app.deps import SessionDep
from app.models.catalog import Course, Exam, Provider, Topic
from app.models.enums import QuestionStatus
from app.models.questions import Question
from app.paths import TEMPLATES_DIR
from app.routers.public.catalog_query import published_exam_filter

router = APIRouter(prefix="/exams", tags=["public"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/{provider_slug}/{exam_slug}", response_class=HTMLResponse)
def exam_detail(
    request: Request,
    provider_slug: str,
    exam_slug: str,
    current: OptionalUser,
    session: SessionDep,
) -> HTMLResponse:
    row = session.execute(
        select(Exam, Course, Provider)
        .join(Course, Exam.course_id == Course.id)
        .join(Provider, Course.provider_id == Provider.id)
        .where(Provider.slug == provider_slug)
        .where(Exam.slug == exam_slug)
        .where(published_exam_filter())
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exam not found")
    exam, course, provider = row

    topics = list(
        session.scalars(select(Topic).where(Topic.exam_id == exam.id).order_by(Topic.name))
    )

    # Count of *published* questions only — Phase 06 will populate this; for
    # now most exams have 0. The template uses this to decide whether to
    # surface "Start Practice" or the "Coming soon" notice.
    published_question_count = (
        session.scalar(
            select(func.count(Question.id))
            .where(Question.exam_id == exam.id)
            .where(Question.status == QuestionStatus.published)
            .where(Question.deleted_at.is_(None))
        )
        or 0
    )

    placeholder = HTMLResponse(content="")
    csrf = issue_csrf_token(placeholder)
    rendered = templates.TemplateResponse(
        request,
        "public/exam_detail.html",
        {
            "current_user": current,
            "exam": exam,
            "course": course,
            "provider": provider,
            "topics": topics,
            "published_question_count": int(published_question_count),
            CSRF_FORM_FIELD: csrf,
        },
    )
    for k, v in placeholder.raw_headers:
        if k == b"set-cookie":
            rendered.raw_headers.append((k, v))
    return rendered
