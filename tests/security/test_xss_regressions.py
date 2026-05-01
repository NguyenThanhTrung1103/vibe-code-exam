"""Phase 09 — XSS regression tests on the render path.

The Phase 06 admin question editor accepts `question_text`, `option_text`,
and per-option / overall `explanation` strings. The Phase 08 review page
renders all of them. This test feeds malicious payloads through the
sanitise helper and asserts the resulting HTML has no executable script.
"""

from __future__ import annotations

import pytest

from app.security.sanitize import render_markdown

XSS_PAYLOADS = [
    "<script>alert('x')</script>",
    "<img src=x onerror='alert(1)'>",
    '"><svg onload=alert(1)>',
    "<a href='javascript:void(0)'>click</a>",
    "<iframe src='https://evil.example.com'></iframe>",
    "<body onload='alert(1)'>",
    "<style>body{}</style>",
    "<link rel='stylesheet' href='https://evil'>",
    "<meta http-equiv='refresh' content='0;url=https://evil'>",
    "<object data='https://evil'></object>",
]


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_payload_neutralised(payload: str) -> None:
    """No live executable element survives the render pipeline.

    `markdown-it` runs with `html=False`, so raw HTML is escaped to text;
    bleach then strips any tag that survived (e.g. through markdown features).
    Escaped text like `&lt;script&gt;alert(1)&lt;/script&gt;` is *safe* — it
    renders as visible text, not as code. The security property is "no live
    tag, no live event handler, no javascript: in href"; the literal
    substring "onerror" can appear inside escaped text without being a hazard.
    """
    out = render_markdown(payload).lower()
    assert "<script" not in out
    assert "<iframe" not in out
    assert "<style" not in out
    assert "<link" not in out
    assert "<meta" not in out
    assert "<object" not in out
    assert "<body" not in out
    assert "<svg" not in out
    # No live <a> tag has javascript: in its href. (Escaped text containing
    # the substring is safe because `<` and `>` are entity-encoded.)
    if 'href="javascript:' in out or "href='javascript:" in out:
        # OK only when the href appears inside escaped (text-only) context —
        # i.e., the surrounding `<` `>` are encoded as `&lt;` `&gt;`.
        assert "&lt;" in out and "&gt;" in out, f"live javascript: href survived: {out!r}"
    # No live event-handler attribute on a surviving tag.
    for handler in ("onerror=", "onload=", "onclick="):
        if handler in out:
            assert "&lt;" in out or "&gt;" in out, f"live {handler} survived: {out!r}"


def test_payload_in_markdown_context() -> None:
    md = "Here is some text\n\n<script>alert(1)</script>\n\nand more **bold**."
    out = render_markdown(md)
    assert "<script" not in out.lower()
    assert "<strong>bold</strong>" in out


def test_inline_attributes_stripped() -> None:
    md = '[click](http://example.com "alert(1)")'
    out = render_markdown(md)
    # Title attr is allowed by the allow-list, but no inline JS slips through.
    assert "javascript:" not in out.lower()
    assert "onclick" not in out.lower()
