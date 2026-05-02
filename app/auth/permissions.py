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
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.service import get_user
from app.auth.session import read_session_user_id
from app.deps import SessionDep
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
