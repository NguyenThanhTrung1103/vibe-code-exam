"""Phase 13 — community dump parser (skeleton — pre-req task 3).

Parses HTML/Excel for community discussion signals:
  external_question_id, discussion_url, vote_distribution, discussion_count.

PARSER_SCHEMA_VERSION pinned to fixture capture date.
Bump version when ExamTopics HTML structure changes; add new fixtures dated to
the bump date in `tests/fixtures/examtopics/<VERSION>-*.html`.

Pre-req scope: ONLY the version constant and module docstring.
Phase 13 implementation will add parser functions in a follow-up commit.
"""

from __future__ import annotations

PARSER_SCHEMA_VERSION = "2026-04-30"
"""Pinned to fixture capture date (`tests/fixtures/examtopics/<VERSION>-*.html`).

Drift policy: when site HTML changes,
  1. Author NEW fixtures with new date prefix.
  2. Bump this constant.
  3. Update parser selectors (Phase 13 implementation).
  4. Run regression tests against BOTH old + new fixtures.
"""

# Phase 13 implementation will fill in parser functions below.
# Current state: skeleton with version constant only.
