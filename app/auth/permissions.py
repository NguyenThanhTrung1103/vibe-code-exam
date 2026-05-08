"""RBAC matrix + FastAPI dependencies.

`require_role(*roles)` raises 401 if the caller is anonymous and 403 if
the caller is logged in but lacks the role. Conflating them confuses both
users and crawlers — keep them distinct (RFC 7235 / 7231).

For browser navigation (Accept: text/html), an unauthenticated request
returns a 303 redirect to /auth/login?next=<path> instead of bare 401 —
the 401 JSON body is hostile UX for users typing URLs into a browser.
API/JSON callers continue to receive 401 unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.guest_token import GUEST_COOKIE_NAME, verify_guest_token
from app.auth.service import get_user
from app.auth.session import read_session_user_id
from app.deps import SessionDep
from app.models.attempts import Attempt
from app.models.enums import UserRole
from app.models.users import User


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "").lower()


def _login_redirect_for(request: Request) -> HTTPException:
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        detail="login required",
        headers={"Location": f"/auth/login?next={quote(path, safe='/?=&')}"},
    )


def get_current_user(
    request: Request,
    session: SessionDep,
) -> User | None:
    """Resolve the user from the signed cookie. None if missing/invalid/expired."""
    user_id = read_session_user_id(request)
    if user_id is None:
        return None
    return get_user(session, user_id)


def get_current_user_required(
    request: Request,
    session: SessionDep,
) -> User:
    user = get_current_user(request, session)
    if user is None:
        if _wants_html(request):
            raise _login_redirect_for(request)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user


def require_role(*allowed: UserRole) -> Callable[..., User]:
    """Build a FastAPI dependency that enforces role membership."""
    allowed_set = set(allowed)

    def _dep(
        request: Request,
        session: SessionDep,
    ) -> User:
        user = get_current_user(request, session)
        if user is None:
            if _wants_html(request):
                raise _login_redirect_for(request)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
                headers={"WWW-Authenticate": "Cookie"},
            )
        if user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="forbidden",
            )
        return user

    return _dep


def _resolve_session_for_user(request: Request, session: Session, user_id: int) -> User | None:
    """Internal helper used by tests; mirrors `get_current_user` but skips cookie parsing."""
    return get_user(session, user_id)


# Pre-built dependency aliases — import these from routers.
CurrentUser = Annotated[User, Depends(get_current_user_required)]
OptionalUser = Annotated[User | None, Depends(get_current_user)]
RequireAdmin = Annotated[User, Depends(require_role(UserRole.admin))]
RequireStudent = Annotated[User, Depends(require_role(UserRole.student))]


# ---------------------------------------------------------------------------
# Phase 18 — guest-aware attempt ownership
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AttemptOwner:
    """Resolved owner of an attempt: either an authenticated user OR a guest.

    Exactly one of `user` / `guest_token` is non-None. Routes use this to
    decide which actor to thread into the service layer (`actor=owner.user`
    when `owner.user` is set, else `actor=None` for guest paths).
    """

    attempt: Attempt
    user: User | None
    guest_token: str | None  # raw UUID (already verified)

    @property
    def is_guest(self) -> bool:
        return self.user is None


def get_attempt_owner(
    attempt_id: int,
    request: Request,
    session: SessionDep,
) -> AttemptOwner:
    """Resolve and authorise the owner of `attempt_id`.

    Checks (in order):
      1. Attempt exists and is not soft-deleted (404 otherwise).
      2. If the request carries a valid auth session AND the attempt's
         `user_id` matches that user → user-owner.
      3. Else if the request carries a valid signed `guest_token` cookie
         AND the attempt's `guest_token` matches → guest-owner.
      4. Anything else → 403.

    Returning a typed dataclass keeps callers honest: route handlers must
    decide explicitly whether to thread an authenticated `actor` or pass
    `actor=None` (guest path) into the service layer.
    """
    attempt = session.get(Attempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="attempt not found")

    # Auth-user path
    user_id = read_session_user_id(request)
    if user_id is not None:
        user = get_user(session, user_id)
        if user is not None and attempt.user_id == user.id:
            return AttemptOwner(attempt=attempt, user=user, guest_token=None)

    # Guest path — verify signed cookie matches the attempt's stored token.
    cookie = request.cookies.get(GUEST_COOKIE_NAME)
    raw = verify_guest_token(cookie)
    if raw is not None and attempt.guest_token is not None and attempt.guest_token == raw:
        return AttemptOwner(attempt=attempt, user=None, guest_token=raw)

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


AttemptOwnerDep = Annotated[AttemptOwner, Depends(get_attempt_owner)]
