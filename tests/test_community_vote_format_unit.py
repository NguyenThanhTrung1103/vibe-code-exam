"""Phase 16a — pure unit tests for `format_vote_distribution`.

Hermetic. No DB, no FastAPI, no template rendering. Validates the helper
that the read-only community tab uses to convert raw `dict[str, int]`
vote counts into a render-friendly structure.
"""

from __future__ import annotations

import pytest

from app.routers.admin.community_sources import format_vote_distribution


def test_empty_input_returns_empty_list() -> None:
    assert format_vote_distribution(None, None) == []
    assert format_vote_distribution({}, None) == []
    assert format_vote_distribution(None, "A") == []


def test_single_label_returns_single_row_with_100_percent() -> None:
    out = format_vote_distribution({"A": 5}, None)
    assert out == [{"label": "A", "count": 5, "percent": 100.0, "is_pick": False}]


def test_multi_label_sorted_by_count_desc() -> None:
    out = format_vote_distribution({"A": 5, "B": 10, "C": 3}, None)
    labels = [r["label"] for r in out]
    counts = [r["count"] for r in out]
    assert labels == ["B", "A", "C"]
    assert counts == [10, 5, 3]


def test_tied_counts_sorted_by_label_ascending_for_determinism() -> None:
    out = format_vote_distribution({"D": 4, "A": 4, "C": 4}, None)
    assert [r["label"] for r in out] == ["A", "C", "D"]


def test_pick_flag_set_when_label_matches_community_pick_uppercase() -> None:
    out = format_vote_distribution({"A": 5, "B": 3}, "a")
    by_label = {r["label"]: r for r in out}
    assert by_label["A"]["is_pick"] is True
    assert by_label["B"]["is_pick"] is False


def test_pick_flag_case_insensitive_match() -> None:
    out = format_vote_distribution({"a": 5, "b": 3}, "A")
    by_label = {r["label"]: r for r in out}
    assert by_label["a"]["is_pick"] is True
    assert by_label["b"]["is_pick"] is False


def test_no_pick_when_community_pick_is_none() -> None:
    out = format_vote_distribution({"A": 5, "B": 3}, None)
    assert all(r["is_pick"] is False for r in out)


def test_percentages_use_one_decimal_place() -> None:
    out = format_vote_distribution({"A": 1, "B": 2, "C": 1}, None)
    by_label = {r["label"]: r for r in out}
    assert by_label["B"]["percent"] == 50.0
    assert by_label["A"]["percent"] == 25.0
    assert by_label["C"]["percent"] == 25.0


def test_percentages_sum_close_to_one_hundred() -> None:
    out = format_vote_distribution({"A": 21, "B": 6, "C": 3}, None)
    total = sum(r["percent"] for r in out)
    # rounding to 1 decimal can drift up to ~0.3 from 100.0 in worst case.
    assert abs(total - 100.0) < 1.0


def test_all_zero_counts_no_division_error() -> None:
    out = format_vote_distribution({"A": 0, "B": 0}, None)
    assert all(r["percent"] == 0.0 for r in out)


def test_non_string_pick_treated_as_no_pick() -> None:
    out = format_vote_distribution({"A": 1}, 123)  # type: ignore[arg-type]
    assert out[0]["is_pick"] is False


@pytest.mark.parametrize(
    "raw,pick,expected_pick_label",
    [
        ({"A": 1, "B": 2}, "B", "B"),
        ({"A": 1, "AC": 5}, "AC", "AC"),
        ({"True": 4, "Fals": 1}, "True", "True"),
    ],
)
def test_dynamic_labels_supported_inc_multi_correct(
    raw: dict[str, int], pick: str, expected_pick_label: str
) -> None:
    out = format_vote_distribution(raw, pick)
    picks = [r["label"] for r in out if r["is_pick"]]
    assert picks == [expected_pick_label]
