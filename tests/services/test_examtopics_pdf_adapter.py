"""Unit tests for the ExamTopics PDF adapter.

Pure-function tests against `parse_examtopics_pdf_text` using the
contract from the user-supplied mock fixture (no pdfminer in the loop).
A separate test exercises the registry / detector promotion path.
"""

from __future__ import annotations

from pathlib import Path

from app.services.parsers.detector import detect_adapter
from app.services.parsers.examtopics_pdf_adapter import (
    ExamTopicsPdfAdapter,
    parse_examtopics_pdf_text,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MOCK_TEXT = """Question #1                                              Topic 1
A company needs to store data that will be accessed frequently.
Which AWS service should they use?

A. Amazon S3 Glacier
B. Amazon S3 Standard
C. AWS Snowball
D. Amazon EBS Cold HDD

  Correct Answer: B
  Selected Answer: B
  Community vote distribution
  B (89%) Other (11%)

Question #2                                              Topic 1
A solutions architect is designing a solution that requires...

A. Option one text
B. Option two text
C. Option three text
D. Option four text

  Correct Answer: AC
"""


_MIN_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"  # signature only — never parsed by detect()


# ---------------------------------------------------------------------------
# Pure-function parser
# ---------------------------------------------------------------------------


def test_parses_two_questions_from_mock_fixture() -> None:
    rows = list(parse_examtopics_pdf_text(_MOCK_TEXT))
    assert len(rows) == 2


def test_first_question_canonical_fields() -> None:
    rows = list(parse_examtopics_pdf_text(_MOCK_TEXT))
    q1 = rows[0]
    assert q1["question_text"].startswith("A company needs to store data")
    assert q1["question_text"].endswith("Which AWS service should they use?")
    assert q1["option_a"] == "Amazon S3 Glacier"
    assert q1["option_b"] == "Amazon S3 Standard"
    assert q1["option_c"] == "AWS Snowball"
    assert q1["option_d"] == "Amazon EBS Cold HDD"
    assert q1["correct_answer"] == "B"
    assert q1["external_question_id"] == "ET-PDF-0001"
    assert q1["source_format"] == "examtopics_pdf"


def test_first_question_captures_vote_distribution() -> None:
    rows = list(parse_examtopics_pdf_text(_MOCK_TEXT))
    q1 = rows[0]
    # `B (89%)` is captured. `Other (11%)` is not a letter so it's skipped.
    assert q1.get("vote_b") == 89
    assert q1.get("discussion_count") == 89


def test_multi_letter_answer_is_preserved() -> None:
    rows = list(parse_examtopics_pdf_text(_MOCK_TEXT))
    q2 = rows[1]
    assert q2["correct_answer"] == "AC"
    # Q2 has no Community vote distribution → no vote keys.
    assert "vote_a" not in q2
    assert "discussion_count" not in q2


def test_question_text_joins_multiline_body() -> None:
    rows = list(parse_examtopics_pdf_text(_MOCK_TEXT))
    # The Q1 body spans two lines in the fixture; the parser must join them
    # with a single space so downstream gets a clean sentence.
    assert "Which AWS service should they use?" in rows[0]["question_text"]
    assert "  " not in rows[0]["question_text"]  # no double-spaces


def test_option_text_continues_onto_wrapped_lines() -> None:
    """Option text wrapped onto a continuation line stays attached to its option."""
    text = (
        "Question #5\n"
        "Pick the best option.\n"
        "\n"
        "A. The first option text that wraps\n"
        "   onto a second line for realism\n"
        "B. Short option B\n"
        "\n"
        "  Correct Answer: A\n"
    )
    rows = list(parse_examtopics_pdf_text(text))
    assert len(rows) == 1
    assert (
        rows[0]["option_a"]
        == "The first option text that wraps onto a second line for realism"
    )
    assert rows[0]["option_b"] == "Short option B"
    assert rows[0]["correct_answer"] == "A"


def test_source_url_is_preserved_when_supplied() -> None:
    rows = list(parse_examtopics_pdf_text(_MOCK_TEXT, source_url="/srv/dump.pdf"))
    assert rows[0]["source_url"] == "/srv/dump.pdf"


def test_block_without_options_is_skipped() -> None:
    """A `Question #N` heading with no A./B. lines must not yield a row."""
    text = "Question #1 Topic 1\nThis question never finished.\n\n  Correct Answer: A\n"
    rows = list(parse_examtopics_pdf_text(text))
    assert rows == []


def test_text_before_first_question_heading_is_discarded() -> None:
    """Cover pages / TOCs must not pollute the first question's body."""
    text = (
        "Vendor: Amazon\n"
        "Exam: SAA-C03\n"
        "Important Notice — please read.\n"
        "\n"
        "Question #1 Topic 1\n"
        "Real question text.\n"
        "\n"
        "A. opt a\n"
        "B. opt b\n"
        "\n"
        "  Correct Answer: A\n"
    )
    rows = list(parse_examtopics_pdf_text(text))
    assert len(rows) == 1
    assert rows[0]["question_text"] == "Real question text."


# ---------------------------------------------------------------------------
# Adapter / detector
# ---------------------------------------------------------------------------


def test_adapter_detect_filename_hint_only() -> None:
    a = ExamTopicsPdfAdapter()
    assert a.detect(filename="SAA-C03_ExamTopics_Updated.pdf", head_bytes=_MIN_PDF) is True
    # Mixed case should still match.
    assert a.detect(filename="DUMP-EXAMTOPICS.pdf", head_bytes=_MIN_PDF) is True
    # Non-PDF extension → no claim.
    assert a.detect(filename="dump-examtopics.html", head_bytes=_MIN_PDF) is False
    # PDF without filename hint → defers to the path-aware sniff in
    # `detect_adapter`; the bytes-only `detect()` returns False.
    assert a.detect(filename="random_dump.pdf", head_bytes=_MIN_PDF) is False
    # Non-PDF magic → no claim even with the right name.
    assert a.detect(filename="examtopics.pdf", head_bytes=b"PK\x03\x04") is False


def test_detector_picks_examtopics_pdf_for_examtopics_named_files(tmp_path: Path) -> None:
    """A PDF whose basename contains `examtopics` must be claimed by this adapter."""
    p = tmp_path / "SAA-C03_ExamTopics_Updated.pdf"
    p.write_bytes(_MIN_PDF + b"\nrest of file is irrelevant for filename match\n")
    chosen = detect_adapter(filename=p.name, file_path=p)
    assert chosen is not None
    assert chosen.name == "examtopics_pdf"


def test_detector_keeps_qblock_pdf_for_unrelated_pdfs(tmp_path: Path) -> None:
    """Generic PDFs with no ExamTopics signal must still go to qblock_pdf."""
    p = tmp_path / "random_dump.pdf"
    # Minimal `%PDF-` magic + body; pdfminer extract_text may yield "" — the
    # examtopics content sniff then returns False and qblock_pdf wins.
    p.write_bytes(_MIN_PDF + b"\n1 0 obj\n<< /Type /Catalog >>\nendobj\n")
    chosen = detect_adapter(filename=p.name, file_path=p)
    assert chosen is not None
    assert chosen.name == "qblock_pdf"
