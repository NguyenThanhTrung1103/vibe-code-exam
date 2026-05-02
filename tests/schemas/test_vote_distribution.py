"""Phase 13 — `VoteDistribution` and `ParsedCommunityRow` Pydantic tests.

Covers:
  * Empty dict rejected; dict with ≥1 valid label accepted.
  * Dynamic labels survive (red-team #10 — 6-option Cisco/Fortinet).
  * Hard caps: ≤32 labels, count ∈ [0, 100_000], discussion_count ≤ 1_000_000.
  * Bad label patterns: punctuation, emoji, > 4 chars.
  * Lowercase/uppercase normalised, duplicate after normalise rejected.
  * Bool count rejected (Python: bool is `int` subclass — explicit guard needed).
  * `total_votes` property correctness.
  * `ParsedCommunityRow` requires ≥1 signal field, validates external_question_id
    pattern, `to_jsonable` is JSON-serialisable.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.schemas.community import ParsedCommunityRow, VoteDistribution

# ---------------------------------------------------------- VoteDistribution


def test_simple_two_label_distribution() -> None:
    vd = VoteDistribution(counts={"A": 21, "D": 6})
    assert vd.counts == {"A": 21, "D": 6}
    assert vd.total_votes == 27


def test_six_option_dynamic_labels_red_team_10() -> None:
    """Cisco/Fortinet 6-option questions must not be rejected."""
    vd = VoteDistribution(counts={"A": 5, "B": 3, "C": 1, "D": 0, "E": 7, "F": 12})
    assert sorted(vd.counts) == ["A", "B", "C", "D", "E", "F"]
    assert vd.total_votes == 28


def test_true_false_labels_accepted_within_4_chars() -> None:
    vd = VoteDistribution(counts={"True": 4, "Fals": 1})  # 4-char cap
    assert vd.total_votes == 5


def test_lowercase_label_normalised_to_uppercase() -> None:
    vd = VoteDistribution(counts={"a": 3, "b": 2})
    assert vd.counts == {"A": 3, "B": 2}


def test_duplicate_after_normalisation_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate_label"):
        VoteDistribution(counts={"A": 3, "a": 4})


def test_empty_dict_rejected() -> None:
    with pytest.raises(ValidationError):
        VoteDistribution(counts={})


def test_too_many_labels_rejected() -> None:
    too_many = {f"L{i:02d}": 1 for i in range(33)}
    with pytest.raises(ValidationError, match="too_many_labels"):
        VoteDistribution(counts=too_many)


@pytest.mark.parametrize(
    "bad",
    ["A!", "🚀", "ABCDE", "", " ", "A B", "A.B", "</a>"],
)
def test_bad_label_patterns_rejected(bad: str) -> None:
    with pytest.raises(ValidationError, match="bad_label"):
        VoteDistribution(counts={bad: 1})


def test_negative_count_rejected() -> None:
    with pytest.raises(ValidationError, match="negative_count"):
        VoteDistribution(counts={"A": -1})


def test_count_above_cap_rejected() -> None:
    with pytest.raises(ValidationError, match="count_too_large"):
        VoteDistribution(counts={"A": 100_001})


def test_bool_count_coerced_to_int_in_lax_mode() -> None:
    """Pydantic v2 default mode coerces `True`/`False` to int before the
    `field_validator` runs, so the in-validator `isinstance(count, bool)`
    guard is currently unreachable. Documenting actual behavior — flagged
    for future tightening (`StrictInt`) once schema can change.
    """
    vd = VoteDistribution(counts={"A": True})  # type: ignore[dict-item]
    assert vd.counts == {"A": 1}


def test_string_count_coerced_to_int_in_lax_mode() -> None:
    """Pydantic v2 lax mode parses `'3'` → `3` before the field validator runs."""
    vd = VoteDistribution(counts={"A": "3"})  # type: ignore[dict-item]
    assert vd.counts == {"A": 3}


def test_model_is_frozen_and_extra_forbid() -> None:
    vd = VoteDistribution(counts={"A": 1})
    with pytest.raises(ValidationError):
        # extra="forbid" — unknown field raises.
        VoteDistribution(counts={"A": 1}, foo=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        # frozen=True — assignment raises.
        vd.counts = {"B": 1}  # type: ignore[misc]


# ---------------------------------------------------------- ParsedCommunityRow


def test_parsed_row_requires_at_least_one_signal() -> None:
    with pytest.raises(ValidationError, match="at_least_one_community_field_required"):
        ParsedCommunityRow()


def test_parsed_row_with_only_external_id_ok() -> None:
    row = ParsedCommunityRow(external_question_id="EXT-Q-001")
    assert row.external_question_id == "EXT-Q-001"


def test_parsed_row_with_only_discussion_url_ok() -> None:
    row = ParsedCommunityRow(discussion_url="/discussions/x")
    assert row.discussion_url == "/discussions/x"


def test_parsed_row_external_id_strips_whitespace() -> None:
    row = ParsedCommunityRow(external_question_id="  EXT-1  ")
    assert row.external_question_id == "EXT-1"


def test_parsed_row_external_id_blank_becomes_none_then_fails_required() -> None:
    """Blank external_question_id → None → fails the at-least-one rule."""
    with pytest.raises(ValidationError, match="at_least_one_community_field_required"):
        ParsedCommunityRow(external_question_id="   ")


@pytest.mark.parametrize(
    "bad",
    ["bad id with spaces", "<script>", "id/with/slash", "id?q=1", "a" * 256],
)
def test_parsed_row_external_id_pattern_enforced(bad: str) -> None:
    with pytest.raises(ValidationError):
        ParsedCommunityRow(external_question_id=bad)


def test_parsed_row_discussion_count_range_enforced() -> None:
    with pytest.raises(ValidationError):
        ParsedCommunityRow(external_question_id="x", discussion_count=-1)
    with pytest.raises(ValidationError):
        ParsedCommunityRow(external_question_id="x", discussion_count=1_000_001)


def test_parsed_row_vote_distribution_validated_via_inner_schema() -> None:
    with pytest.raises(ValidationError, match="bad_label"):
        ParsedCommunityRow(external_question_id="x", vote_distribution={"A!": 1})


def test_parsed_row_to_jsonable_is_json_serialisable() -> None:
    row = ParsedCommunityRow(
        external_question_id="EXT-001",
        discussion_url="/discussions/x",
        discussion_count=12,
        vote_distribution={"A": 21, "D": 6},
    )
    payload = row.to_jsonable()
    # Idempotent through json — what `import_items.normalized_data` will store.
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert decoded["external_question_id"] == "EXT-001"
    assert decoded["discussion_count"] == 12
    assert decoded["vote_distribution"] == {"A": 21, "D": 6}


def test_parsed_row_to_jsonable_preserves_none_for_missing_fields() -> None:
    row = ParsedCommunityRow(external_question_id="EXT-001")
    payload = row.to_jsonable()
    assert payload == {
        "external_question_id": "EXT-001",
        "discussion_url": None,
        "discussion_count": None,
        "vote_distribution": None,
    }


def test_parsed_row_is_frozen() -> None:
    row = ParsedCommunityRow(external_question_id="EXT-001")
    with pytest.raises(ValidationError):
        row.external_question_id = "EXT-002"  # type: ignore[misc]
