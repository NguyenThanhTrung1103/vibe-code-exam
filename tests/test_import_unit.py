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


def test_combined_options_seven_slots_now_ok_under_a_h() -> None:
    """7-piece combined_options splits cleanly into A..G under the A–H cap."""
    raw = normalize_row(
        {
            "question_text": "Pick one",
            "combined_options": "o1;o2;o3;o4;o5;o6;o7",
            "correct_answer": "A",
        }
    )
    r = validate_row(raw)
    assert r.status == ImportItemStatus.ok, r.error_message
    assert dict(r.canonical["options"])["G"] == "o7"


def test_correct_answer_numeric_nine_out_of_range() -> None:
    """1–8 map to A–H; 9 is past the cap."""
    row = _good_row()
    row["correct_answer"] = "9"
    r = validate_row(row)
    assert r.status == ImportItemStatus.error
    assert "out of range" in (r.error_message or "").lower()


def test_correct_answer_bd_contiguous_expands() -> None:
    row = _good_row()
    row["option_d"] = "fourth"
    row["correct_answer"] = "BD"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert set(r.canonical["correct_answer"]) == {"B", "D"}


# ---------------------------------------------------------------------------
# question_type alias normalization (Vietnamese XLSX dump #142 + friends)
# ---------------------------------------------------------------------------


def test_qtype_choice_with_single_correct_resolves_to_single() -> None:
    row = _good_row()
    row["question_type"] = "choice"
    row["correct_answer"] = "A"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["question_type"] == "single"


def test_qtype_choice_with_multi_correct_resolves_to_multiple() -> None:
    row = _good_row()
    row["question_type"] = "choice"
    row["correct_answer"] = "A,C"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["question_type"] == "multiple"


def test_qtype_one_choice_alias_resolves_to_single() -> None:
    """`one_choice` is the actual cell value seen on import #142."""
    row = _good_row()
    row["question_type"] = "one_choice"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["question_type"] == "single"


def test_qtype_multi_choice_alias_resolves_to_multiple() -> None:
    """`multi_choice` is the actual multi-answer cell value on #142."""
    row = _good_row()
    row["question_type"] = "multi_choice"
    row["correct_answer"] = "A,C"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["question_type"] == "multiple"


def test_qtype_radio_alias_resolves_to_single() -> None:
    row = _good_row()
    row["question_type"] = "radio"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["question_type"] == "single"


def test_qtype_checkbox_alias_resolves_to_multiple() -> None:
    row = _good_row()
    row["question_type"] = "checkbox"
    row["correct_answer"] = "A,C"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["question_type"] == "multiple"


def test_qtype_true_false_alias_normalizes() -> None:
    """`Boolean` / `truefalse` should land on `true_false`."""
    row = _good_row()
    row["question_type"] = "Boolean"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["question_type"] == "true_false"


def test_qtype_blank_with_multi_correct_infers_multiple() -> None:
    row = _good_row()
    row["question_type"] = ""
    row["correct_answer"] = "A,C"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["question_type"] == "multiple"


def test_qtype_unknown_value_still_errors_clearly() -> None:
    """Unknown alias must surface a precise error, not silently mis-route."""
    row = _good_row()
    row["question_type"] = "essay"
    r = validate_row(row)
    assert r.status == ImportItemStatus.error
    assert "question_type" in (r.error_message or "")


# ---------------------------------------------------------------------------
# correct_answer normalization (numeric + contiguous + multi-letter + F)
# ---------------------------------------------------------------------------


def test_correct_answer_contiguous_letters_AC_expands() -> None:
    row = _good_row()
    row["correct_answer"] = "AC"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["correct_answer"] == ["A", "C"]
    assert r.canonical["question_type"] == "multiple"


def test_correct_answer_contiguous_letters_BD_expands() -> None:
    row = _good_row()
    row["option_d"] = "delta"
    row["correct_answer"] = "BD"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok, r.error_message
    assert r.canonical["correct_answer"] == ["B", "D"]


def test_correct_answer_numeric_semicolon_pair_resolves() -> None:
    """`1;3` is the canonical multi-answer shape on import #142."""
    row = _good_row()
    row["correct_answer"] = "1;3"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["correct_answer"] == ["A", "C"]
    assert r.canonical["question_type"] == "multiple"


def test_correct_answer_numeric_comma_pair_resolves() -> None:
    row = _good_row()
    row["correct_answer"] = "1,3"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["correct_answer"] == ["A", "C"]


def test_correct_answer_numeric_six_resolves_to_F() -> None:
    """1–6 must map to A–F end-to-end (option_f is now a real slot)."""
    row = _good_row()
    row["option_d"] = "delta"
    row["option_e"] = "epsilon"
    row["option_f"] = "phi"
    row["correct_answer"] = "6"
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok
    assert r.canonical["correct_answer"] == ["F"]


def test_correct_answer_full_text_match_resolves() -> None:
    """A verbatim option text in the correct_answer cell maps to its label."""
    row = _good_row()
    row["correct_answer"] = "Voice Packet Node"  # verbatim option_b text
    r = validate_row(row)
    assert r.status == ImportItemStatus.ok, r.error_message
    assert r.canonical["correct_answer"] == ["B"]


