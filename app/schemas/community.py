"""Phase 13 — Pydantic schemas for community-signal data.

`VoteDistribution` accepts dynamic option labels (no hardcode A–E) per
red-team #10. Cisco/Fortinet 6-option questions and True/False questions
both fit. The label regex is intentionally narrow to prevent log/JSON
injection: only ASCII alphanumeric, max 4 chars (covers 'A'..'Z' single,
'AB' multi-correct shorthand, '0'..'10' numeric labels).

`ParsedCommunityRow` is what the parser produces and the import pipeline
consumes — small, immutable, JSONB-safe.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_VOTE_LABEL_RE = re.compile(r"^[A-Za-z0-9]{1,4}$")
_EXTERNAL_QID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,255}$")

# Hard caps to deny memory-exhaustion / log-spam payloads.
_MAX_LABELS_PER_VOTE = 32
_MAX_VOTE_VALUE = 100_000
_MAX_DISCUSSION_COUNT = 1_000_000


class VoteDistribution(BaseModel):
    """A label → count mapping with safe value range and dynamic labels.

    Examples:
        {"A": 21, "D": 6}
        {"A": 5, "D": 3, "F": 12}      # 6-option (red-team #10)
        {"True": 4, "False": 1}        # T/F as 4-char labels

    Empty dict is rejected — use `None` to mean "no vote data".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    counts: dict[str, int] = Field(..., min_length=1)

    @field_validator("counts")
    @classmethod
    def _check_labels_and_values(cls, raw: dict[str, int]) -> dict[str, int]:
        if len(raw) > _MAX_LABELS_PER_VOTE:
            raise ValueError(f"too_many_labels (>{_MAX_LABELS_PER_VOTE})")
        cleaned: dict[str, int] = {}
        for label, count in raw.items():
            if not isinstance(label, str) or not _VOTE_LABEL_RE.fullmatch(label):
                raise ValueError(f"bad_label: {label!r}")
            if not isinstance(count, int) or isinstance(count, bool):
                raise ValueError(f"bad_count_type: {label}={type(count).__name__}")
            if count < 0:
                raise ValueError(f"negative_count: {label}={count}")
            if count > _MAX_VOTE_VALUE:
                raise ValueError(f"count_too_large: {label}={count}")
            # Normalize label to upper-case so "a" and "A" can't both appear.
            key = label.upper()
            if key in cleaned:
                raise ValueError(f"duplicate_label: {label!r}")
            cleaned[key] = count
        return cleaned

    @property
    def total_votes(self) -> int:
        return sum(self.counts.values())


class ParsedCommunityRow(BaseModel):
    """Output of `community_dump_parser.parse_html_block` and the per-row
    contribution to `import_items.normalized_data['community']`.

    All fields optional individually; the row is meaningful when at least
    one of `discussion_url` or `external_question_id` is set.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    external_question_id: str | None = None
    discussion_url: str | None = None
    discussion_count: int | None = None
    vote_distribution: dict[str, int] | None = None

    @field_validator("external_question_id")
    @classmethod
    def _check_external_id(cls, raw: str | None) -> str | None:
        if raw is None:
            return None
        s = raw.strip()
        if not s:
            return None
        if not _EXTERNAL_QID_RE.fullmatch(s):
            raise ValueError("external_question_id must be [A-Za-z0-9_-]{1,255}")
        return s

    @field_validator("discussion_count")
    @classmethod
    def _check_discussion_count(cls, raw: int | None) -> int | None:
        if raw is None:
            return None
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise ValueError("discussion_count must be int")
        if raw < 0 or raw > _MAX_DISCUSSION_COUNT:
            raise ValueError(f"discussion_count out of range [0, {_MAX_DISCUSSION_COUNT}]")
        return raw

    @field_validator("vote_distribution")
    @classmethod
    def _check_vote(cls, raw: dict[str, int] | None) -> dict[str, int] | None:
        if raw is None:
            return None
        return VoteDistribution(counts=raw).counts

    @model_validator(mode="after")
    def _at_least_one_signal(self) -> ParsedCommunityRow:
        if not any(
            v is not None
            for v in (
                self.external_question_id,
                self.discussion_url,
                self.discussion_count,
                self.vote_distribution,
            )
        ):
            raise ValueError("at_least_one_community_field_required")
        return self

    def to_jsonable(self) -> dict[str, Any]:
        """JSONB-safe form for `import_items.normalized_data`."""
        return {
            "external_question_id": self.external_question_id,
            "discussion_url": self.discussion_url,
            "discussion_count": self.discussion_count,
            "vote_distribution": dict(self.vote_distribution) if self.vote_distribution else None,
        }


__all__ = ["ParsedCommunityRow", "VoteDistribution"]
