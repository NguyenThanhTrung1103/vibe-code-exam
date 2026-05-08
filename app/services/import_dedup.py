"""Phase 05 — exact-duplicate detection via SHA-256 content hash.

The canonical formula is shared with `plan.md` and Phase 06; do NOT
re-derive it elsewhere — call `content_hash` from this module.

Hash payload:
  sha256(canonical_question + "|" + "||".join(sorted_canonical_options))

`canonical_*` means: NFKD-normalised, accent-folded, lower-cased, with
internal whitespace runs collapsed to a single space. This makes the
hash stable across cosmetic differences (trailing spaces, smart quotes,
case changes, accent variants) so two rows that read identically are
treated as duplicates regardless of stray whitespace or capitalisation.

Options are sorted lexicographically after canonicalisation — so option
order within a row does not affect the hash either.

Dedup is always scoped to the target exam (`existing_question_hashes_for_exam`).
Cross-exam matches are intentional non-events: the same question text
re-imported under a different exam is a legitimate new question.

Near-duplicate detection (added 2026-05-04) is a separate, non-blocking
signal — see `find_near_duplicates`. Powered by Postgres `pg_trgm` (see
migration `0010_…_pg_trgm_question_text_index.py`).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.questions import Question

_WS_RE = re.compile(r"\s+")

# Minimum question length to consider for near-duplicate matching. Short
# stems (<40 chars) trigger trigram false positives constantly — common
# words like "Which of the following…" lift trivial similarity scores.
_NEAR_DUP_MIN_TEXT_LEN = 40


@dataclass(frozen=True, slots=True)
class NearDuplicateMatch:
    """One near-duplicate hit during import staging."""

    question_id: int
    similarity: float
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "similarity": round(self.similarity, 3),
            "snippet": self.snippet[:120],
        }


def canonicalize_for_hash(value: str | None) -> str:
    """Return a hash-canonical form of `value`.

    Steps: NFKD-normalise, drop combining marks (accent fold), lower-case,
    collapse whitespace runs to a single space, strip outer whitespace.
    `None` and non-strings degrade to "".

    This is stricter than `import_normalizer.normalize_text` because here
    we want hashes to be stable across cosmetic differences (case, accents,
    smart quotes, tab vs space, etc.) — even where end-user-visible text
    legitimately differs.
    """
    if not value:
        return ""
    text_value = value if isinstance(value, str) else str(value)
    decomposed = unicodedata.normalize("NFKD", text_value)
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = no_marks.replace("đ", "d").replace("Đ", "d").lower()
    collapsed = _WS_RE.sub(" ", folded)
    return collapsed.strip()


def content_hash(canonical: dict[str, Any]) -> str:
    """Compute SHA-256 over canonicalised text + sorted canonicalised options.

    See module docstring + `canonicalize_for_hash` for the canonicalisation
    contract. Stable across whitespace, case, accent, and option-order
    variations of the same question.
    """
    q = canonicalize_for_hash(canonical.get("question_text"))
    opts: list[str] = []
    for label_text in canonical.get("options") or []:
        # `options` is list[(label, text)] from the validator.
        if isinstance(label_text, tuple) and len(label_text) == 2:
            text_val = label_text[1]
        else:
            text_val = label_text
        cleaned = canonicalize_for_hash(text_val)
        if cleaned:
            opts.append(cleaned)
    payload = q + "|" + "||".join(sorted(opts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def existing_question_hashes_for_exam(session: Session, *, exam_id: int) -> set[str]:
    """Return all `content_hash` values for non-deleted questions on `exam_id`."""
    rows = session.scalars(
        select(Question.content_hash)
        .where(Question.exam_id == exam_id)
        .where(Question.deleted_at.is_(None))
        .where(Question.content_hash.is_not(None))
    )
    return {h for h in rows if h}


def find_near_duplicates(
    session: Session,
    *,
    exam_id: int,
    question_text: str,
    threshold: float = 0.55,
    limit: int = 3,
) -> list[NearDuplicateMatch]:
    """Trigram-similarity near-duplicate search against questions in an exam.

    Returns matches ordered by descending similarity. Empty list when the
    text is too short, when no rows clear the threshold, or when an
    exact-hash dedup will already handle the row (caller's responsibility
    to skip when content_hash matches).

    Uses the GIN trigram index on `questions.question_text` (partial,
    `WHERE deleted_at IS NULL`). At small table sizes Postgres may pick a
    seq scan — that's fine and intentional, the planner is right.
    """
    q_text = (question_text or "").strip()
    if len(q_text) < _NEAR_DUP_MIN_TEXT_LEN:
        return []

    # `question_text % :q` (pg_trgm operator) lets the planner use the GIN
    # index; the explicit `similarity(...) >= :threshold` then enforces our
    # stricter cutoff than the default 0.3 trigram threshold.
    sql = text(
        """
        SELECT id, question_text, similarity(question_text, :q) AS sim
        FROM questions
        WHERE exam_id = :exam_id
          AND deleted_at IS NULL
          AND question_text % :q
          AND similarity(question_text, :q) >= :threshold
        ORDER BY sim DESC
        LIMIT :limit
        """
    )
    rows = session.execute(
        sql,
        {"q": q_text, "exam_id": exam_id, "threshold": threshold, "limit": limit},
    ).all()
    return [
        NearDuplicateMatch(question_id=int(qid), similarity=float(sim), snippet=str(snippet or ""))
        for qid, snippet, sim in rows
    ]
