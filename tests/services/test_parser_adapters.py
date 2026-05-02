"""Hermetic Milestone 1 tests — parser adapter contract + detector.

Covers:
  * detector picks XLSX for a real .xlsx (zip magic + filename)
  * detector picks ExamTopics HTML for a saved page with marker DOM
  * qblock_text parses QUESTION / options / Answer / Explanation
  * qblock_pdf delegates to the text extractor (monkeypatched)

NO network IO, NO DB.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from app.services.parsers import detect_adapter
from app.services.parsers.qblock_pdf_adapter import QBlockPdfAdapter
from app.services.parsers.qblock_text_adapter import parse_qblock_text

# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


def test_detect_adapter_picks_xlsx_for_real_xlsx(tmp_path: Path) -> None:
    """A real openpyxl-emitted .xlsx must be claimed by the XLSX adapter."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Question", "A", "B", "Correct"])
    ws.append(["What is 2+2?", "3", "4", "B"])
    path = tmp_path / "demo.xlsx"
    wb.save(str(path))

    adapter = detect_adapter(filename="demo.xlsx", file_path=path)

    assert adapter is not None
    assert adapter.name == "xlsx"
    assert adapter.priority == 80


def test_detect_adapter_picks_examtopics_for_html_with_markers(tmp_path: Path) -> None:
    """An HTML file with ExamTopics markers must be claimed by the HTML adapter."""
    html = (
        "<html><body>"
        "<div class='card-question' data-id='12345'>"
        "<div class='question-body'>What is the capital of France?</div>"
        "<ul><li>A. London</li><li>B. Paris</li><li>C. Berlin</li></ul>"
        "<div class='correct-answer'>Suggested Answer: B</div>"
        "<div class='voted-answers-tally'>A: 1 B: 42 C: 3</div>"
        "</div></body></html>"
    )
    path = tmp_path / "saved-page.html"
    path.write_text(html, encoding="utf-8")

    adapter = detect_adapter(filename="saved-page.html", file_path=path)

    assert adapter is not None
    assert adapter.name == "examtopics_html"


def test_detect_adapter_returns_none_for_unknown_format(tmp_path: Path) -> None:
    """An unrecognised file (.docx-ish bytes) gracefully returns None."""
    path = tmp_path / "mystery.bin"
    path.write_bytes(b"\x00\x01\x02not-a-known-format")
    assert detect_adapter(filename="mystery.bin", file_path=path) is None


# ---------------------------------------------------------------------------
# qblock_text adapter — pure parse function
# ---------------------------------------------------------------------------


def test_qblock_text_parses_full_block_shape() -> None:
    """A canonical QUESTION/A/B/Answer/Explanation block produces the expected row."""
    text = (
        "QUESTION 1\n"
        "Which AWS service stores objects?\n"
        "A. EC2\n"
        "B. S3\n"
        "C. Lambda\n"
        "D. RDS\n"
        "Answer: B\n"
        "Explanation:\n"
        "S3 is object storage.\n"
    )
    rows = list(parse_qblock_text(text, source_format="qblock_text", source_url="memory://t"))

    assert len(rows) == 1
    row = rows[0]
    assert row["question_text"] == "Which AWS service stores objects?"
    assert row["option_a"] == "EC2"
    assert row["option_b"] == "S3"
    assert row["option_c"] == "Lambda"
    assert row["option_d"] == "RDS"
    assert row["correct_answer"] == "B"
    assert "S3 is object storage." in row["explanation"]
    assert row["external_question_id"] == "Q0001"
    assert row["source_format"] == "qblock_text"
    assert row["source_url"] == "memory://t"


def test_qblock_text_parses_multiple_blocks() -> None:
    """Two back-to-back blocks emit two rows with sequential ids."""
    text = "QUESTION 1\nQ1?\nA. a\nB. b\nAnswer: A\nQUESTION 2\nQ2?\nA. x\nB. y\nAnswer: B\n"
    rows = list(parse_qblock_text(text))

    assert [r["external_question_id"] for r in rows] == ["Q0001", "Q0002"]
    assert rows[0]["correct_answer"] == "A"
    assert rows[1]["correct_answer"] == "B"


