"""Guest-attempt cookie helpers.

A guest gets a single 32-byte URL-safe token (`secrets.token_urlsafe(32)`)
issued on the first practice-start request. The token lives in:

  * an HttpOnly cookie called ``GUEST_COOKIE`` on the client (30-day TTL),
  * the ``attempts.guest_token`` column on every attempt the guest creates.

Ownership of an attempt is granted when *either* the cookie token matches
``attempts.guest_token`` *or* the authed user matches ``attempts.user_id``.
There is no shared "guest user" — each browser gets its own opaque token,
isolating one guest's attempts from another's.
"""

from __future__ import annotations

import secrets

from fastapi import Request, Response

GUEST_COOKIE = "exam_guest_token"
GUEST_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
_TOKEN_BYTES = 32


def read_guest_token(request: Request) -> str | None:
    """Return the guest token from the request cookie, or None."""
    raw = request.cookies.get(GUEST_COOKIE)
    if not raw:
        return None
    raw = raw.strip()
    # Reject tokens that are obviously malformed or wrong length to avoid
    # treating noise as a valid identity. token_urlsafe(32) yields a string
    # in the 40-50 char range; cap at the column size.
    if not (16 <= len(raw) <= 64):
        return None
    return raw


def issue_guest_token(response: Response) -> str:
    """Mint a new guest token and set the cookie on `response`."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    response.set_cookie(
        key=GUEST_COOKIE,
        value=token,
        max_age=GUEST_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # dev/LAN — flip to True behind HTTPS-terminating proxy
        path="/",
    )
    return token


def ensure_guest_token(request: Request, response: Response) -> str:
    """Return the cookie's token if present and valid, else mint a new one."""
    existing = read_guest_token(request)
    if existing:
        return existing
    return issue_guest_token(response)
