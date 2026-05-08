"""SecurityHeadersMiddleware — apply defense-in-depth response headers.

Adds CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy and a
minimal Permissions-Policy on every response. HSTS is gated on
`Settings.is_production` so dev/local don't accidentally pin themselves
to HTTPS.

CSP at MVP intentionally allows `'unsafe-inline'` for HTMX/Alpine inline
handlers — see `docs/security-baseline.md` for the Phase 2 nonce-CSP path.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings, get_settings

# Public pages render a Tailwind CDN + Google Fonts shell (see
# `templates/public/_layout.html`). Admin/practice/auth keep the
# self-only chrome and don't depend on these origins.
CSP_DIRECTIVES = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)

PERMISSIONS_POLICY = (
    "geolocation=(), microphone=(), camera=(), payment=(), usb=(), "
    "fullscreen=(self), interest-cohort=()"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set hardening headers on every response."""

    def __init__(self, app, settings: Settings | None = None) -> None:
        super().__init__(app)
        self._settings = settings or get_settings()

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        h = response.headers
        # Defense-in-depth headers. setdefault preserves any per-route override.
        h.setdefault("Content-Security-Policy", CSP_DIRECTIVES)
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        # HSTS only in prod — local dev runs HTTP.
        if self._settings.is_production:
            h.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response
