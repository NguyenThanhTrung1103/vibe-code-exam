"""Phase 13 — community dump parser.

Parses HTML blocks (e.g. an admin-pasted ExamTopics question page) for the
4 community-signal fields used by Phase 13:
  * external_question_id   — `[data-id]` attribute
  * vote_distribution      — `.voted-answers-tally` JSON block
  * discussion_url         — `a[href*="/discussions/"]`
  * discussion_count       — `.discussion-count[data-count]`

PARSER_SCHEMA_VERSION pins the selector contract to the date of the
fixtures in `tests/fixtures/examtopics/<VERSION>-*.html`. Bump this
constant when ExamTopics rewrites their HTML; add new dated fixtures
to the same date prefix; keep the old fixtures so regression tests can
flag drift.

Failed REQUIRED selector raises `ParseError` (red-team #4 — never silent
NULL). Missing OPTIONAL selector returns None gracefully (e.g. q4 fixture
has no discussion link by design).

This module performs ZERO network IO. Phase 14 fetcher will fetch the
HTML; Phase 13 only parses what's already in hand.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

PARSER_SCHEMA_VERSION = "2026-04-30"
"""Pinned to fixture capture date (`tests/fixtures/examtopics/<VERSION>-*.html`).

Drift policy: when site HTML changes,
  1. Author NEW fixtures with new date prefix.
  2. Bump this constant.
  3. Update parser selectors below.
  4. Run regression tests against BOTH old + new fixtures.
"""


# Selector contract — keep in lock-step with PARSER_SCHEMA_VERSION.
_SEL_DATA_ID = "[data-id]"
_SEL_VOTE_TALLY = ".voted-answers-tally"
_SEL_DISCUSSION_LINK = "a[href*='/discussions/']"
_SEL_DISCUSSION_COUNT = ".discussion-count[data-count]"

_INT_RE = re.compile(r"-?\d+")


class ParseError(ValueError):
    """Raised when a REQUIRED selector is missing or malformed.

    `selector` is the CSS selector that failed; `reason` is a stable string
    suitable for `import_items.error_message` (e.g. `parse_error: data-id`).
    """

    def __init__(self, selector: str, reason: str) -> None:
        super().__init__(f"parse_error: {reason}")
        self.selector = selector
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ParsedHtmlBlock:
    """Raw extraction from one community HTML block.

    Caller (`import_normalizer`) wraps these into `ParsedCommunityRow`
    Pydantic schema for validation + DB write.
    """

    external_question_id: str | None
    discussion_url: str | None
    discussion_count: int | None
    vote_distribution: dict[str, int] | None
    schema_version: str = PARSER_SCHEMA_VERSION


def parse_html_block(html: str) -> ParsedHtmlBlock | None:
    """Parse one community HTML block. Return `None` if the input is empty
    or has no `[data-id]` (i.e. it's not a community-signal block at all).

    REQUIRED selectors → ParseError on miss:
      * `[data-id]`            — external question id (red-team #4 contract).
      * `.voted-answers-tally` — JSON vote tally container.

    OPTIONAL selectors → graceful None on miss:
      * `a[href*="/discussions/"]`
      * `.discussion-count[data-count]`
    """
    if not html or not isinstance(html, str):
        return None
    if not html.strip():
        return None

    soup = BeautifulSoup(html, "lxml")

    data_id_el = soup.select_one(_SEL_DATA_ID)
    if data_id_el is None:
        # Caller passed something that wasn't a community block at all (e.g.
        # a regular Excel cell). Not an error — just "no community signal".
        return None
    raw_attr = data_id_el.get("data-id")
    if isinstance(raw_attr, list):  # bs4 returns list for multi-valued attrs
        raw_attr = raw_attr[0] if raw_attr else None
    if not isinstance(raw_attr, str) or not raw_attr.strip():
        raise ParseError(_SEL_DATA_ID, "data-id present but empty")
    external_question_id: str = raw_attr.strip()

    tally_el = soup.select_one(_SEL_VOTE_TALLY)
    if tally_el is None:
        raise ParseError(_SEL_VOTE_TALLY, "voted-answers-tally")
    tally_text = tally_el.get_text(strip=True)
    if not tally_text:
        raise ParseError(_SEL_VOTE_TALLY, "voted-answers-tally empty")
    try:
        tally_json = json.loads(tally_text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ParseError(_SEL_VOTE_TALLY, f"voted-answers-tally not JSON: {exc}") from exc

    vote_distribution = _extract_vote_distribution(tally_json)

    disc_el = soup.select_one(_SEL_DISCUSSION_LINK)
    discussion_url: str | None = None
    if disc_el is not None:
        href = disc_el.get("href")
        if isinstance(href, list):
            href = href[0] if href else None
        if isinstance(href, str) and href.strip():
            discussion_url = href.strip()

    discussion_count: int | None = None
    count_el = soup.select_one(_SEL_DISCUSSION_COUNT)
    if count_el is not None:
        raw_count = count_el.get("data-count")
        if isinstance(raw_count, list):
            raw_count = raw_count[0] if raw_count else None
        if isinstance(raw_count, str):
            m = _INT_RE.search(raw_count)
            if m:
                try:
                    discussion_count = int(m.group(0))
                except ValueError:
                    discussion_count = None

    return ParsedHtmlBlock(
        external_question_id=external_question_id,
        discussion_url=discussion_url,
        discussion_count=discussion_count,
        vote_distribution=vote_distribution,
    )


def _extract_vote_distribution(tally_json: object) -> dict[str, int] | None:
    """Convert a parsed `.voted-answers-tally` JSON value into a clean
    `{label: int}` dict. Drops malformed entries; preserves dynamic labels.

    Accepted shapes (loose — ExamTopics has shipped both at different times):
      {"voted_answers": [{"key": "A", "count": 21}, ...]}
      [{"key": "A", "count": 21}, ...]
      {"A": 21, "D": 6}
    """
    if isinstance(tally_json, dict):
        nested = tally_json.get("voted_answers")
        if isinstance(nested, list):
            return _from_list(nested)
        return _from_mapping(tally_json)
    if isinstance(tally_json, list):
        return _from_list(tally_json)
    return None


def _from_list(items: list[object]) -> dict[str, int] | None:
    out: dict[str, int] = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        label = entry.get("key") or entry.get("answer") or entry.get("label")
        count = entry.get("count") if "count" in entry else entry.get("votes")
        if not isinstance(label, str):
            continue
        try:
            count_int = int(count) if count is not None else None  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if count_int is None or count_int < 0:
            continue
        out[label.strip()] = count_int
    return out or None


def _from_mapping(mapping: dict[str, object]) -> dict[str, int] | None:
    out: dict[str, int] = {}
    for label, count in mapping.items():
        if not isinstance(label, str):
            continue
        try:
            count_int = int(count) if count is not None else None  # type: ignore[arg-type, call-overload]
        except (TypeError, ValueError):
            continue
        if count_int is None or count_int < 0:
            continue
        out[label.strip()] = count_int
    return out or None


__all__ = [
    "PARSER_SCHEMA_VERSION",
    "ParseError",
    "ParsedHtmlBlock",
    "parse_html_block",
]
