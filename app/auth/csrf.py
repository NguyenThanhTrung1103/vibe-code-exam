"""Stateless HMAC CSRF tokens.

Pattern: GET issues a fresh token via cookie + form-field. POST verifies
that the cookie token and the form field both verify with the same secret
and match each other. Verification is HMAC-based — no DB read.
"""

from __future__ import annotations

import secrets

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import Settings, get_settings

CSRF_COOKIE_NAME = "exam_csrf"
CSRF_FORM_FIELD = "csrf_token"
_CSRF_TTL_SECONDS = 60 * 60 * 4  # 4 hours per token; new token per GET


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="exam-csrf")


def issue_csrf_token(
    response: Response,
    settings: Settings | None = None,
) -> str:
    """Generate a fresh CSRF token, set it on the cookie, return it for the form."""
    settings = settings or get_settings()
    nonce = secrets.token_urlsafe(16)
    token = _serializer(settings).dumps(nonce)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=_CSRF_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=not settings.is_local,
        path="/",
    )
    return token


def verify_csrf(request: Request, form_token: str | None) -> bool:
    """True iff the form token + cookie token both verify and match."""
    settings = get_settings()
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_token or not form_token:
        return False
    if not secrets.compare_digest(cookie_token, form_token):
        return False
    serializer = _serializer(settings)
    try:
        serializer.loads(cookie_token, max_age=_CSRF_TTL_SECONDS)
    except BadSignature:
        return False
    return True
