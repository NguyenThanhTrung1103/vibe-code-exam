"""Phase 18 — public guest-practice routes.

Endpoints:

* `GET  /practice`                       — public catalog of published exams.
* `GET  /practice/{exam_slug}/setup`     — Mock Exam setup page (pick #questions).
* `POST /practice/{exam_id}/start`       — issue (or reuse) a signed guest
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

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.auth.guest_token import (
    GUEST_COOKIE_MAX_AGE,
    GUEST_COOKIE_NAME,
    issue_guest_token,
    verify_guest_token,
)
from app.auth.permissions import OptionalUser
from app.config import get_settings
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.catalog import Course, Exam, Provider
from app.models.enums import AttemptMode, QuestionStatus
from app.models.questions import Question
from app.paths import TEMPLATES_DIR
from app.routers.public.catalog_query import published_exam_filter
from app.security.rate_limits import RL_ATTEMPT_START
from app.services import attempt_service

# Mock Exam default subset size — overridable per-request via the form's
# `question_count` field; capped server-side at the exam's published total.
_MOCK_DEFAULT_COUNT = 30
# Mock Exam setup minimum question count.
_MOCK_MIN_COUNT = 5
# Preset buttons for the setup page (kept here so the template stays dumb).
_MOCK_PRESETS = (10, 20, 30, 50)

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
# GET /practice/{exam_slug}/setup — Mock Exam configuration page
# ---------------------------------------------------------------------------


@router.get("/{exam_slug}/setup", response_class=HTMLResponse)
def setup_page(
    exam_slug: str,
    request: Request,
    session: SessionDep,
) -> HTMLResponse:
    """Render the Mock Exam setup page: question-count picker → POST /start.

    Looks up the exam by slug (slugs are unique per course; if a collision
    exists we pick the most-recently updated published one). 404 for
    draft / soft-deleted / unknown slugs.
    """
    row = session.execute(
        select(Exam, Course, Provider)
        .join(Course, Exam.course_id == Course.id)
        .join(Provider, Course.provider_id == Provider.id)
        .where(Exam.slug == exam_slug)
        .where(published_exam_filter())
        .order_by(Exam.updated_at.desc())
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exam not found")
    exam, course, provider = row

    total = (
        session.scalar(
            select(func.count(Question.id))
            .where(Question.exam_id == exam.id)
            .where(Question.deleted_at.is_(None))
            .where(Question.retired_at.is_(None))
            .where(Question.status == QuestionStatus.published)
        )
        or 0
    )
    total = int(total)
    presets = [n for n in _MOCK_PRESETS if n <= total] or ([total] if total else [])
    default_count = _MOCK_DEFAULT_COUNT if total >= _MOCK_DEFAULT_COUNT else total
    return templates.TemplateResponse(
        request,
        "practice/setup.html",
        {
            "exam": exam,
            "course": course,
            "provider": provider,
            "total_questions": total,
            "presets": presets,
            "default_count": default_count,
            "min_count": min(_MOCK_MIN_COUNT, total) if total else 0,
        },
    )


# ---------------------------------------------------------------------------
# POST /practice/{exam_id}/start — start (or resume) guest attempt
# ---------------------------------------------------------------------------


@router.post("/{exam_id}/start", dependencies=[Depends(RL_ATTEMPT_START)])
def start_guest_attempt(
    exam_id: int,
    request: Request,
    session: SessionDep,
    current_user: OptionalUser,
    mode: str = Form("practice"),
    question_count: int | None = Form(None),
) -> Response:
    """Start (or resume) an attempt against a published exam.

    Two flows depending on caller:
      * Authenticated user → `attempt_service.start_attempt(actor=user)` so
        the attempt is linked to the user account (visible in their history).
      * Guest → `attempt_service.start_guest_attempt(guest_token=...)` with
        signed-cookie identity.

    `mode` accepts `practice` (Learning Mode — answers + explanations
    revealed inline) or `exam` (Mock Exam Mode — answers hidden until
    submit). `question_count` is the optional cap for Mock Exam (default
    30, capped at exam total). Ignored for Learning Mode (uses all
    questions so the learner studies the full bank).

    Cookie lifecycle (guest path only):
      * Read existing `guest_token` cookie; verify signature.
      * Valid → reuse UUID (resumes in-progress attempt for same exam).
      * Missing / expired / tampered → mint a fresh UUID, set a fresh
        signed cookie on the redirect response.
    """
    if mode not in ("practice", "exam"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mode must be 'practice' or 'exam'",
        )
    parsed_mode = AttemptMode(mode)

    # Mock Exam — sanitize subset size; ignore for Learning so the learner
    # sees every published question.
    effective_count: int | None = None
    if parsed_mode == AttemptMode.exam:
        raw = question_count if (question_count and question_count > 0) else _MOCK_DEFAULT_COUNT
        effective_count = max(1, int(raw))

    request_id = request.headers.get(REQUEST_ID_HEADER)

    if current_user is not None:
        try:
            attempt = attempt_service.start_attempt(
                session,
                actor=current_user,
                request_id=request_id,
                exam_id=exam_id,
                mode=parsed_mode,
                question_count=effective_count,
            )
        except attempt_service.AttemptValidationError as exc:
            msg = str(exc)
            if "not available" in msg or "not found" in msg:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg) from exc
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg) from exc
        session.commit()
        return RedirectResponse(
            url=f"/attempts/{attempt.id}/page/1",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # Guest path
    incoming = request.cookies.get(GUEST_COOKIE_NAME)
    raw_uuid = verify_guest_token(incoming)
    cookie_to_set: str | None = None

    if raw_uuid is None:
        raw_uuid, signed = issue_guest_token()
        cookie_to_set = signed

    try:
        attempt = attempt_service.start_guest_attempt(
            session,
            request_id=request_id,
            exam_id=exam_id,
            guest_token=raw_uuid,
            mode=parsed_mode,
            question_count=effective_count,
        )
    except attempt_service.AttemptValidationError as exc:
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
