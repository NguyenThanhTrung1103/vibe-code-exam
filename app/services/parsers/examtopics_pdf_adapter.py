"""ExamTopics PDF dump parser.

Targets PDFs whose body uses the ExamTopics layout (distinct from the
QBLOCK-style PassLeader dumps already handled by `qblock_pdf_adapter`):

    Question #1                            Topic 1
    <question text — may wrap across several lines>

    A. <option a — may wrap>
    B. <option b>
    C. <option c>
    D. <option d>

      Correct Answer: B
      Selected Answer: B
      Community vote distribution
      B (89%) Other (11%)

Differences vs. the QBLOCK shape:
  * Heading is `Question #N` (with optional `Topic M` trailer), not
    `QUESTION N`.
  * Answer marker is `Correct Answer:` (multi-letter rows allowed, e.g.
    `BD`), not `Answer:`.
  * Per-option community votes are surfaced via a `Community vote
    distribution` block — same data the HTML adapter pulls from
    `.voted-answers-tally`.

Detection is a two-step gate: filename hint OR a 1-page text sniff. The
sniff is required because PDFs zlib-encode their content streams, so
substring-matching the head bytes won't work.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from app.services.parsers.base import ParsedQuestion

NAME = "examtopics_pdf"
# Higher than examtopics_html (70) and qblock_pdf (60) so this adapter wins
# whenever an ExamTopics PDF lands on disk; non-ExamTopics PDFs still fall
# through to qblock_pdf via the priority-ordered registry.
PRIORITY = 80

# `Question #1` heading. Optional `Topic N` trailer is captured but unused
# downstream — kept in the regex so it's clearly part of the contract.
_Q_HEAD_RE = re.compile(
    r"^\s*Question\s*#\s*(\d+)\b.*?(?:Topic\s*(\d+))?\s*$",
    re.IGNORECASE,
)
_OPTION_HEAD_RE = re.compile(r"^\s*([A-H])[.\)\:\-]\s*(.+?)\s*$")
_CORRECT_ANSWER_RE = re.compile(
    r"^\s*Correct\s+Answer\s*[:\-]\s*([A-H]+)\s*$", re.IGNORECASE
)
_VOTE_LINE_RE = re.compile(r"\b([A-H])\s*\(\s*(\d+)\s*%\s*\)", re.IGNORECASE)

# Lines we want to skip wholesale inside a question body. Anything that
# would otherwise pollute `question_text` or `option_x` if greedily appended.
_NOISE_LINE_RES: tuple[re.Pattern, ...] = (
    re.compile(r"^\s*Selected\s+Answer\s*[:\-]", re.IGNORECASE),
    re.compile(r"^\s*Community\s+vote\s+distribution\b", re.IGNORECASE),
    re.compile(r"^\s*upvoted\s+\d+\s+times?\b", re.IGNORECASE),
    re.compile(r"^\s*Most\s+Voted\b", re.IGNORECASE),
    re.compile(r"^\s*Reveal\s+Solution\b", re.IGNORECASE),
    re.compile(r"^\s*Hide\s+Answer\b", re.IGNORECASE),
    # Page numbers / trailing pagination noise.
    re.compile(r"^\s*\d{1,4}\s*$"),
)

# Keywords that anchor the start of the post-options metadata block. When
# we hit one of these, option-text accumulation stops — so a multi-line
# option `D` doesn't swallow the answer or vote lines.
_METADATA_HEAD_RES: tuple[re.Pattern, ...] = (
    _CORRECT_ANSWER_RE,
    re.compile(r"^\s*Selected\s+Answer\s*[:\-]", re.IGNORECASE),
    re.compile(r"^\s*Community\s+vote\s+distribution\b", re.IGNORECASE),
)


class ExamTopicsPdfAdapter:
    name = NAME
    priority = PRIORITY

    def detect(self, *, filename: str, head_bytes: bytes) -> bool:
        """Bytes-only detect. Honours the registry's standard signature.

        Only the filename heuristic is reachable from this entry point —
        PDF content streams are zlib-encoded so substring-matching the
        first 4 KB of bytes can't see `Question #` markers. The
        path-aware content sniff lives in `detect_examtopics_pdf` and is
        called by `detector.detect_adapter` as a fallback before the
        generic `qblock_pdf` adapter wins.
        """
        if not filename.lower().endswith(".pdf"):
            return False
        if not head_bytes.startswith(b"%PDF-"):
            return False
        return "examtopics" in filename.lower()

    def parse(
        self,
        *,
        file_path: Path,
        column_mapping: dict[str, str | None] | None = None,
    ) -> Iterator[ParsedQuestion]:
        try:
            from pdfminer.high_level import extract_text  # noqa: PLC0415
        except Exception as exc:  # pragma: no cover — dep missing
            raise RuntimeError(
                "pdfminer.six is required for PDF parsing. "
                "Install with `uv add pdfminer.six` and redeploy."
            ) from exc
        text = extract_text(str(file_path)) or ""
        yield from parse_examtopics_pdf_text(
            text, source_format=self.name, source_url=str(file_path)
        )


def detect_examtopics_pdf(*, filename: str, file_path: Path) -> bool:
    """Path-aware detection used by the registry when bytes-only signals
    are inconclusive.

    Two-step gate: filename hint OR 1-page content sniff for `Question #N`
    + `Correct Answer:` markers.
    """
    name_lower = filename.lower()
    if not name_lower.endswith(".pdf"):
        return False
    try:
        with open(file_path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return False
    if not head.startswith(b"%PDF-"):
        return False
    if "examtopics" in name_lower:
        return True
    try:
        from pdfminer.high_level import extract_text  # noqa: PLC0415
    except Exception:
        return False
    try:
        sniff = extract_text(str(file_path), maxpages=2) or ""
    except Exception:
        return False
    has_q_head = bool(re.search(r"^\s*Question\s*#\s*\d+", sniff, re.MULTILINE))
    has_correct = bool(
        re.search(r"^\s*Correct\s+Answer\s*[:\-]", sniff, re.MULTILINE | re.IGNORECASE)
    )
    return has_q_head and has_correct


def parse_examtopics_pdf_text(
    text: str,
    *,
    source_format: str = NAME,
    source_url: str | None = None,
) -> Iterator[ParsedQuestion]:
    """Pure-function parser. Tested directly without spinning up pdfminer.

    Walks the extracted text line-by-line, splitting on each `Question #N`
    heading. Within each block:
      1. Lines after the heading and before the first `^[A-H][.\\)\\:\\-]`
         marker are joined into `question_text`.
      2. Each option marker starts a new option; subsequent non-marker,
         non-noise, non-metadata lines append to the current option's text.
      3. The metadata gate (`Correct Answer:`, `Selected Answer:`,
         `Community vote distribution`) ends option accumulation.
      4. The next non-empty line after `Community vote distribution` is
         scanned for `B (89%)`-style tokens to populate `vote_a..vote_h` +
         `discussion_count`.
    """
    blocks = _split_into_blocks(text)
    for block_num, lines in blocks:
        row = _block_to_row(lines)
        if row is None:
            continue
        row["external_question_id"] = f"ET-PDF-{block_num:04d}"
        row["source_format"] = source_format
        if source_url:
            row["source_url"] = source_url
        yield row


def _split_into_blocks(text: str) -> list[tuple[int, list[str]]]:
    """Slice raw text into `(question_number, block_lines)` chunks.

    Discards anything before the first `Question #N` line (cover page,
    table of contents, marketing fluff). Lines between heading N and
    heading N+1 belong to block N — including blank lines, which we keep
    as separators inside the block.
    """
    out: list[tuple[int, list[str]]] = []
    current_num: int | None = None
    current_lines: list[str] = []
    for raw in text.splitlines():
        m = _Q_HEAD_RE.match(raw)
        if m and m.group(1):
            if current_num is not None:
                out.append((current_num, current_lines))
            current_num = int(m.group(1))
            current_lines = []
        elif current_num is not None:
            current_lines.append(raw)
    if current_num is not None:
        out.append((current_num, current_lines))
    return out


def _is_noise(line: str) -> bool:
    return any(rx.match(line) for rx in _NOISE_LINE_RES)


def _is_metadata_head(line: str) -> bool:
    return any(rx.match(line) for rx in _METADATA_HEAD_RES)


def _block_to_row(lines: list[str]) -> ParsedQuestion | None:
    """Convert one Question #N's worth of lines into a canonical row."""
    question_lines: list[str] = []
    options: dict[str, list[str]] = {}
    correct: str | None = None
    votes: dict[str, int] = {}

    state = "question"  # question | options | metadata
    current_option: str | None = None
    saw_vote_header = False

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            # Blank line ends the current option; doesn't switch state on its own.
            current_option = None
            continue
        if _is_noise(line) and state != "metadata":
            # Pre-metadata noise (rare here) — skip.
            continue

        # Metadata gate: short-circuits regardless of current state.
        if _is_metadata_head(line):
            state = "metadata"
            current_option = None
            ans_match = _CORRECT_ANSWER_RE.match(line)
            if ans_match and not correct:
                correct = ans_match.group(1).upper()
            continue

        if state == "metadata":
            ans_match = _CORRECT_ANSWER_RE.match(line)
            if ans_match and not correct:
                correct = ans_match.group(1).upper()
                continue
            # Vote distribution lines: collect every `X (NN%)` token.
            for letter, pct in _VOTE_LINE_RE.findall(line):
                votes[letter.upper()] = int(pct)
                saw_vote_header = True
            continue

        opt_match = _OPTION_HEAD_RE.match(line)
        if opt_match:
            state = "options"
            current_option = opt_match.group(1).upper()
            options.setdefault(current_option, []).append(opt_match.group(2).strip())
            continue

        if state == "question":
            question_lines.append(line.strip())
        elif state == "options" and current_option is not None:
            # Option text wrapped onto a continuation line.
            options[current_option].append(line.strip())

    question_text = " ".join(s for s in question_lines if s).strip()
    if not question_text or not options:
        return None

    row: ParsedQuestion = {"question_text": question_text}
    for letter, parts in options.items():
        row[f"option_{letter.lower()}"] = " ".join(p for p in parts if p).strip()
    if correct:
        row["correct_answer"] = correct
    if votes:
        for letter, pct in votes.items():
            row[f"vote_{letter.lower()}"] = pct
        row["discussion_count"] = sum(votes.values())
    # `saw_vote_header` is only useful as a debug breadcrumb; the row is
    # complete either way. Suppress the unused-var lint without noise.
    _ = saw_vote_header
    return row


__all__ = [
    "ExamTopicsPdfAdapter",
    "detect_examtopics_pdf",
    "parse_examtopics_pdf_text",
]
