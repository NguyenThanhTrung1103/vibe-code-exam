"""Signed-cookie sessions via itsdangerous.

Payload is small: `{"user_id": int, "iat": <epoch>, "sid": <random>}`.
The `sid` rotates on every login so sniffed cookies from before login are
invalid afterwards (session fixation defence).
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from fastapi import Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings, get_settings


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="exam-session")


def make_session_payload(user_id: int) -> dict[str, Any]:
    return {"user_id": user_id, "iat": int(time.time()), "sid": secrets.token_urlsafe(16)}


def issue_session_cookie(
    response: Response,
    *,
    user_id: int,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    payload = make_session_payload(user_id)
    token = _serializer(settings).dumps(payload)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=not settings.is_local,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=not settings.is_local,
    )


def read_session_user_id(request: Request, settings: Settings | None = None) -> int | None:
    """Return user_id if the cookie verifies + isn't expired, else None.

    Never raises; never reveals which failure mode it was.
    """
    settings = settings or get_settings()
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        return None
    try:
        payload = _serializer(settings).loads(raw, max_age=settings.session_ttl_days * 24 * 3600)
    except (BadSignature, SignatureExpired):
        return None
    user_id = payload.get("user_id") if isinstance(payload, dict) else None
    return int(user_id) if isinstance(user_id, int) else None
