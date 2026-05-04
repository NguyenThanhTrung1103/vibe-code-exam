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
from app.services.import_service import required_mapping_missing
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


# ---------------------------------------------------------------------------
# Milestone 1 regressions — combined_options + Vietnamese alias map
# ---------------------------------------------------------------------------


def test_combined_options_split_into_option_slots() -> None:
    """A `combined_options` cell is split into option_a..option_f by the normalizer.

    Regression for the Vietnamese / dump-style XLSX path: a single sheet column
    holding `A. EC2; B. S3; C. Lambda` must yield individual option_* slots
    that the validator already understands. Individual `option_*` keys, when
    present, must win over split values.
    """
    out = normalize_row(
        {
            "question_text": "Which is object storage?",
            "combined_options": "A. EC2 ; B. S3 ; C. Lambda ; D. RDS",
            "correct_answer": "B",
        }
    )
    assert out["option_a"] == "EC2"
    assert out["option_b"] == "S3"
    assert out["option_c"] == "Lambda"
    assert out["option_d"] == "RDS"
    # combined_options must be popped — only individual slots survive.
    assert "combined_options" not in out


def test_combined_options_does_not_overwrite_explicit_option_slots() -> None:
    """Explicit option_a wins over the split combined_options value."""
    out = normalize_row(
        {
            "question_text": "Q?",
            "option_a": "explicit-A",
            "combined_options": "A. should-not-win ; B. beta",
        }
    )
    assert out["option_a"] == "explicit-A"
    assert out["option_b"] == "beta"


def test_vietnamese_alias_map_routes_to_canonical_fields() -> None:
    """The Vietnamese header alias map continues to map to canonical fields.

    Smoke test that auto_map still recognises representative Vietnamese
    headers — protects against accidental regressions when adding adapters.
    """
    headers = ["Nội dung câu hỏi", "Đáp án A", "Đáp án B", "Đáp án đúng"]
    m = auto_map(headers)
    assert m["Nội dung câu hỏi"] == "question_text"
    # Đáp án A / B normalise to dapana / dapanb in the alias key after accent
    # stripping — they may or may not exist as aliases. The contract we need
    # to defend is: question_text + correct_answer keep working.
    assert m["Đáp án đúng"] == "correct_answer"


def test_vietnamese_dump_combined_options_and_explanation_no_collision() -> None:
    """Vietnamese dump shape used by import #142 must auto-map cleanly.

    Both "Giải thích đáp án" and "Mô tả thêm" used to land on `explanation`,
    which silently dropped one column. After the fix, "Giải thích đáp án"
    owns `explanation` and "Mô tả thêm" goes to `reference`.
    """
    headers = [
        "Câu hỏi",
        "Danh sách đáp án (ví dụ A. ...)",
        "Đáp án đúng (ví dụ A)",
        "Giải thích đáp án",
        "Mô tả thêm",
        "Tags",
    ]
    m = auto_map(headers)
    assert m["Câu hỏi"] == "question_text"
    assert m["Danh sách đáp án (ví dụ A. ...)"] == "combined_options"
    assert m["Đáp án đúng (ví dụ A)"] == "correct_answer"
    assert m["Giải thích đáp án"] == "explanation"
    assert m["Mô tả thêm"] == "reference"
    assert m["Tags"] == "tags"
    # No two headers may resolve to the same canonical.
    canonicals = [v for v in m.values() if v]
    assert len(canonicals) == len(set(canonicals)), m


def test_motathem_alias_routes_to_reference_not_explanation() -> None:
    """Standalone alias check — `Mô tả thêm` is reference, not explanation."""
    m = auto_map(["Mô tả thêm"])
    assert m["Mô tả thêm"] == "reference"


def test_loaicauhoi_does_not_steal_question_text() -> None:
    """`Loại câu hỏi` must map to `question_type`, not `question_text`.

    Without an explicit alias, the `cauhoi` substring fallback would match
    inside `loaicauhoi` and steal `question_text` from the real question
    column on import #142.
    """
    m = auto_map(["Loại câu hỏi", "Câu hỏi(Tiêu đề)"])
    assert m["Loại câu hỏi"] == "question_type"
    assert m["Câu hỏi(Tiêu đề)"] == "question_text"


def test_tags_prefix_beats_buried_combined_options_substring() -> None:
    """`Tags (Các đáp án ...)` must map to `tags`, not `combined_options`.

    The header starts with `tags` (pos 0, len 4); a longer alias key
    `cacdapan` (combined_options, len 8) appears mid-header. Position-0
    matches must beat buried longer matches.
    """
    m = auto_map(["Tags (Các đáp án ngăn cách nhau bởi dấu chấm phẩy)"])
    assert m["Tags (Các đáp án ngăn cách nhau bởi dấu chấm phẩy)"] == "tags"


