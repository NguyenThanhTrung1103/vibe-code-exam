"""Phase 07 — practice / exam attempt routes.

Phase 18.6 — paginated practice UI: 5 questions per page (ExamTopics layout).

POST /attempts/start                          start a new attempt (or resume)
GET  /attempts/{id}/page/{page_num}           deliver a page of N questions
GET  /attempts/{id}/q/{order}                 legacy 302 → /page/{ceil(order/N)}
POST /attempts/{id}/q/{order}/answer          autosave selection (per question)
POST /attempts/{id}/q/{order}/flag            toggle flag (per question)
GET  /attempts/{id}/submit-confirm            confirm dialog (exam mode)
POST /attempts/{id}/submit                    finalise attempt (idempotent)
GET  /attempts/{id}/submitted                 placeholder result page
                                              (Phase 08 replaces with real result)
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.auth.csrf import CSRF_FORM_FIELD, issue_csrf_token, verify_csrf
from app.auth.permissions import AttemptOwnerDep, CurrentUser
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.catalog import Exam
from app.models.enums import AttemptMode
from app.paths import TEMPLATES_DIR
from app.schemas.attempt import AttemptStartForm
from app.security.rate_limits import RL_ATTEMPT_ANSWER, RL_ATTEMPT_START
from app.services import attempt_service

router = APIRouter(prefix="/attempts", tags=["practice"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Phase 18.6 — ExamTopics-style page size. 5 questions per practice page.
PAGE_SIZE = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_csrf(request: Request, token: str) -> None:
    if not verify_csrf(request, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid csrf")


def _render_with_csrf(request: Request, template: str, ctx: dict) -> HTMLResponse:
    placeholder = HTMLResponse(content="")
    csrf = issue_csrf_token(placeholder)
    rendered = templates.TemplateResponse(request, template, {**ctx, CSRF_FORM_FIELD: csrf})
    for k, v in placeholder.raw_headers:
        if k == b"set-cookie":
            rendered.raw_headers.append((k, v))
    return rendered


def _request_id(request: Request) -> str | None:
    return request.headers.get(REQUEST_ID_HEADER)


def _redirect_seeother(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


def _service_error_to_http(exc: attempt_service.AttemptError) -> HTTPException:
    if isinstance(exc, attempt_service.AttemptForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, attempt_service.AttemptNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, attempt_service.AttemptValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# ---------------------------------------------------------------------------
# Start / resume
# ---------------------------------------------------------------------------


@router.post("/start", dependencies=[Depends(RL_ATTEMPT_START)])
def start_attempt(
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    exam_id: int = Form(...),
    mode: str = Form("practice"),
    csrf_token: str = Form(""),
) -> Response:
    _require_csrf(request, csrf_token)
    try:
        payload = AttemptStartForm.model_validate({"exam_id": exam_id, "mode": mode})
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc.errors()[0]["msg"]),
        ) from exc
    try:
        attempt = attempt_service.start_attempt(
            session,
            actor=user,
            request_id=_request_id(request),
            exam_id=payload.exam_id,
            mode=AttemptMode(payload.mode),
        )
    except attempt_service.AttemptError as exc:
        raise _service_error_to_http(exc) from exc
    session.commit()
    return _redirect_seeother(f"/attempts/{attempt.id}/page/1")


# ---------------------------------------------------------------------------
# Question delivery — Phase 18.6 page-of-N (ExamTopics layout)
# ---------------------------------------------------------------------------


def _parse_reveal_positions(raw: str | None, page_start: int, page_end: int) -> set[int]:
    """Parse `?reveal=2,4,7` query value into a set of ints clamped to page range.

    Anything outside `[page_start, page_end]` is silently dropped so a stale
    URL from another page never leaks state into the current render.
    """
    if not raw:
        return set()
    out: set[int] = set()
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token.isdigit():
            continue
        n = int(token)
        if page_start <= n <= page_end:
            out.add(n)
    return out


@router.get("/{attempt_id}/page/{page_num}", response_class=HTMLResponse)
def practice_page(
    request: Request,
    attempt_id: int,
    page_num: int,
    owner: AttemptOwnerDep,
    session: SessionDep,
) -> Response:
    try:
        page = attempt_service.get_page_views(
            session,
            actor=owner.user,
            attempt_id=attempt_id,
            page_num=page_num,
            page_size=PAGE_SIZE,
        )
    except attempt_service.AttemptError as exc:
        raise _service_error_to_http(exc) from exc

    # Server-authoritative timer enforcement: if exam mode and time-up,
    # finalise the attempt and redirect to the submitted page.
    try:
        attempt_service.ensure_not_expired(
            session,
            actor=owner.user,
            request_id=_request_id(request),
            attempt=page.attempt,
        )
    except attempt_service.AttemptExpiredError:
        session.commit()
        return _redirect_seeother(f"/attempts/{attempt_id}/submitted")

    if page.attempt.finished_at is not None:
        return _redirect_seeother(f"/attempts/{attempt_id}/submitted")

    # Reveal: only practice mode honors it; exam mode never shows answers mid-attempt.
    raw_reveal = request.query_params.get("reveal") or ""
    reveal_set: set[int] = set()
    if page.attempt.mode == AttemptMode.practice:
        reveal_set = _parse_reveal_positions(raw_reveal, page.page_start, page.page_end)
    page.revealed_positions = reveal_set

    # Pre-compute toggle URLs server-side. Click on Q3 with current reveal={2,4}:
    #   if revealed → new = {2,4}            (remove 3, but it wasn't there anyway)
    #   if not revealed → new = {2,3,4}      (add 3)
    # Avoids contorted Jinja list math.
    cards: list[dict] = []
    for view in page.views:
        position = view.answer.order_index
        is_revealed = position in reveal_set
        new_set = reveal_set - {position} if is_revealed else reveal_set | {position}
        toggle_param = ",".join(str(p) for p in sorted(new_set))
        toggle_url = (
            f"?reveal={toggle_param}#q{position}" if toggle_param else f"#q{position}"
        )
        cards.append(
            {
                "view": view,
                "position": position,
                "revealed": is_revealed,
                "toggle_url": toggle_url,
            }
        )

    page_query = f"?reveal={raw_reveal}" if raw_reveal else ""
    prev_url = (
        f"/attempts/{attempt_id}/page/{page.page_num - 1}" if page.page_num > 1 else None
    )
    next_url = (
        f"/attempts/{attempt_id}/page/{page.page_num + 1}{page_query}"
        if page.page_num < page.total_pages
        else None
    )
    is_last_page = page.page_num == page.total_pages

    exam = session.get(Exam, page.attempt.exam_id)
    return _render_with_csrf(
        request,
        "practice/question.html",
        {
            "current_user": owner.user,
            "is_guest": owner.is_guest,
            "page": page,
            "cards": cards,
            "exam": exam,
            "is_exam_mode": page.attempt.mode == AttemptMode.exam,
            "prev_url": prev_url,
            "next_url": next_url,
            "is_last_page": is_last_page,
        },
    )


@router.get("/{attempt_id}/q/{order}")
def legacy_question_redirect(attempt_id: int, order: int) -> RedirectResponse:
    """Phase 18.6 — preserve old single-question URLs by redirecting to their page.

    Existing bookmarks, audit-log links, and admin previews keep working.
    Returns a 302 with anchor `#q{order}` so the browser scrolls to the card.
    """
    if order < 1:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invalid order")
    page_num = math.ceil(order / PAGE_SIZE)
    return RedirectResponse(
        url=f"/attempts/{attempt_id}/page/{page_num}#q{order}",
        status_code=status.HTTP_302_FOUND,
    )


# ---------------------------------------------------------------------------
# Autosave + flag
# ---------------------------------------------------------------------------


@router.post(
    "/{attempt_id}/q/{order}/answer",
    response_class=HTMLResponse,
    dependencies=[Depends(RL_ATTEMPT_ANSWER)],
)
async def save_answer(
    request: Request,
    attempt_id: int,
    order: int,
    owner: AttemptOwnerDep,
    session: SessionDep,
) -> Response:
    form = await request.form()
    _require_csrf(request, str(form.get("csrf_token", "")))
    raw_values = [str(v) for v in form.getlist("selected_options") if isinstance(v, str)]
    try:
        attempt_service.save_answer(
            session,
            actor=owner.user,
            request_id=_request_id(request),
            attempt_id=attempt_id,
            order=order,
            selected=raw_values or None,
        )
    except attempt_service.AttemptExpiredError:
        session.commit()
        return _redirect_seeother(f"/attempts/{attempt_id}/submitted")
    except attempt_service.AttemptError as exc:
        raise _service_error_to_http(exc) from exc
    session.commit()
    return HTMLResponse(content="", status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{attempt_id}/q/{order}/flag", response_class=HTMLResponse)
def toggle_flag(
    request: Request,
    attempt_id: int,
    order: int,
    owner: AttemptOwnerDep,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> Response:
    _require_csrf(request, csrf_token)
    try:
        answer = attempt_service.toggle_flag(
            session,
            actor=owner.user,
            request_id=_request_id(request),
            attempt_id=attempt_id,
            order=order,
        )
    except attempt_service.AttemptError as exc:
        raise _service_error_to_http(exc) from exc
    session.commit()
    return templates.TemplateResponse(
        request,
        "practice/_flag_button.html",
        {"answer": answer, "position": order},
    )


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


@router.get("/{attempt_id}/submit-confirm", response_class=HTMLResponse)
def submit_confirm(
    request: Request,
    attempt_id: int,
    owner: AttemptOwnerDep,
    session: SessionDep,
) -> HTMLResponse:
    return _render_with_csrf(
        request,
        "practice/submit_confirm.html",
        {"current_user": owner.user, "is_guest": owner.is_guest, "attempt": owner.attempt},
    )


@router.post("/{attempt_id}/submit", response_class=HTMLResponse)
def submit(
    request: Request,
    attempt_id: int,
    owner: AttemptOwnerDep,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> Response:
    _require_csrf(request, csrf_token)
    try:
        attempt_service.submit_attempt(
            session,
            actor=owner.user,
            request_id=_request_id(request),
            attempt_id=attempt_id,
        )
    except attempt_service.AttemptError as exc:
        raise _service_error_to_http(exc) from exc
    session.commit()
    return _redirect_seeother(f"/attempts/{attempt_id}/result")


@router.get("/{attempt_id}/submitted", response_class=HTMLResponse)
def submitted_stub(
    request: Request,
    attempt_id: int,
    owner: AttemptOwnerDep,
    session: SessionDep,
) -> HTMLResponse:
    return _render_with_csrf(
        request,
        "practice/submitted_stub.html",
        {"current_user": owner.user, "is_guest": owner.is_guest, "attempt": owner.attempt},
    )
