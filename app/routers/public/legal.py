"""Phase 12 — public legal pages.

Renders Markdown straight from `docs/{disclaimer,terms-of-service,
privacy-policy,dmca-takedown}.md` through the Phase 09 sanitiser, so
legal updates never need a code change.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth.permissions import OptionalUser
from app.paths import TEMPLATES_DIR
from app.security.sanitize import render_markdown

router = APIRouter(prefix="/legal", tags=["public", "legal"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_DOCS = Path(__file__).resolve().parents[3] / "docs"

_PAGES: dict[str, tuple[str, str]] = {
    "disclaimer": ("disclaimer.md", "Disclaimer"),
    "terms": ("terms-of-service.md", "Terms of Service"),
    "privacy": ("privacy-policy.md", "Privacy Policy"),
    "dmca": ("dmca-takedown.md", "DMCA Takedown"),
}


@router.get("/{slug}", response_class=HTMLResponse)
def legal_page(slug: str, request: Request, current: OptionalUser) -> HTMLResponse:
    if slug not in _PAGES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    file_name, title = _PAGES[slug]
    path = _DOCS / file_name
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    body_html = render_markdown(text)
    return templates.TemplateResponse(
        request,
        "public/legal.html",
        {"current_user": current, "title": title, "body_html": body_html, "slug": slug},
    )
