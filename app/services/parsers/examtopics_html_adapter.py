"""Uploaded-HTML dump parser (ExamTopics-like).

Best-effort extraction from a SAVED HTML page. We DO NOT fetch from the
internet. The admin uploads a file (e.g. saved via "Page → Save As Web
Page, complete") and this adapter walks the DOM looking for repeating
question blocks with options + (sometimes) answer/explanation/votes.

Selector heuristics live here; community_dump_parser.py covers a pinned
contract for a single ExamTopics question page (Phase 13). This adapter
is the file-level wrapper that emits one canonical row per question.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.services.parsers.base import ParsedQuestion

NAME = "examtopics_html"
PRIORITY = 70

# Markers we look for in the head bytes to claim a file as ExamTopics-style.
_ET_HEAD_HINTS = (
    b"question-body",
    b"voted-answers-tally",
    b"data-id=",
    b"discussion-count",
    b"examtopics",
    b"multi-choice-item",
)

# Regex fallbacks for files where the DOM doesn't quite match the pinned
# selectors but still follows the recognizable pattern.
_OPTION_LI_RE = re.compile(r"^\s*([A-Fa-f])[\.\)\:\-]\s*(.+?)\s*$", re.DOTALL)
_VOTE_LETTER_RE = re.compile(r"\b([A-Fa-f])\b\s*[:\-]?\s*(\d+)")
# Badge/notice text appended inside option <li>s (e.g. "Most Voted").
_OPTION_BADGE_NOISE_RE = re.compile(
    r"\s*(?:Most Voted|Correct Answer|Reveal Solution)\s*$",
    re.IGNORECASE,
)


class ExamTopicsHtmlAdapter:
    name = NAME
    priority = PRIORITY

    def detect(self, *, filename: str, head_bytes: bytes) -> bool:
        if not (filename.lower().endswith(".html") or filename.lower().endswith(".htm")):
            return False
        head_lower = head_bytes.lower()
        return any(hint in head_lower for hint in _ET_HEAD_HINTS)

    def parse(
        self,
        *,
        file_path: Path,
        column_mapping: dict[str, str | None] | None = None,
    ) -> Iterator[ParsedQuestion]:
        html = Path(file_path).read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        # Saved pages preserve a <base href="..."> the browser used as the
        # link-resolution root. Use it to absolutize relative discussion URLs
        # so the community-URL validator stops rejecting them as
        # `scheme_not_allowed`.
        base_el = soup.find("base", href=True)
        base_href = base_el["href"] if base_el and base_el.get("href") else ""
        # Each question is typically wrapped in a card. Try several common shapes.
        candidates = (
            soup.select(".question-discussion-header, .card.question, .question-body")
            or soup.select("[data-id]")
            or soup.select("article")
        )
        seen_ids: set[str] = set()
        for idx, block in enumerate(candidates, start=1):
            row = _block_to_row(block, fallback_index=idx)
            if row is None:
                continue
            ext_id = row.get("external_question_id")
            if ext_id in seen_ids:
                continue
            if ext_id:
                seen_ids.add(ext_id)
            row["source_format"] = self.name
            row["source_url"] = str(file_path)
            disc = row.get("discussion_url")
            if disc and base_href and not disc.startswith(("http://", "https://")):
                row["discussion_url"] = urljoin(base_href, disc)
            yield row


def _block_to_row(block, fallback_index: int) -> ParsedQuestion | None:
    # Question text — prefer .card-text (the inner paragraph) over
    # .question-body (which IS the wrapper on saved ExamTopics pages and
    # would pull in the option text via get_text()).
    body_el = (
        block.select_one(".card-text") or block.select_one(".question-body") or block.find("p")
    )
    question_text = body_el.get_text(" ", strip=True) if body_el else ""
    if not question_text:
        return None

    # Options — list items inside the block, or paragraphs starting with A./B.
    options: dict[str, str] = _extract_options(block)

    # Answer + votes — saved ExamTopics pages stash both as JSON inside
    # `.voted-answers-tally script`. Plain-text fallbacks below cover the
    # legacy .correct-answer / .reveal-solution shapes.
    vote_block = block.select_one(".voted-answers-tally")
    votes, answer_from_json = _extract_votes_and_answer(vote_block)

    answer: str | None = answer_from_json
    if not answer:
        answer_el = block.select_one(".correct-answer, .reveal-solution, .question-answer")
        if answer_el:
            text = answer_el.get_text(" ", strip=True)
            m = re.search(r"\b([A-F]+)\b", text.upper())
            if m:
                answer = m.group(1)

    # Explanation — best-effort.
    expl_el = block.select_one(".question-explanation, .answer-description, .explanation")
    explanation = expl_el.get_text("\n", strip=True) if expl_el else None

    # Discussion link + external id.
    disc_a = block.select_one("a[href*='/discussions/']")
    discussion_url = disc_a["href"] if disc_a and disc_a.has_attr("href") else None
    ext_id = block.get("data-id") if block.has_attr("data-id") else None

    if not options:
        return None
    row: ParsedQuestion = {"question_text": question_text}
    for label, text in options.items():
        row[f"option_{label.lower()}"] = text
    if answer:
        row["correct_answer"] = answer
    if explanation:
        row["explanation"] = explanation
    if discussion_url:
        row["discussion_url"] = discussion_url
    if ext_id:
        row["external_question_id"] = str(ext_id)
    else:
        row["external_question_id"] = f"ET-{fallback_index:04d}"
    for letter, count in votes.items():
        row[f"vote_{letter.lower()}"] = count
    if votes:
        row["discussion_count"] = sum(votes.values())
    return row


def _extract_options(block) -> dict[str, str]:
    """Return `{letter: text}` for the options inside a question block.

    Handles both the modern saved-page shape (where each `<li
    class="multi-choice-item">` carries a `<span class="multi-choice-letter"
    data-choice-letter="A">A.</span>` plus raw option text) and the legacy
    `<li>A. text</li>` shape via the regex fallback.
    """
    options: dict[str, str] = {}
    items = block.select(
        "ul li.multi-choice-item, ol li.multi-choice-item, ul li, ol li, .question-choices li"
    )
    for li in items:
        letter_el = li.select_one("[data-choice-letter]")
        letter = (letter_el.get("data-choice-letter", "") if letter_el is not None else "").upper()
        if letter and letter in "ABCDEF":
            # Strip the leading letter span + any trailing badge spans
            # (e.g. "Most Voted") so we keep just the option text.
            text = li.get_text(" ", strip=True)
            text = re.sub(r"^\s*[A-Fa-f]\s*[\.\)\:\-]\s*", "", text)
            text = _OPTION_BADGE_NOISE_RE.sub("", text).strip()
            if text:
                options[letter] = text
                continue
        # Regex fallback for the legacy shape.
        m = _OPTION_LI_RE.match(li.get_text(" ", strip=True))
        if m:
            text = _OPTION_BADGE_NOISE_RE.sub("", m.group(2).strip()).strip()
            options[m.group(1).upper()] = text
    if not options:
        # Paragraph fallback.
        for p in block.find_all("p"):
            m = _OPTION_LI_RE.match(p.get_text(" ", strip=True))
            if m:
                text = _OPTION_BADGE_NOISE_RE.sub("", m.group(2).strip()).strip()
                options[m.group(1).upper()] = text
    return options


def _extract_votes_and_answer(vote_block) -> tuple[dict[str, int], str | None]:
    """Pull the JSON payload off `.voted-answers-tally script` if present.

    Returns `(votes_by_letter, most_voted_answer_or_None)`. Falls back to
    the plain-text regex sniffer when no JSON is found.
    """
    if vote_block is None:
        return {}, None
    votes: dict[str, int] = {}
    answer: str | None = None
    for script in vote_block.find_all("script"):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, list):
            continue
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            voted = str(entry.get("voted_answers", "")).strip().upper()
            if not voted:
                continue
            count = int(entry.get("vote_count", 0) or 0)
            # Multi-letter votes (e.g. "AC") get split per letter so each
            # contributes to the per-letter tally.
            for letter in voted:
                if letter in "ABCDEF":
                    votes[letter] = votes.get(letter, 0) + count
            if entry.get("is_most_voted"):
                answer = voted
    if not votes:
        for letter, count in _VOTE_LETTER_RE.findall(vote_block.get_text(" ", strip=True)):
            votes[letter.upper()] = int(count)
    return votes, answer