def test_correct_answer_label_out_of_options_errors() -> None:
    """`E` referenced when only A–D are present → legitimate error."""
    row = _good_row()
    row["correct_answer"] = "E"
    r = validate_row(row)
    assert r.status == ImportItemStatus.error
    assert "no matching option" in (r.error_message or "")


# ---------------------------------------------------------------------------
# Real import #142-style row — combined_options + Vietnamese qtype
# ---------------------------------------------------------------------------


def test_validate_import_142_style_single_choice_row() -> None:
    """End-to-end: a row that mirrors a real one_choice line from #142."""
    raw = {
        "question_text": "Which protocol works at the network layer?",
        "question_type": "one_choice",
        "combined_options": "TCP;UDP;IP;HTTP",
        "correct_answer": "3",
        "tags": "ccna_online",
    }
    normalized = normalize_row(raw)
    r = validate_row(normalized)
    assert r.status == ImportItemStatus.ok, r.error_message
    assert r.canonical["question_type"] == "single"
    assert r.canonical["correct_answer"] == ["C"]
    assert dict(r.canonical["options"]) == {
        "A": "TCP",
        "B": "UDP",
        "C": "IP",
        "D": "HTTP",
    }


def test_validate_import_142_style_multi_choice_row() -> None:
    """End-to-end: a row that mirrors a real multi_choice line from #142."""
    raw = {
        "question_text": "Which of the following are private IP networks?",
        "question_type": "multi_choice",
        "combined_options": "172.31.0.0;172.32.0.0;192.168.255.0;192.1.168.0;11.0.0.0",
        "correct_answer": "1;3",
        "tags": "ccna_online",
    }
    normalized = normalize_row(raw)
    r = validate_row(normalized)
    assert r.status == ImportItemStatus.ok, r.error_message
    assert r.canonical["question_type"] == "multiple"
    assert r.canonical["correct_answer"] == ["A", "C"]
    assert dict(r.canonical["options"]) == {
        "A": "172.31.0.0",
        "B": "172.32.0.0",
        "C": "192.168.255.0",
        "D": "192.1.168.0",
        "E": "11.0.0.0",
    }


def test_validate_import_142_style_multi_choice_with_F() -> None:
    """6-option row + correct=4;6 stretches the new A–F support."""
    raw = {
        "question_text": "Pick the transport-layer protocols (choose two):",
        "question_type": "multi_choice",
        "combined_options": "Ethernet;HTTP;IP;UDP;SMTP;TCP",
        "correct_answer": "4;6",
        "tags": "ccna_online",
    }
    normalized = normalize_row(raw)
    r = validate_row(normalized)
    assert r.status == ImportItemStatus.ok, r.error_message
    assert r.canonical["question_type"] == "multiple"
    assert r.canonical["correct_answer"] == ["D", "F"]
    options = dict(r.canonical["options"])
    assert options["F"] == "TCP"


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


def test_find_near_duplicates_skips_short_text() -> None:
    """No DB call when text is below the min-length guard."""

    class _ExplodingSession:
        def execute(self, *_a, **_k):
            raise AssertionError("execute should not be called for short text")

    out = import_dedup.find_near_duplicates(
        _ExplodingSession(),
        exam_id=1,
        question_text="too short",
    )
    assert out == []


def test_near_duplicate_match_to_dict_rounds_similarity() -> None:
    m = import_dedup.NearDuplicateMatch(
        question_id=42, similarity=0.7777777, snippet="x" * 200
    )
    d = m.to_dict()
    assert d["question_id"] == 42
    assert d["similarity"] == 0.778  # rounded to 3 dp
    assert len(d["snippet"]) == 120  # truncated


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
        m["Danh sách đáp án (Các đáp án ngăn cách nhau bởi dấu chấm phẩy) *"] == "combined_options"
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


# ---------------------------------------------------------------------------
# Bug 1 — A–H option support (7- and 8-option rows)
# ---------------------------------------------------------------------------


def test_validate_seven_option_row_with_correct_seven() -> None:
    """7 separate option columns + correct_answer=7 → resolves to G, OK."""
    raw = {
        "question_text": "Pick the seventh option (numeric correct=7).",
        "option_a": "alpha",
        "option_b": "beta",
        "option_c": "gamma",
        "option_d": "delta",
        "option_e": "epsilon",
        "option_f": "zeta",
        "option_g": "eta",
        "correct_answer": "7",
    }
    r = validate_row(raw)
    assert r.status == ImportItemStatus.ok, r.error_message
    assert r.canonical["correct_answer"] == ["G"]
    assert dict(r.canonical["options"])["G"] == "eta"


def test_validate_eight_option_row_with_correct_h() -> None:
    """8 separate option columns + correct_answer=H → OK (mirrors import #142 row 9)."""
    raw = {
        "question_text": "Pick the eighth option.",
        "option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d",
        "option_e": "e", "option_f": "f", "option_g": "g", "option_h": "h",
        "correct_answer": "H",
    }
    r = validate_row(raw)
    assert r.status == ImportItemStatus.ok, r.error_message
    assert r.canonical["correct_answer"] == ["H"]
    assert dict(r.canonical["options"])["H"] == "h"


