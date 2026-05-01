"""Hermetic Phase 05 unit tests — normalizer / validator / dedup / parser.

No DB — all logic is in pure functions.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.models.enums import ImportItemStatus
from app.services import import_dedup
from app.services.excel_parser import auto_map, read_headers, stream_rows
from app.services.import_normalizer import normalize_row, normalize_text
from app.services.import_validator import validate_row

# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def test_normalize_text_strips_html() -> None:
    assert normalize_text("<script>alert(1)</script>hello") == "alert(1)hello"


def test_normalize_text_strips_zero_width_chars() -> None:
    s = "Hello​‌‍world﻿!"
    assert normalize_text(s) == "Helloworld!"


def test_normalize_text_collapses_whitespace_and_nfkc() -> None:
    # full-width "ＡＢＣ" → "ABC" via NFKC
    assert normalize_text("  ＡＢＣ   def  ") == "ABC def"


def test_normalize_text_handles_none() -> None:
    assert normalize_text(None) is None
    # blank-after-strip → None
    assert normalize_text("   \t\n ") is None


def test_normalize_row_recursively_handles_strings_in_list() -> None:
    out = normalize_row({"a": "  hi  ", "n": 5, "list": ["<b>x</b>", "y"]})
    assert out == {"a": "hi", "n": 5, "list": ["x", "y"]}


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def _good_row():
    return {
        "question_text": "What does VPN stand for?",
        "option_a": "Virtual Private Network",
        "option_b": "Voice Packet Node",
        "option_c": "Visible Public Network",
        "correct_answer": "A",
        "difficulty": "easy",
    }


def test_validate_ok_row_returns_ok_with_canonical_form() -> None:
    r = validate_row(_good_row())
    assert r.status == ImportItemStatus.ok
    assert r.canonical["question_type"] == "single"
    assert r.canonical["correct_answer"] == ["A"]
    assert r.canonical["difficulty"] == "easy"


def test_validate_missing_question_text_is_error() -> None:
    row = _good_row()
    row["question_text"] = ""
    r = validate_row(row)
    assert r.status == ImportItemStatus.error
    assert "question_text required" in (r.error_message or "")


def test_validate_correct_answer_unknown_label_is_error() -> None:
    row = _good_row()
    row["correct_answer"] = "Z"
    r = validate_row(row)
    assert r.status == ImportItemStatus.error
    assert "unknown" in (r.error_message or "")


def test_validate_multiple_choice_inferred_when_correct_has_comma() -> None:
    row = _good_row()
    row["correct_answer"] = "A,C"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["question_type"] == "multiple"
    assert r.canonical["correct_answer"] == ["A", "C"]


def test_validate_difficulty_unknown_demotes_to_warning() -> None:
    row = _good_row()
    row["difficulty"] = "platinum"
    r = validate_row(row)
    assert r.status == ImportItemStatus.warning
    assert r.canonical["difficulty"] == "medium"


def test_validate_under_two_options_is_error() -> None:
    row = _good_row()
    row["option_b"] = ""
    row["option_c"] = ""
    r = validate_row(row)
    assert r.status == ImportItemStatus.error
    assert "at least two options" in (r.error_message or "")


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def test_content_hash_stable_across_option_order() -> None:
    canonical_a = {
        "question_text": "Q?",
        "options": [("A", "alpha"), ("B", "beta"), ("C", "gamma")],
    }
    canonical_b = {
        "question_text": "Q?",
        "options": [("C", "gamma"), ("A", "alpha"), ("B", "beta")],
    }
    assert import_dedup.content_hash(canonical_a) == import_dedup.content_hash(canonical_b)


def test_content_hash_changes_on_question_text_edit() -> None:
    a = import_dedup.content_hash({"question_text": "Q?", "options": [("A", "x")]})
    b = import_dedup.content_hash({"question_text": "Q??", "options": [("A", "x")]})
    assert a != b


# ---------------------------------------------------------------------------
# Excel parser
# ---------------------------------------------------------------------------


def _make_workbook(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Question", "A", "B", "Correct", "Difficulty"])
    ws.append(["What is 2+2?", "3", "4", "B", "easy"])
    ws.append(["What is 3+3?", "5", "6", "B", "medium"])
    # Empty row
    ws.append([None, None, None, None, None])
    path = tmp_path / "demo.xlsx"
    wb.save(str(path))
    return path


def test_excel_parser_auto_map_aliases() -> None:
    headers = ["Question", "A", "B", "Correct", "Difficulty", "Random"]
    m = auto_map(headers)
    assert m == {
        "Question": "question_text",
        "A": "option_a",
        "B": "option_b",
        "Correct": "correct_answer",
        "Difficulty": "difficulty",
        "Random": None,
    }


def test_excel_parser_streams_rows_and_skips_empty(tmp_path: Path) -> None:
    path = _make_workbook(tmp_path)
    sheet, headers = read_headers(path)
    assert sheet == "Sheet1"
    assert headers == ["Question", "A", "B", "Correct", "Difficulty"]

    mapping = auto_map(headers)
    rows = list(stream_rows(path, column_mapping=mapping, max_rows=10))
    assert len(rows) == 2  # empty trailer skipped
    assert rows[0].row_number == 2
    assert rows[0].raw == {
        "question_text": "What is 2+2?",
        "option_a": "3",
        "option_b": "4",
        "correct_answer": "B",
        "difficulty": "easy",
    }


def test_excel_parser_caps_rows(tmp_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["Question", "A", "B", "Correct"])
    for i in range(5):
        ws.append([f"q{i}", "x", "y", "A"])
    p = tmp_path / "big.xlsx"
    wb.save(str(p))
    headers = ["Question", "A", "B", "Correct"]
    mapping = auto_map(headers)
    # max_rows=2 → third data row must raise.
    import pytest

    with pytest.raises(ValueError, match="too many data rows"):
        list(stream_rows(p, column_mapping=mapping, max_rows=2))
