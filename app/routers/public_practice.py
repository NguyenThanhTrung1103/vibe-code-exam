"""Phase 18 — public guest-practice routes.

Two endpoints:

* `GET  /practice`                   — public catalog of published exams.
* `POST /practice/{exam_id}/start`   — issue (or reuse) a signed guest
                                       cookie + start an attempt; redirect
                                       to `/attempts/{id}/page/1`.

No authentication required. Draft exams must never appear in the catalog
or accept starts. CSRF is intentionally NOT enforced on `/start` because
the request carries no authenticated session — the `SameSite=Lax` cookie
plus the POST-only verb is the mitigation.

Audit logs for guest actions write `ActorType.system` with `actor_id=None`
(see `attempt_service._audit_actor`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.auth.guest_token import (
    GUEST_COOKIE_MAX_AGE,
    GUEST_COOKIE_NAME,
    issue_guest_token,
    verify_guest_token,
)
from app.config import get_settings
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.catalog import Course, Exam, Provider
from app.models.enums import QuestionStatus
from app.models.questions import Question
from app.paths import TEMPLATES_DIR
from app.routers.public.catalog_query import published_exam_filter
from app.security.rate_limits import RL_ATTEMPT_START
from app.services import attempt_service

router = APIRouter(prefix="/practice", tags=["public", "practice"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# GET /practice — catalog
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def catalog(request: Request, session: SessionDep) -> HTMLResponse:
    """Public list of published exams with per-exam question counts.

    The question_count is computed via a single SQL aggregate (one query
    per page-load, not per row) — fine for the typical N (< a few dozen).
    """
    rows = session.execute(
        select(Exam, Course, Provider)
        .join(Course, Exam.course_id == Course.id)
        .join(Provider, Course.provider_id == Provider.id)
        .where(published_exam_filter())
        .order_by(Exam.updated_at.desc())
    ).all()

    if not rows:
        return templates.TemplateResponse(
            request,
            "practice/catalog.html",
            {"exams": []},
        )

    exam_ids = [e.id for e, _, _ in rows]
    counts_rows = session.execute(
        select(Question.exam_id, func.count(Question.id))
        .where(Question.exam_id.in_(exam_ids))
        .where(Question.deleted_at.is_(None))
        .where(Question.retired_at.is_(None))
        .where(Question.status == QuestionStatus.published)
        .group_by(Question.exam_id)
    ).all()
    counts: dict[int, int] = {int(eid): int(c) for eid, c in counts_rows}

    exams_view = [
        {
            "id": exam.id,
            "title": exam.name,
            "slug": exam.slug,
            "provider": provider.name,
            "course": course.name,
            "provider_slug": provider.slug,
            "question_count": counts.get(exam.id, 0),
        }
        for exam, course, provider in rows
    ]

    return templates.TemplateResponse(
        request,
        "practice/catalog.html",
        {"exams": exams_view},
    )


# ---------------------------------------------------------------------------
# POST /practice/{exam_id}/start — start (or resume) guest attempt
# ---------------------------------------------------------------------------


@router.post("/{exam_id}/start", dependencies=[Depends(RL_ATTEMPT_START)])
def start_guest_attempt(
    exam_id: int,
    request: Request,
    session: SessionDep,
) -> Response:
    """Start (or resume) a guest practice attempt against a published exam.

    Cookie lifecycle:
      * Read existing `guest_token` cookie; verify signature.
      * If valid → reuse the embedded UUID (resumes any in-progress attempt
        the guest already has on this exam).
      * If missing / expired / tampered → mint a fresh UUID, set a fresh
        signed cookie on the redirect response. Existing attempts under
        the OLD UUID are intentionally orphaned (they remain accessible
        only until the cookie's max_age elapsed, which is exactly when
        the new UUID is issued — by design).
    """
    incoming = request.cookies.get(GUEST_COOKIE_NAME)
    raw_uuid = verify_guest_token(incoming)
    cookie_to_set: str | None = None

    if raw_uuid is None:
        raw_uuid, signed = issue_guest_token()
        cookie_to_set = signed

    try:
        attempt = attempt_service.start_guest_attempt(
            session,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            exam_id=exam_id,
            guest_token=raw_uuid,
        )
    except attempt_service.AttemptValidationError as exc:
        # Map to 403 when exam is not publishable; 404 / 400 otherwise.
        msg = str(exc)
        if "not available" in msg or "not found" in msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg) from exc
    session.commit()

    redirect = RedirectResponse(
        url=f"/attempts/{attempt.id}/page/1",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    if cookie_to_set is not None:
        settings = get_settings()
        redirect.set_cookie(
            key=GUEST_COOKIE_NAME,
            value=cookie_to_set,
            max_age=GUEST_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.is_production,
            path="/",
        )
    return redirect


__all__ = ["router"]
