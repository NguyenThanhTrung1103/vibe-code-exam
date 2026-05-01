"""Shared helpers for admin catalog routers — keep router files compact."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth.csrf import CSRF_FORM_FIELD, issue_csrf_token, verify_csrf
from app.paths import TEMPLATES_DIR

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def require_csrf(request: Request, csrf_token: str) -> None:
    if not verify_csrf(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid csrf")


def render_with_csrf(request: Request, template: str, context: dict[str, Any]) -> HTMLResponse:
    """Issue ONE csrf token, set ONE cookie, render the template with it."""
    placeholder = HTMLResponse(content="")
    csrf = issue_csrf_token(placeholder)
    rendered = templates.TemplateResponse(request, template, {**context, CSRF_FORM_FIELD: csrf})
    for k, v in placeholder.raw_headers:
        if k == b"set-cookie":
            rendered.raw_headers.append((k, v))
    return rendered


def flash_error(request: Request, message: str, status_code: int = 400) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/catalog/_error.html",
        {"message": message},
        status_code=status_code,
    )
