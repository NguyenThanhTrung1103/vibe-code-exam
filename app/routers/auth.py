"""HTTP routes for register / login / logout / me.

Phase 03 ships `/auth/register` open for internal-beta dev/test use. Public
self-registration is NOT production-ready — gate it behind invite/admin
control before the first public soft-launch (Phase 09 hardening or earlier).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.auth.csrf import CSRF_FORM_FIELD, issue_csrf_token, verify_csrf
from app.auth.permissions import CurrentUser, OptionalUser
from app.auth.rate_limit import check_login_rate_limit
from app.auth.service import authenticate, get_user_by_email, get_user_by_username, register_user
from app.auth.session import clear_session_cookie, issue_session_cookie
from app.deps import RedisDep, SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.enums import ActorType, UserRole
from app.paths import TEMPLATES_DIR
from app.security.rate_limits import RL_REGISTER

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

log = structlog.get_logger("auth")


def _client_ip(request: Request) -> str:
    # Phase 11 will add ProxyHeadersMiddleware; until then `client.host` is
    # the direct connection (loopback in dev). Trusting X-Forwarded-* on
    # untrusted ingress is a foot-gun.
    return request.client.host if request.client else "unknown"


# ---------- GET pages (issue CSRF token) ----------


def _issue_csrf_for_template(
    request: Request,
    template: str,
    extra_context: dict[str, object],
) -> HTMLResponse:
    """Issue ONE CSRF token, render the template with it, and set ONE cookie.

    Calling `issue_csrf_token` twice would mint two different tokens — the
    cookie ends up holding the second while the form holds the first, and
    every POST fails CSRF. Generate the token first, then attach it to a
    single response.
    """
    # Build a placeholder response so we can mint a token bound to its cookie.
    placeholder = HTMLResponse(content="")
    csrf_token = issue_csrf_token(placeholder)

    # Render the real template with the same token in the form.
    rendered = templates.TemplateResponse(
        request,
        template,
        {**extra_context, CSRF_FORM_FIELD: csrf_token},
    )
    # Carry the cookie set by `issue_csrf_token` onto the rendered response.
    for k, v in placeholder.raw_headers:
        if k == b"set-cookie":
            rendered.raw_headers.append((k, v))
    return rendered


@router.get("/login", response_class=HTMLResponse)
def get_login(request: Request, current: OptionalUser) -> HTMLResponse:
    return _issue_csrf_for_template(
        request, "auth/login.html", {"current_user": current, "error": None}
    )


@router.get("/register", response_class=HTMLResponse)
def get_register(request: Request, current: OptionalUser) -> HTMLResponse:
    return _issue_csrf_for_template(
        request, "auth/register.html", {"current_user": current, "error": None}
    )


# ---------- POST endpoints ----------


@router.post("/login")
def post_login(
    request: Request,
    response: Response,
    session: SessionDep,
    redis: RedisDep,
    identifier: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
) -> JSONResponse:
    if not verify_csrf(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid csrf")

    request_id = request.headers.get(REQUEST_ID_HEADER)
    ip = _client_ip(request)
    rl = check_login_rate_limit(redis, ip=ip, identifier=identifier)
    if not rl.allowed:
        log.warning("login_rate_limited", ip=ip, reason=rl.reason)
        return JSONResponse(
            {"detail": "too many attempts, try again later"},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers=(
                {"Retry-After": str(rl.retry_after_seconds)} if rl.retry_after_seconds else {}
            ),
        )

    user = authenticate(session, identifier=identifier, password=password)
    if user is None:
        # Audit failure with safe metadata only — never the password.
        write_audit_log(
            session,
            actor_type=ActorType.system,
            actor_id=None,
            action=AuditAction.LOGIN_FAILED,
            entity_type="auth",
            entity_id=None,
            new_value={
                "identifier": identifier.strip().lower(),
                "ip": ip,
                "reason": "invalid_credentials",
            },
            request_id=request_id,
        )
        session.commit()
        return JSONResponse(
            {"detail": "invalid credentials"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # Success — rotate the cookie (defends session fixation).
    payload = JSONResponse(
        {"status": "ok", "user_id": user.id, "username": user.username, "role": user.role.value}
    )
    issue_session_cookie(payload, user_id=user.id)
    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=user.id,
        action=AuditAction.LOGIN_SUCCEEDED,
        entity_type="user",
        entity_id=user.id,
        new_value={"ip": ip},
        request_id=request_id,
    )
    session.commit()
    return payload


@router.post("/register", dependencies=[Depends(RL_REGISTER)])
def post_register(
    request: Request,
    session: SessionDep,
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
) -> JSONResponse:
    if not verify_csrf(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid csrf")

    if len(password) < 12:
        return JSONResponse(
            {"detail": "password must be at least 12 characters"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Pre-check uniqueness for a friendlier UX, but the canonical guard is
    # the unique constraint at DB level (handled below).
    if (
        get_user_by_email(session, email) is not None
        or get_user_by_username(session, username) is not None
    ):
        return JSONResponse(
            {"detail": "registration not available with those details"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    request_id = request.headers.get(REQUEST_ID_HEADER)
    try:
        user = register_user(
            session,
            email=email,
            username=username,
            password=password,
            role=UserRole.student,
            request_id=request_id,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        return JSONResponse(
            {"detail": "registration not available with those details"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    response = JSONResponse(
        {"status": "ok", "user_id": user.id, "username": user.username},
        status_code=status.HTTP_201_CREATED,
    )
    issue_session_cookie(response, user_id=user.id)
    return response


@router.post("/logout")
def post_logout(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> JSONResponse:
    request_id = request.headers.get(REQUEST_ID_HEADER)
    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=user.id,
        action=AuditAction.LOGOUT,
        entity_type="user",
        entity_id=user.id,
        request_id=request_id,
    )
    session.commit()
    response = JSONResponse({"status": "ok"})
    clear_session_cookie(response)
    return response


@router.get("/me")
def get_me(user: CurrentUser) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role.value,
    }
