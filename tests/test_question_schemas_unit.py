"""Hermetic Phase 06 schema/validator unit tests — no DB."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import QuestionType
from app.schemas.question import (
    OptionsReplace,
    QuestionCreate,
    QuestionUpdate,
    RetireIn,
)
from app.services.question_service import (
    QuestionValidationError,
    _content_hash,
    _validate_options,
)


def _opts(*pairs):
    return [(label, text) for label, text in pairs]


def test_validate_options_min_two() -> None:
    with pytest.raises(QuestionValidationError, match="at least two"):
        _validate_options(_opts(("A", "x")), ["A"], QuestionType.single)


def test_validate_options_max_six() -> None:
    """Storage cap raised from A–E to A–F on 2026-05-04 to match dump-style
    XLSX feeds whose `combined_options` cell can carry up to six options.
    A seventh option is still rejected.
    """
    with pytest.raises(QuestionValidationError, match="at most six"):
        _validate_options(
            _opts(
                ("A", "1"),
                ("B", "2"),
                ("C", "3"),
                ("D", "4"),
                ("E", "5"),
                ("F", "6"),
                ("G", "7"),
            ),
            ["A"],
            QuestionType.single,
        )


def test_validate_options_accepts_six() -> None:
    """A six-option question (A–F) must validate without raising."""
    _validate_options(
        _opts(("A", "1"), ("B", "2"), ("C", "3"), ("D", "4"), ("E", "5"), ("F", "6")),
        ["A"],
        QuestionType.single,
    )


def test_validate_options_consecutive_labels() -> None:
    with pytest.raises(QuestionValidationError, match="consecutive"):
        _validate_options(_opts(("A", "x"), ("C", "z")), ["A"], QuestionType.single)


def test_validate_correct_label_must_exist() -> None:
    with pytest.raises(QuestionValidationError, match="no matching"):
        _validate_options(_opts(("A", "x"), ("B", "y")), ["Z"], QuestionType.single)


def test_validate_single_requires_one() -> None:
    with pytest.raises(QuestionValidationError, match="single-choice"):
        _validate_options(
            _opts(("A", "x"), ("B", "y"), ("C", "z")),
            ["A", "B"],
            QuestionType.single,
        )


def test_validate_multiple_requires_two_plus() -> None:
    with pytest.raises(QuestionValidationError, match="multiple-choice"):
        _validate_options(
            _opts(("A", "x"), ("B", "y"), ("C", "z")),
            ["A"],
            QuestionType.multiple,
        )


def test_validate_passes_for_well_formed_single() -> None:
    _validate_options(_opts(("A", "x"), ("B", "y")), ["A"], QuestionType.single)


def test_validate_passes_for_well_formed_multiple() -> None:
    _validate_options(_opts(("A", "x"), ("B", "y"), ("C", "z")), ["A", "C"], QuestionType.multiple)


def test_content_hash_invariant_to_option_order() -> None:
    h1 = _content_hash("Q?", _opts(("A", "alpha"), ("B", "beta"), ("C", "gamma")))
    h2 = _content_hash("Q?", _opts(("C", "gamma"), ("A", "alpha"), ("B", "beta")))
    assert h1 == h2


def test_content_hash_changes_on_text_edit() -> None:
    a = _content_hash("Q?", _opts(("A", "x"), ("B", "y")))
    b = _content_hash("Q??", _opts(("A", "x"), ("B", "y")))
    assert a != b


def test_question_create_min_options_enforced() -> None:
    with pytest.raises(ValidationError):
        QuestionCreate.model_validate(
            {
                "exam_id": 1,
                "question_text": "Q?",
                "options": [{"label": "A", "text": "x"}],
                "correct_answer": ["A"],
            }
        )


def test_question_create_blank_text_rejected() -> None:
    with pytest.raises(ValidationError):
        QuestionCreate.model_validate(
            {
                "exam_id": 1,
                "question_text": "",
                "options": [{"label": "A", "text": "x"}, {"label": "B", "text": "y"}],
                "correct_answer": ["A"],
            }
        )


def test_question_update_partial_ok() -> None:
    upd = QuestionUpdate.model_validate({"difficulty": "easy"})
    assert upd.difficulty == "easy"
    assert upd.question_text is None


def test_options_replace_validates_labels_and_correct() -> None:
    body = OptionsReplace.model_validate(
        {
            "options": [{"label": "A", "text": "x"}, {"label": "B", "text": "y"}],
            "correct_answer": ["A"],
        }
    )
    assert len(body.options) == 2


def test_retire_reason_required() -> None:
    with pytest.raises(ValidationError):
        RetireIn.model_validate({"reason": ""})
    body = RetireIn.model_validate({"reason": "wrong answer"})
    assert body.reason == "wrong answer"
