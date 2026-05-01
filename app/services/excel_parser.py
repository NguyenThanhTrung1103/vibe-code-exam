"""Phase 05 — read-only streaming Excel parser.

Uses openpyxl `read_only=True, data_only=True` so cells are values not
formulas, and rows are streamed (no full-workbook in RAM).

Caller passes a workbook path + the column mapping
(`header_label -> canonical_field`). We yield one dict per data row.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

# Canonical fields the rest of the pipeline understands.
CANONICAL_FIELDS = (
    "question_text",
    "question_type",
    "difficulty",
    "topic",
    "option_a",
    "option_b",
    "option_c",
    "option_d",
    "option_e",
    "correct_answer",
    "explanation",
    "reference",
    "tags",
)
REQUIRED_FIELDS = ("question_text", "option_a", "option_b", "correct_answer")
MAX_COLUMNS = 32  # safety cap — too-wide sheet → reject.


# Common header alias map for auto-mapping.
_ALIAS = {
    "question": "question_text",
    "questiontext": "question_text",
    "q": "question_text",
    "type": "question_type",
    "questiontype": "question_type",
    "level": "difficulty",
    "difficulty": "difficulty",
    "topic": "topic",
    "topics": "topic",
    "a": "option_a",
    "optiona": "option_a",
    "b": "option_b",
    "optionb": "option_b",
    "c": "option_c",
    "optionc": "option_c",
    "d": "option_d",
    "optiond": "option_d",
    "e": "option_e",
    "optione": "option_e",
    "correct": "correct_answer",
    "correctanswer": "correct_answer",
    "answer": "correct_answer",
    "explanation": "explanation",
    "rationale": "explanation",
    "reference": "reference",
    "url": "reference",
    "ref": "reference",
    "tags": "tags",
}


@dataclass(slots=True)
class ParsedRow:
    sheet_name: str
    row_number: int  # 1-based, matches Excel row number
    raw: dict[str, Any]


def auto_map(headers: list[str]) -> dict[str, str | None]:
    """Best-effort header → canonical mapping. Unknown headers map to None."""
    out: dict[str, str | None] = {}
    for h in headers:
        if not h:
            continue
        key = _normalize_header(h)
        out[h] = _ALIAS.get(key)
    return out


def _normalize_header(label: str) -> str:
    return "".join(ch for ch in label.lower() if ch.isalnum())


def read_headers(path: Path | str) -> tuple[str, list[str]]:
    """Open workbook, return `(sheet_name, header_row_values)`.

    Reads only the first sheet's first row.
    """
    wb = load_workbook(filename=str(path), read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        headers: list[str] = []
        for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
            for cell in row:
                headers.append("" if cell is None else str(cell).strip())
            break
        if len(headers) > MAX_COLUMNS:
            raise ValueError(f"too many columns ({len(headers)} > {MAX_COLUMNS})")
        return ws.title, headers
    finally:
        wb.close()


def stream_rows(
    path: Path | str,
    *,
    column_mapping: dict[str, str | None],
    max_rows: int,
) -> Iterator[ParsedRow]:
    """Yield one `ParsedRow` per non-empty data row.

    `column_mapping` keys are the workbook's *header labels*; values are the
    canonical field names (or None to skip the column).

    Stops + raises `ValueError` if more than `max_rows` data rows are seen.
    Empty rows (all cells None) are skipped silently.
    """
    wb = load_workbook(filename=str(path), read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        sheet = ws.title
        header_row: list[str] = []
        seen_data = 0
        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if row_idx == 1:
                header_row = ["" if c is None else str(c).strip() for c in row]
                continue
            if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
                continue
            seen_data += 1
            if seen_data > max_rows:
                raise ValueError(f"too many data rows (>{max_rows})")
            raw: dict[str, Any] = {}
            for header, value in zip(header_row, row, strict=False):
                canonical = column_mapping.get(header) if header else None
                if not canonical:
                    continue
                raw[canonical] = value
            if not raw:
                continue
            yield ParsedRow(sheet_name=sheet, row_number=row_idx, raw=raw)
    finally:
        wb.close()
