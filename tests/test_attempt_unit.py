"""Hermetic Phase 07 unit tests — pure-function behaviour, no DB."""

from __future__ import annotations

import random

from app.services.attempt_service import _parse_selected_labels
from app.services.question_selector import shuffled_question_ids


def test_parse_none_yields_empty() -> None:
    assert _parse_selected_labels(None) == []


def test_parse_blank_string_yields_empty() -> None:
    assert _parse_selected_labels("") == []


def test_parse_single_label() -> None:
    assert _parse_selected_labels("B") == ["B"]


def test_parse_csv_uppercased_and_sorted() -> None:
    assert _parse_selected_labels("c,a") == ["A", "C"]


def test_parse_dedup() -> None:
    assert _parse_selected_labels(["A", "a", "C", "C"]) == ["A", "C"]


def test_parse_strips_whitespace() -> None:
    assert _parse_selected_labels(" b , c ") == ["B", "C"]


def test_parse_list_form() -> None:
    assert _parse_selected_labels(["A", "C"]) == ["A", "C"]


class _FakeQ:
    def __init__(self, qid: int) -> None:
        self.id = qid


def test_shuffled_question_ids_is_a_permutation() -> None:
    qs = [_FakeQ(i) for i in range(1, 11)]
    out = shuffled_question_ids(qs)
    assert sorted(out) == list(range(1, 11))


def test_shuffled_question_ids_reproducible_with_seeded_rng() -> None:
    qs = [_FakeQ(i) for i in range(1, 11)]
    rng_a = random.Random(42)
    rng_b = random.Random(42)
    assert shuffled_question_ids(qs, rng=rng_a) == shuffled_question_ids(qs, rng=rng_b)


def test_parse_only_comma_splits() -> None:
    """Commas are the only accepted separator; semicolons stay inside the token
    so downstream label validation rejects them."""
    assert _parse_selected_labels("A") == ["A"]
    assert _parse_selected_labels("a,b") == ["A", "B"]
    # 'A;B' is one token after splitting on ',' — service validation
    # rejects it because it's not a known option label.
    assert _parse_selected_labels("a;b") == ["A;B"]