def test_qblock_text_skips_blocks_missing_options() -> None:
    """A block with no parseable options is silently dropped (best-effort)."""
    text = "QUESTION 1\nThis block has no options.\nAnswer: A\n"
    rows = list(parse_qblock_text(text))
    assert rows == []


# ---------------------------------------------------------------------------
# qblock_pdf adapter — delegates to text extraction
# ---------------------------------------------------------------------------


def test_qblock_pdf_delegates_to_text_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`QBlockPdfAdapter.parse()` must forward extracted text into the qblock parser.

    We don't actually render a PDF here — pdfminer's `extract_text` is
    monkeypatched to return a known string. This proves the adapter calls
    the same `parse_qblock_text` function the .txt path uses, so behaviour
    stays identical across the two delivery formats.
    """
    fake_pdf_text = "QUESTION 1\nPdf-extracted question?\nA. alpha\nB. beta\nAnswer: A\n"

    # pdfminer.high_level is imported lazily inside the adapter; patch the
    # attribute on the module the adapter imports from.
    import pdfminer.high_level as pdfminer_high

    monkeypatch.setattr(pdfminer_high, "extract_text", lambda _path: fake_pdf_text)

    # Filename + magic-bytes still need to be PDF-shaped for detect()/parse()
    # plausibility — write a PDF-magic stub file.
    stub = tmp_path / "exam-dump.pdf"
    stub.write_bytes(b"%PDF-1.4\n%%EOF\n")

    adapter = QBlockPdfAdapter()
    assert adapter.detect(filename="exam-dump.pdf", head_bytes=b"%PDF-1.4\n")

    rows = list(adapter.parse(file_path=stub))

    assert len(rows) == 1
    row = rows[0]
    assert row["question_text"] == "Pdf-extracted question?"
    assert row["option_a"] == "alpha"
    assert row["option_b"] == "beta"
    assert row["correct_answer"] == "A"
    assert row["source_format"] == "qblock_pdf"


# ---------------------------------------------------------------------------
# Golden-fixture tests (Milestone 1) — the 3 sample dumps the user provided.
# Files live in repo at `Template Dump/`. Tests are skipped when missing so
# the suite still runs in clean checkouts that don't ship the fixtures.
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "Template Dump"
_FIX_XLSX = _FIXTURE_DIR / "import_quiz_question_ccna_online.xlsx"
_FIX_HTML = _FIXTURE_DIR / "57q_efw.html"
_FIX_PDF = _FIXTURE_DIR / "646b6d2013bb103e361af8674630dcb6_2.pdf"


@pytest.mark.skipif(not _FIX_XLSX.exists(), reason="XLSX fixture missing")
def test_fixture_xlsx_detects_and_parses_vietnamese_dump() -> None:
    """The Vietnamese CCNA XLSX dump must (a) be claimed by the XLSX adapter,
    (b) auto-map the Vietnamese headers, and (c) yield ≥ 1 valid row whose
    `combined_options` splits into option_a..option_b at normalize time.
    """
    from app.services.excel_parser import auto_map, read_headers, stream_rows
    from app.services.import_normalizer import normalize_row
    from app.services.import_validator import validate_row
    from app.services.parsers import detect_adapter

    adapter = detect_adapter(filename=_FIX_XLSX.name, file_path=_FIX_XLSX)
    assert adapter is not None
    assert adapter.name == "xlsx"

    sheet, headers = read_headers(_FIX_XLSX)
    mapping = auto_map(headers)
    # The Vietnamese alias map should at minimum cover question_text,
    # combined_options, and correct_answer.
    mapped_targets = {v for v in mapping.values() if v}
    assert "question_text" in mapped_targets
    assert "correct_answer" in mapped_targets
    assert "combined_options" in mapped_targets

    rows = list(stream_rows(_FIX_XLSX, column_mapping=mapping, max_rows=1000))
    assert len(rows) >= 1, "XLSX fixture must contain at least one data row"

    # Spot-check: normalize the first row → combined_options splits → validator OK.
    first = normalize_row(rows[0].raw)
    assert first.get("option_a"), "combined_options should split into option_a"
    assert first.get("option_b"), "combined_options should split into option_b"
    result = validate_row(first)
    # The fixture's first row should validate as ok or warning (not error) —
    # numeric correct_answer "1" must resolve to option label "A".
    assert result.canonical.get("correct_answer") == ["A"], (
        f"expected numeric '1' to normalise to ['A'], got "
        f"{result.canonical.get('correct_answer')!r}; errors={result.error_message!r}"
    )


@pytest.mark.skipif(not _FIX_HTML.exists(), reason="HTML fixture missing")
def test_fixture_html_detects_and_parses_examtopics_dump() -> None:
    """The saved ExamTopics HTML dump must yield 57 question rows with
    options and a correct_answer extracted from the embedded JSON tally.
    """
    from app.services.parsers import detect_adapter
    from app.services.parsers.examtopics_html_adapter import ExamTopicsHtmlAdapter

    adapter = detect_adapter(filename=_FIX_HTML.name, file_path=_FIX_HTML)
    assert adapter is not None
    assert adapter.name == "examtopics_html"

    rows = list(ExamTopicsHtmlAdapter().parse(file_path=_FIX_HTML))
    assert len(rows) == 57, f"expected 57 questions, got {len(rows)}"

    # Every row should have at least 2 options + a correct_answer parsed
    # from the voted-answers-tally JSON — that's the whole point of the
    # adapter, not a "best effort".
    rows_with_two_opts = sum(1 for r in rows if r.get("option_a") and r.get("option_b"))
    rows_with_answer = sum(1 for r in rows if r.get("correct_answer"))
    assert rows_with_two_opts == 57
    assert rows_with_answer == 57

    # First row spot-check.
    first = rows[0]
    assert first.get("source_format") == "examtopics_html"
    assert first.get("external_question_id"), "data-id should be captured"
    # Option text must NOT carry the "Most Voted" badge string.
    assert "Most Voted" not in (first.get("option_a") or "")


@pytest.mark.skipif(not _FIX_PDF.exists(), reason="PDF fixture missing")
def test_fixture_pdf_detects_and_parses_qblock_dump() -> None:
    """The PassLeader-style PDF dump must be claimed by `qblock_pdf` and
    yield 166 QUESTION blocks with options A/B/C/D and an Answer letter.
    """
    from app.services.parsers import detect_adapter
    from app.services.parsers.qblock_pdf_adapter import QBlockPdfAdapter

    adapter = detect_adapter(filename=_FIX_PDF.name, file_path=_FIX_PDF)
    assert adapter is not None
    assert adapter.name == "qblock_pdf"

    rows = list(QBlockPdfAdapter().parse(file_path=_FIX_PDF))
    assert len(rows) == 166, f"expected 166 questions, got {len(rows)}"

    rows_with_four_opts = sum(
        1
        for r in rows
        if r.get("option_a") and r.get("option_b") and r.get("option_c") and r.get("option_d")
    )
    rows_with_answer = sum(1 for r in rows if r.get("correct_answer"))
    rows_with_explanation = sum(1 for r in rows if r.get("explanation"))
    # Most rows have all 4 options + an answer + explanation. Allow a
    # small tolerance for tail-of-file partial blocks but require ≥ 95 %.
    assert rows_with_four_opts >= int(len(rows) * 0.95)
    assert rows_with_answer >= int(len(rows) * 0.95)
    assert rows_with_explanation >= int(len(rows) * 0.90)

    first = rows[0]
    assert first.get("source_format") == "qblock_pdf"
    assert first.get("external_question_id") == "Q0001"
