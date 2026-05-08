"""Adapter interface + canonical row shape used across all parsers."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# Canonical row keys produced by every parser. Mirrors `excel_parser.CANONICAL_FIELDS`
# but adds source-locator fields the multi-format pipeline needs.
CANONICAL_FIELDS: tuple[str, ...] = (
    "question_text",
    "question_type",
    "difficulty",
    "topic",
    "tags",
    "option_a",
    "option_b",
    "option_c",
    "option_d",
    "option_e",
    "option_f",
    "option_g",
    "option_h",
    "combined_options",
    "correct_answer",
    "explanation",
    "reference",
    "external_question_id",
    "discussion_url",
    "discussion_count",
    "vote_a",
    "vote_b",
    "vote_c",
    "vote_d",
    "vote_e",
    "vote_f",
    "vote_g",
    "vote_h",
    # Source-locator (stored in questions.source_locator JSONB):
    "source_url",
    "source_format",
    "source_page",
    "raw_source_ref",
)

ParsedQuestion = dict[str, Any]


@runtime_checkable
class ParserAdapter(Protocol):
    """A pluggable file-format parser.

    `detect()` is cheap and signature-only — it should not parse the whole
    file. The detector picks the highest-priority adapter whose `detect()`
    returns True, then calls `parse()` on the same file path.
    """

    name: str
    priority: int

    def detect(self, *, filename: str, head_bytes: bytes) -> bool: ...

    def parse(
        self,
        *,
        file_path: Path,
        column_mapping: dict[str, str | None] | None = None,
    ) -> Iterator[ParsedQuestion]: ...
