"""Plain-text dump parser for the `QUESTION N` block format.

Recognises files like:

    QUESTION 1
    Which AWS service ...?
    A. EC2
    B. S3
    C. Lambda
    D. RDS
    Answer: B
    Explanation:
    S3 is object storage, used for ...

One file may contain many `QUESTION N` blocks back-to-back. Page
headers/footers/watermarks (any line that recurs across blocks at the same
relative position) are best-effort suppressed by ignoring lines that are
shorter than 4 chars and look like page numbers `^\\d+$`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.services.parsers.base import ParsedQuestion

NAME = "qblock_text"
PRIORITY = 50

_QUESTION_HEAD_RE = re.compile(r"^\s*QUESTION\s+(\d+)\b", re.IGNORECASE)
_OPTION_LINE_RE = re.compile(r"^\s*([A-Fa-f])[\.\)\:\-]\s*(.+?)\s*$")
_ANSWER_RE = re.compile(r"^\s*Answer\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)
_EXPLANATION_RE = re.compile(
    r"^\s*(?:Explanation|Reason|Rationale)\s*[:\-]?\s*(.*)$", re.IGNORECASE
)
_PAGE_NUM_RE = re.compile(r"^\s*\d{1,4}\s*$")


class QBlockTextAdapter:
    name = NAME
    priority = PRIORITY

    def detect(self, *, filename: str, head_bytes: bytes) -> bool:
        if not (filename.lower().endswith(".txt") or filename.lower().endswith(".text")):
            return False
        try:
            text = head_bytes.decode("utf-8", errors="replace")
        except Exception:
            return False
        return bool(_QUESTION_HEAD_RE.search(text))

    def parse(
        self,
        *,
        file_path: Path,
        column_mapping: dict[str, str | None] | None = None,
    ) -> Iterator[ParsedQuestion]:
        text = Path(file_path).read_text(encoding="utf-8", errors="replace")
        yield from parse_qblock_text(text, source_format=self.name, source_url=str(file_path))


def parse_qblock_text(
    text: str,
    *,
    source_format: str = "qblock_text",
    source_url: str | None = None,
) -> Iterator[ParsedQuestion]:
    """Pure-function parser. Used directly by tests + the PDF adapter."""
    blocks = _split_into_blocks(text)
    for block_num, lines in blocks:
        row = _block_to_row(lines)
        if row is None:
            continue
        row["external_question_id"] = f"Q{block_num:04d}"
        row["source_format"] = source_format
        if source_url:
            row["source_url"] = source_url
        yield row


def _split_into_blocks(text: str) -> list[tuple[int, list[str]]]:
    out: list[tuple[int, list[str]]] = []
    current: list[str] | None = None
    current_num: int | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        # Skip obvious page-number lines.
        if _PAGE_NUM_RE.match(line):
            continue
        m = _QUESTION_HEAD_RE.match(line)
        if m:
            if current is not None and current_num is not None:
                out.append((current_num, current))
            current = []
            current_num = int(m.group(1))
            continue
        if current is not None:
            current.append(line)
    if current is not None and current_num is not None:
        out.append((current_num, current))
    return out


def _block_to_row(lines: list[str]) -> ParsedQuestion | None:
    """Convert one block's body lines into a canonical row dict."""
    question_lines: list[str] = []
    options: dict[str, str] = {}
    answer: str | None = None
    explanation_lines: list[str] = []
    state = "question"

    for line in lines:
        s = line.strip()
        if not s:
            continue
        m_opt = _OPTION_LINE_RE.match(s)
        m_ans = _ANSWER_RE.match(s)
        m_exp = _EXPLANATION_RE.match(s)
        if m_opt:
            label = m_opt.group(1).upper()
            options[label] = m_opt.group(2).strip()
            state = "options"
            continue
        if m_ans:
            answer = m_ans.group(1).strip()
            state = "answer"
            continue
        if m_exp:
            tail = m_exp.group(1).strip()
            if tail:
                explanation_lines.append(tail)
            state = "explanation"
            continue
        if state == "question":
            question_lines.append(s)
        elif state in ("answer", "explanation"):
            explanation_lines.append(s)
        elif state == "options" and options:
            # Continuation of last option (long answer wrapped).
            last_label = list(options.keys())[-1]
            options[last_label] = (options[last_label] + " " + s).strip()

    if not question_lines or not options:
        return None
    row: dict[str, Any] = {
        "question_text": " ".join(question_lines).strip(),
    }
    for label, text in options.items():
        row[f"option_{label.lower()}"] = text
    if answer:
        row["correct_answer"] = answer
    if explanation_lines:
        row["explanation"] = "\n".join(explanation_lines).strip()
    return row