def test_import_142_full_fixture_shape_auto_map() -> None:
    """End-to-end check on the exact header shape from import #142.

    Locks in the contract for the canonical Vietnamese XLSX dump:
    Loại câu hỏi → question_type
    Câu hỏi(Tiêu đề) * → question_text
    Mô tả thêm → reference
    Tags (...) → tags
    Danh sách đáp án (...) → combined_options
    Đáp án đúng (...) → correct_answer
    Giải thích đáp án → explanation
    """
    headers = [
        "Loại câu hỏi",
        "Câu hỏi(Tiêu đề) *",
        "Mô tả thêm",
        "Tags (Các đáp án ngăn cách nhau bởi dấu chấm phẩy)",
        "Danh sách đáp án (Các đáp án ngăn cách nhau bởi dấu chấm phẩy) *",
        "Đáp án đúng (ví dụ câu trả lời 1 là đáp án đúng thì điền 1, các đáp án ngăn cách bằng dấu chấm phẩy) *",
        "Giải thích đáp án",
    ]
    m = auto_map(headers)
    assert m["Loại câu hỏi"] == "question_type"
    assert m["Câu hỏi(Tiêu đề) *"] == "question_text"
    assert m["Mô tả thêm"] == "reference"
    assert m["Tags (Các đáp án ngăn cách nhau bởi dấu chấm phẩy)"] == "tags"
    assert (
        m["Danh sách đáp án (Các đáp án ngăn cách nhau bởi dấu chấm phẩy) *"]
        == "combined_options"
    )
    assert (
        m[
            "Đáp án đúng (ví dụ câu trả lời 1 là đáp án đúng thì điền 1, "
            "các đáp án ngăn cách bằng dấu chấm phẩy) *"
        ]
        == "correct_answer"
    )
    assert m["Giải thích đáp án"] == "explanation"
    canonicals = [v for v in m.values() if v]
    assert len(canonicals) == len(set(canonicals)), m


def test_giaithichdapan_wins_explanation_over_giaithich_only() -> None:
    """When both `Giải thích đáp án` and `Giải thích` are present, the more
    specific alias `giaithichdapan` keeps `explanation`; `Giải thích` alone
    is demoted to None to avoid the duplicate-canonical collision.
    """
    m = auto_map(["Giải thích đáp án", "Giải thích"])
    assert m["Giải thích đáp án"] == "explanation"
    # `Giải thích` alone normalises to `giaithich` which exact-matches the
    # alias too — but the longer key wins, so the rival is reset to None.
    assert m["Giải thích"] is None


def test_auto_map_drops_duplicate_canonicals() -> None:
    """Two headers cannot silently auto-map to the same canonical field.

    Synthetic case: a sheet with two `Question` columns. The first wins;
    the second is reset to None so the operator must pick manually.
    """
    m = auto_map(["Question", "Question Text"])
    canonicals = [v for v in m.values() if v]
    assert canonicals.count("question_text") == 1, m


# ---------------------------------------------------------------------------
# save_mapping rule — combined_options satisfies option_a + option_b
# ---------------------------------------------------------------------------


def test_required_mapping_accepts_combined_options_without_option_a_b() -> None:
    """The Vietnamese / dump-style mapping for import #142 must validate.

    Required: question_text + correct_answer + combined_options
    (no separate option_a / option_b).
    """
    missing = required_mapping_missing(
        {
            "Câu hỏi": "question_text",
            "Đáp án đúng": "correct_answer",
            "Danh sách đáp án": "combined_options",
            "Giải thích đáp án": "explanation",
        }
    )
    assert missing == []


def test_required_mapping_accepts_explicit_option_a_b() -> None:
    """Classic XLSX shape with discrete option_a / option_b columns."""
    missing = required_mapping_missing(
        {
            "Question": "question_text",
            "A": "option_a",
            "B": "option_b",
            "Correct": "correct_answer",
        }
    )
    assert missing == []


def test_required_mapping_rejects_when_neither_option_path_present() -> None:
    """No option_a/b and no combined_options → mapping is invalid."""
    missing = required_mapping_missing(
        {
            "Question": "question_text",
            "Correct": "correct_answer",
        }
    )
    assert "option_a + option_b OR combined_options" in missing


def test_required_mapping_reports_question_text_missing() -> None:
    """Missing question_text is reported alongside any other gaps."""
    missing = required_mapping_missing(
        {
            "Correct": "correct_answer",
            "Combined": "combined_options",
        }
    )
    assert "question_text" in missing
    assert "correct_answer" not in missing
