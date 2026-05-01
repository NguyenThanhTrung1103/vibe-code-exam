"""Phase 09 — bleach allow-list + Markdown render unit tests."""

from __future__ import annotations

import pytest

from app.security.sanitize import render_markdown


def test_empty_input_returns_empty() -> None:
    assert render_markdown(None) == ""
    assert render_markdown("") == ""


def test_basic_markdown_rendered() -> None:
    out = render_markdown("**bold** and *italic*")
    assert "<strong>bold</strong>" in out
    assert "<em>italic</em>" in out


def test_script_tag_stripped() -> None:
    """Markdown-it (html=False) escapes raw HTML; the live `<script>` tag never appears."""
    out = render_markdown("<script>alert(1)</script> hello").lower()
    assert "<script" not in out  # no live tag
    assert "&lt;script" in out or "hello" in out  # escaped or stripped


def test_iframe_stripped() -> None:
    out = render_markdown("<iframe src='https://evil'></iframe>safe").lower()
    assert "<iframe" not in out
    assert "safe" in out


def test_javascript_url_stripped() -> None:
    out = render_markdown("[click](javascript:alert(1))").lower()
    # The anchor must either be dropped, or the href must not carry javascript:.
    # Bleach drops disallowed-protocol hrefs. Even if a literal substring stays
    # in escaped text, no `<a href="javascript:..."` element is rendered.
    assert 'href="javascript:' not in out
    assert "href='javascript:" not in out


def test_external_link_hardened() -> None:
    out = render_markdown("[example](https://example.com)")
    assert 'rel="noopener noreferrer nofollow"' in out
    assert 'target="_blank"' in out


def test_disallowed_tag_stripped_keeps_text() -> None:
    out = render_markdown("<style>body{}</style>visible")
    assert "<style" not in out.lower()
    assert "visible" in out


@pytest.mark.parametrize(
    "payload",
    [
        '<img src="x" onerror="alert(1)">',
        '<svg onload="alert(1)">',
        '<a href="javascript:alert(1)">x</a>',
        '<body onload="alert(1)">',
    ],
)
def test_xss_payloads_have_no_live_handlers(payload: str) -> None:
    """Output may contain *escaped* text, but no live tag/attribute is allowed."""
    out = render_markdown(payload).lower()
    # No live <script>/<img>/<svg>/<body> tag survived.
    assert "<script" not in out
    # No live event-handler attribute (escaped text like `&lt;img onerror...` is ok).
    assert "<img " not in out or "onerror=" not in out.split("<img ", 1)[-1].split(">", 1)[0]
    assert "<svg" not in out
    assert "<body" not in out
    # No href that carries javascript:.
    assert 'href="javascript:' not in out
    assert "href='javascript:" not in out
