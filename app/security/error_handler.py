"""Production-safe error handlers.

In `prod`/`staging`, unhandled exceptions render a generic 500 page —
no traceback, no exception class name. In dev/local/test, we let
FastAPI's default behaviour pass through so debugging stays useful.

Sentry is wired in `app.main._init_sentry`; this handler runs *after*
the SDK has captured the exception (the SDK hooks the ASGI lifecycle).
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import Settings, get_settings

log = structlog.get_logger("security.error")


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept


def _generic_500(request: Request) -> HTMLResponse | JSONResponse:
    if _wants_html(request):
        body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Server error</title></head>"
            "<body><h1>Something went wrong</h1>"
            "<p>The error has been logged. Please try again shortly.</p>"
            "</body></html>"
        )
        return HTMLResponse(body, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return JSONResponse(
        {"detail": "internal server error"},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def install_error_handlers(app: FastAPI, settings: Settings | None = None) -> None:
    """Install production-safe exception handlers on `app`."""
    s = settings or get_settings()

    if s.is_production or s.env == "staging":

        @app.exception_handler(Exception)
        async def _unhandled(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
            # HTTPException short-circuits to FastAPI's own handler.
            if isinstance(exc, HTTPException | RequestValidationError):
                raise exc
            log.exception(
                "unhandled_exception",
                path=request.url.path,
                method=request.method,
                error_type=type(exc).__name__,
            )
            return _generic_500(request)


__all__ = ["install_error_handlers"]