def test_validate_combined_options_eight_pieces_split_to_h() -> None:
    """combined_options with 8 pieces splits into option_a..option_h."""
    raw = normalize_row(
        {
            "question_text": "Pick anything",
            "combined_options": "o1;o2;o3;o4;o5;o6;o7;o8",
            "correct_answer": "8",
        }
    )
    r = validate_row(raw)
    assert r.status == ImportItemStatus.ok, r.error_message
    assert r.canonical["correct_answer"] == ["H"]
    assert dict(r.canonical["options"])["H"] == "o8"


def test_validate_combined_options_nine_pieces_overflows() -> None:
    """9+ split pieces still error — A–H is the new hard cap."""
    raw = normalize_row(
        {
            "question_text": "Too many options",
            "combined_options": ";".join(f"o{i}" for i in range(1, 10)),
            "correct_answer": "A",
        }
    )
    r = validate_row(raw)
    assert r.status == ImportItemStatus.error
    assert r.error_message and "9" in r.error_message


def test_correct_answer_contiguous_letters_acgh_expands() -> None:
    """`ACGH` (multi-correct shorthand spanning new letters) expands to A,C,G,H."""
    raw = {
        "question_text": "Multi correct across A–H",
        "option_a": "a", "option_b": "b", "option_c": "c", "option_d": "d",
        "option_e": "e", "option_f": "f", "option_g": "g", "option_h": "h",
        "correct_answer": "ACGH",
    }
    r = validate_row(raw)
    assert r.status == ImportItemStatus.ok, r.error_message
    assert r.canonical["correct_answer"] == ["A", "C", "G", "H"]
    assert r.canonical["question_type"] == "multiple"


def test_excel_parser_alias_includes_option_g_and_h() -> None:
    """auto_map() picks up `optionG` / `optionH` headers."""
    m = auto_map(["Question", "Option G", "Option H", "Correct"])
    assert m["Option G"] == "option_g"
    assert m["Option H"] == "option_h"


# ---------------------------------------------------------------------------
# Bug 2 — content_hash canonicalisation
# ---------------------------------------------------------------------------


def test_content_hash_stable_across_whitespace_and_case() -> None:
    """Same question + options modulo case + extra whitespace → same hash."""
    a = import_dedup.content_hash(
        {
            "question_text": "What does VPN stand for?",
            "options": [("A", "Virtual Private Network"), ("B", "Voice Packet Node")],
        }
    )
    b = import_dedup.content_hash(
        {
            "question_text": "  what does   VPN stand for? ",
            "options": [("A", "VIRTUAL  PRIVATE NETWORK"), ("B", "voice packet node ")],
        }
    )
    assert a == b


def test_content_hash_stable_across_diacritics() -> None:
    """Accented vs ASCII transliteration → same hash."""
    a = import_dedup.content_hash(
        {"question_text": "Câu hỏi mẫu", "options": [("A", "Đáp án A"), ("B", "Đáp án B")]}
    )
    b = import_dedup.content_hash(
        {"question_text": "Cau hoi mau", "options": [("A", "dap an a"), ("B", "dap an b")]}
    )
    assert a == b


def test_content_hash_changes_when_options_differ_meaningfully() -> None:
    """Genuine option-set edits must produce a different hash."""
    a = import_dedup.content_hash(
        {"question_text": "Q?", "options": [("A", "alpha"), ("B", "beta")]}
    )
    b = import_dedup.content_hash(
        {"question_text": "Q?", "options": [("A", "alpha"), ("B", "gamma")]}
    )
    assert a != b


# ---------------------------------------------------------------------------
# Bug 3 — XLSX header normalizer + graceful unmapped behaviour
# ---------------------------------------------------------------------------


def test_auto_map_unknown_headers_resolve_to_none_not_error() -> None:
    """Unknown headers map to None — they don't crash auto_map or fail rows.

    Required-field check is the gate; unknown columns are silently dropped at
    parse time so the row is still validated against whatever was mapped.
    """
    m = auto_map(["Question", "MyCustomColumnXYZ", "Correct"])
    assert m["Question"] == "question_text"
    assert m["Correct"] == "correct_answer"
    assert m["MyCustomColumnXYZ"] is None


def test_auto_map_uppercase_english_headers() -> None:
    """`QUESTION` / `CORRECT ANSWER` (unusual casing + spaces) map correctly."""
    m = auto_map(["QUESTION", "CORRECT ANSWER", "OPTION A", "OPTION B"])
    assert m["QUESTION"] == "question_text"
    assert m["CORRECT ANSWER"] == "correct_answer"
    assert m["OPTION A"] == "option_a"
    assert m["OPTION B"] == "option_b"


def test_auto_map_choice_and_answerkey_aliases() -> None:
    """`Choice A` and `Answer Key` resolve correctly."""
    m = auto_map(["Choice A", "Choice B", "Answer Key"])
    assert m["Choice A"] == "option_a"
    assert m["Choice B"] == "option_b"
    assert m["Answer Key"] == "correct_answer"
