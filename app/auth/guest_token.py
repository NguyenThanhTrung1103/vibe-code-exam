"""Phase 18 — signed guest-token helpers.

Public exam-practice mode (no login). The plain-text payload is a UUID4
written into the `attempts.guest_token` column; the cookie carries the
signed form so the server can verify on every request without a DB hit.

Signature uses `itsdangerous.URLSafeTimedSerializer` keyed off the
project secret (`settings.secret_key`) plus a salt that scopes this
key to guest tokens specifically — sharing the same `secret_key` with
session cookies / CSRF is fine because the salt makes signatures
non-interchangeable.

Cookie layering (set by `app/routers/public_practice.py`):
  * `httponly=True`   — JS cannot read it
  * `samesite="lax"`  — top-level GET navigations attach it; cross-site
                        POSTs do not (CSRF mitigation for guest start)
  * `secure=True` in production envs only — local dev tolerates HTTP
  * `max_age=86400`   — 24 h sliding window; missing/expired cookies
                        get a fresh token transparently on next start.

Never expose the raw UUID in the URL — the cookie is the only carrier.
"""

from __future__ import annotations

import uuid

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings

GUEST_COOKIE_NAME = "guest_token"
GUEST_COOKIE_MAX_AGE = 86400  # 24 h
_SALT = "guest-token"


def _serializer() -> URLSafeTimedSerializer:
    """Build the serializer lazily so settings overrides at test time win."""
    return URLSafeTimedSerializer(get_settings().secret_key, salt=_SALT)


def issue_guest_token() -> tuple[str, str]:
    """Return `(raw_uuid, signed_cookie_value)` for a fresh guest token."""
    raw = str(uuid.uuid4())
    signed = _serializer().dumps(raw)
    return raw, signed


def verify_guest_token(signed: str | None, *, max_age: int = GUEST_COOKIE_MAX_AGE) -> str | None:
    """Return the raw UUID if `signed` is a valid, non-expired token; else None.

    `BadSignature` covers tampering AND `SignatureExpired` (subclass), so a
    single except catches both. We swallow them all and return None — the
    caller treats "no valid token" identically to "no cookie at all" by
    issuing a fresh one.
    """
    if not signed:
        return None
    try:
        raw = _serializer().loads(signed, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(raw, str):
        return None
    return raw


__all__ = [
    "GUEST_COOKIE_MAX_AGE",
    "GUEST_COOKIE_NAME",
    "issue_guest_token",
    "verify_guest_token",
]
