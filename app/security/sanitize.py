"""Markdown → safe HTML render helper.

Pipeline: `markdown_it` → `bleach.clean()` (strict allow-list) → `bleach.linkify()`.
External links are forced to `rel="noopener noreferrer nofollow"`.

`render_markdown(text)` returns HTML; templates use the `render_md` Jinja
filter which marks the result safe. Callers MUST treat the input as
admin- or user-supplied — never plumb raw HTML directly.
"""

from __future__ import annotations

from typing import Any

import bleach  # type: ignore[import-untyped]
from bleach.linkifier import LinkifyFilter  # type: ignore[import-untyped]
from markdown_it import MarkdownIt

ALLOWED_TAGS: list[str] = [
    "p",
    "strong",
    "em",
    "code",
    "pre",
    "ul",
    "ol",
    "li",
    "a",
    "h2",
    "h3",
    "h4",
    "blockquote",
    "br",
    "hr",
]
ALLOWED_ATTRS: dict[str, list[str]] = {
    "a": ["href", "title", "rel"],
    "code": ["class"],
}
ALLOWED_PROTOCOLS: list[str] = ["http", "https", "mailto"]


def _harden_links(attrs: dict[Any, str], new: bool = False) -> dict[Any, str]:  # noqa: ARG001
    """bleach.linkify callback — force opener/referrer/follow safety on <a>."""
    attrs[(None, "rel")] = "noopener noreferrer nofollow"
    attrs[(None, "target")] = "_blank"
    return attrs


_md = MarkdownIt("commonmark", {"breaks": True, "html": False, "linkify": True}).enable("table")


def render_markdown(text: str | None) -> str:
    """Render Markdown → strictly-sanitised HTML. Empty input → empty string."""
    if not text:
        return ""
    raw_html = _md.render(text)
    cleaned = bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    # linkify converts bare URLs to anchors and applies the link hardener.
    return bleach.linkify(cleaned, callbacks=[_harden_links], skip_tags=["pre", "code"])


__all__ = [
    "ALLOWED_ATTRS",
    "ALLOWED_PROTOCOLS",
    "ALLOWED_TAGS",
    "LinkifyFilter",
    "render_markdown",
]
