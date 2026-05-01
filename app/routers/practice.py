"""Phase 07 — practice / exam attempt routes.

POST /attempts/start                          start a new attempt (or resume)
GET  /attempts/{id}/q/{order}                 deliver a question page
POST /attempts/{id}/q/{order}/answer          autosave selection
POST /attempts/{id}/q/{order}/flag            toggle flag
GET  /attempts/{id}/submit-confirm            confirm dialog (exam mode)
POST /attempts/{id}/submit                    finalise attempt (idempotent)
GET  /attempts/{id}/submitted                 placeholder result page
                                              (Phase 08 replaces with real result)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.csrf import CSRF_FORM_FIELD, issue_csrf_token, verify_csrf
from app.auth.permissions import CurrentUser
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.attempts import Attempt, AttemptAnswer
from app.models.enums import AttemptMode
from app.paths import TEMPLATES_DIR
from app.schemas.attempt import AttemptStartForm
from app.security.rate_limits import RL_ATTEMPT_ANSWER, RL_ATTEMPT_START
from app.services import attempt_service

router = APIRouter(prefix="/attempts", tags=["practice"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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
    return _redirect_seeother(f"/attempts/{attempt.id}/q/1")


# ---------------------------------------------------------------------------
# Question delivery
# ---------------------------------------------------------------------------


@router.get("/{attempt_id}/q/{order}", response_class=HTMLResponse)
def show_question(
    request: Request,
    attempt_id: int,
    order: int,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    try:
        view = attempt_service.get_question_view(
            session, actor=user, attempt_id=attempt_id, order=order
        )
    except attempt_service.AttemptError as exc:
        raise _service_error_to_http(exc) from exc

    # Server-authoritative timer enforcement: if exam mode and time-up,
    # finalise the attempt and redirect to the submitted page.
    try:
        attempt_service.ensure_not_expired(
            session,
            actor=user,
            request_id=_request_id(request),
            attempt=view.attempt,
        )
    except attempt_service.AttemptExpiredError:
        session.commit()
        return _redirect_seeother(f"/attempts/{attempt_id}/submitted")

    if view.attempt.finished_at is not None:
        return _redirect_seeother(f"/attempts/{attempt_id}/submitted")

    # Render — include the jump-to grid state and reveal flag (practice mode only).
    reveal = request.query_params.get("reveal") == "1" and view.attempt.mode == AttemptMode.practice
    grid = list(
        session.scalars(
            select(AttemptAnswer)
            .where(AttemptAnswer.attempt_id == view.attempt.id)
            .order_by(AttemptAnswer.order_index)
        )
    )
    return _render_with_csrf(
        request,
        "practice/question.html",
        {
            "current_user": user,
            "view": view,
            "grid": grid,
            "reveal": reveal,
            "is_exam_mode": view.attempt.mode == AttemptMode.exam,
        },
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
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    form = await request.form()
    _require_csrf(request, str(form.get("csrf_token", "")))
    raw_values = [str(v) for v in form.getlist("selected_options") if isinstance(v, str)]
    try:
        attempt_service.save_answer(
            session,
            actor=user,
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
    user: CurrentUser,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> Response:
    _require_csrf(request, csrf_token)
    try:
        answer = attempt_service.toggle_flag(
            session,
            actor=user,
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
        {"answer": answer},
    )


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


@router.get("/{attempt_id}/submit-confirm", response_class=HTMLResponse)
def submit_confirm(
    request: Request,
    attempt_id: int,
    user: CurrentUser,
    session: SessionDep,
) -> HTMLResponse:
    a = session.get(Attempt, attempt_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if a.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return _render_with_csrf(
        request,
        "practice/submit_confirm.html",
        {"current_user": user, "attempt": a},
    )


@router.post("/{attempt_id}/submit", response_class=HTMLResponse)
def submit(
    request: Request,
    attempt_id: int,
    user: CurrentUser,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> Response:
    _require_csrf(request, csrf_token)
    try:
        attempt_service.submit_attempt(
            session,
            actor=user,
            request_id=_request_id(request),
            attempt_id=attempt_id,
        )
    except attempt_service.AttemptError as exc:
        raise _service_error_to_http(exc) from exc
    session.commit()
    return _redirect_seeother(f"/attempts/{attempt_id}/submitted")


@router.get("/{attempt_id}/submitted", response_class=HTMLResponse)
def submitted_stub(
    request: Request,
    attempt_id: int,
    user: CurrentUser,
    session: SessionDep,
) -> HTMLResponse:
    a = session.get(Attempt, attempt_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if a.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return _render_with_csrf(
        request,
        "practice/submitted_stub.html",
        {"current_user": user, "attempt": a},
    )
