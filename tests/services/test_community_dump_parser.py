"""Phase 13 — `community_dump_parser` unit tests.

Covers:
  * `PARSER_SCHEMA_VERSION` is the expected fixture date prefix.
  * 5 fixtures parse to expected `ParsedHtmlBlock` shape (q1..q5).
  * Empty / non-html / no `[data-id]` → `None` (graceful).
  * Missing required `.voted-answers-tally` → `ParseError`.
  * Empty / blank `data-id` → `ParseError`.
  * Malformed JSON tally → `ParseError`.
  * Dynamic vote labels survive (red-team #10 — 6-option case Q5).
  * Multi-correct key (e.g. "AC") preserved verbatim from upstream.

NO network IO, NO DB, NO mocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.community_dump_parser import (
    PARSER_SCHEMA_VERSION,
    ParsedHtmlBlock,
    ParseError,
    parse_html_block,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "examtopics"


def _read(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_parser_schema_version_locked_to_fixture_date() -> None:
    assert PARSER_SCHEMA_VERSION == "2026-04-30"
    # And matches the fixture date-prefix on disk.
    files = sorted(FIXTURE_DIR.glob(f"{PARSER_SCHEMA_VERSION}-*.html"))
    assert len(files) == 5, "expected 5 dated fixtures for the pinned version"


def test_parse_html_block_returns_none_for_empty_input() -> None:
    assert parse_html_block("") is None
    assert parse_html_block("   \n  ") is None


def test_parse_html_block_returns_none_for_non_string() -> None:
    assert parse_html_block(None) is None  # type: ignore[arg-type]


def test_parse_html_block_returns_none_when_no_data_id() -> None:
    # A regular Excel-cell snippet without [data-id] is "not a community
    # block at all" — should return None, not raise.
    html = "<p>just some text without any data-id attribute</p>"
    assert parse_html_block(html) is None


def test_q1_happy_path_4_options() -> None:
    block = parse_html_block(_read("2026-04-30-fortinet-q1.html"))
    assert isinstance(block, ParsedHtmlBlock)
    assert block.external_question_id == "EXT-Q-001"
    assert block.discussion_url == "/discussions/fortinet/view/sample-q-001"
    assert block.discussion_count == 12
    assert block.vote_distribution == {"A": 21, "D": 6}
    assert block.schema_version == PARSER_SCHEMA_VERSION


def test_q2_disagree_5_options_keeps_dynamic_labels() -> None:
    block = parse_html_block(_read("2026-04-30-fortinet-q2.html"))
    assert block is not None
    assert block.external_question_id == "EXT-Q-002"
    assert block.discussion_count == 24
    assert block.vote_distribution == {"A": 8, "D": 10, "B": 2}


def test_q3_multi_correct_label_ac_preserved() -> None:
    """Multi-correct answers ship with composite labels like 'AC'.

    Parser must NOT split or normalize them — VoteDistribution will reject
    > 4 chars, so a future > 4-char composite would surface there, not here.
    """
    block = parse_html_block(_read("2026-04-30-fortinet-q3-multivote.html"))
    assert block is not None
    assert block.external_question_id == "EXT-Q-003"
    assert block.vote_distribution == {"AC": 10, "A": 4, "C": 3, "B": 2}


def test_q4_graceful_null_on_missing_discussion_link() -> None:
    """Q4 deliberately omits `<a href="/discussions/...">` — must not raise."""
    block = parse_html_block(_read("2026-04-30-fortinet-q4-no-discussion.html"))
    assert block is not None
    assert block.external_question_id == "EXT-Q-004"
    assert block.discussion_url is None
    assert block.discussion_count is None  # also no .discussion-count element
    assert block.vote_distribution == {"B": 3}


def test_q5_six_options_dynamic_labels_red_team_10() -> None:
    """Red-team #10: vote labels NOT hardcoded A–E. Cisco/Fortinet ship 6-option questions."""
    block = parse_html_block(_read("2026-04-30-fortinet-q5-6options.html"))
    assert block is not None
    assert block.external_question_id == "EXT-Q-005"
    assert "F" in (block.vote_distribution or {})
    assert block.vote_distribution == {"F": 12, "A": 5, "B": 3}


def test_missing_voted_answers_tally_raises_parse_error() -> None:
    html = """
    <div data-id="EXT-X" class="question-body">
        <p>no tally element here</p>
    </div>
    """
    with pytest.raises(ParseError) as excinfo:
        parse_html_block(html)
    assert excinfo.value.selector == ".voted-answers-tally"
    # Stable error message for `import_items.error_message`.
    assert "voted-answers-tally" in str(excinfo.value)


def test_empty_voted_answers_tally_raises_parse_error() -> None:
    html = """
    <div data-id="EXT-X" class="question-body">
        <div class="voted-answers-tally"></div>
    </div>
    """
    with pytest.raises(ParseError) as excinfo:
        parse_html_block(html)
    assert excinfo.value.selector == ".voted-answers-tally"


def test_malformed_json_in_tally_raises_parse_error() -> None:
    html = """
    <div data-id="EXT-X" class="question-body">
        <div class="voted-answers-tally">not-valid-json-{{{</div>
    </div>
    """
    with pytest.raises(ParseError) as excinfo:
        parse_html_block(html)
    assert excinfo.value.selector == ".voted-answers-tally"
    assert "not JSON" in excinfo.value.reason


def test_blank_data_id_raises_parse_error() -> None:
    html = """
    <div data-id="   " class="question-body">
        <div class="voted-answers-tally">{"A":1}</div>
    </div>
    """
    with pytest.raises(ParseError) as excinfo:
        parse_html_block(html)
    assert excinfo.value.selector == "[data-id]"


def test_mapping_shape_tally_accepted() -> None:
    """Parser tolerates the alternate `{label:count}` mapping shape too."""
    html = """
    <div data-id="EXT-MAP">
        <div class="voted-answers-tally">{"A": 9, "B": 1}</div>
    </div>
    """
    block = parse_html_block(html)
    assert block is not None
    assert block.vote_distribution == {"A": 9, "B": 1}


def test_list_shape_without_voted_answers_wrapper_accepted() -> None:
    """Parser tolerates a bare list shape (older site rev)."""
    html = """
    <div data-id="EXT-LIST">
        <div class="voted-answers-tally">[{"key":"A","count":4},{"key":"B","count":1}]</div>
    </div>
    """
    block = parse_html_block(html)
    assert block is not None
    assert block.vote_distribution == {"A": 4, "B": 1}


def test_negative_counts_are_dropped_not_raised() -> None:
    """Defensive: negative counts skipped so downstream Pydantic still gets clean data."""
    html = """
    <div data-id="EXT-NEG">
        <div class="voted-answers-tally">[{"key":"A","count":4},{"key":"B","count":-1}]</div>
    </div>
    """
    block = parse_html_block(html)
    assert block is not None
    assert block.vote_distribution == {"A": 4}


def test_data_count_attribute_is_extracted_from_first_int() -> None:
    """`data-count="15 comments"` shape — leading int wins."""
    html = """
    <div data-id="EXT-CNT">
        <div class="voted-answers-tally">{"A":1}</div>
        <span class="discussion-count" data-count="15 comments">15 comments</span>
    </div>
    """
    block = parse_html_block(html)
    assert block is not None
    assert block.discussion_count == 15
