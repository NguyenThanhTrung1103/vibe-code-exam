"""Phase 05 — exact-duplicate detection via SHA-256 content hash.

The canonical formula is shared with `plan.md` and Phase 06; do NOT
re-derive it elsewhere — call `content_hash` from this module.

Hash payload:
  sha256(normalized_question + "|" + "||".join(sorted_normalized_options))

`option_a..option_e` are reduced to non-empty normalized strings, then
sorted lexicographically — so option order within a row does not affect
the hash.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.questions import Question


def content_hash(canonical: dict[str, Any]) -> str:
    """Compute SHA-256 over normalized text + sorted normalized options."""
    q = (canonical.get("question_text") or "").strip()
    opts: list[str] = []
    for label_text in canonical.get("options") or []:
        # `options` is list[(label, text)] from the validator.
        if isinstance(label_text, tuple) and len(label_text) == 2:
            text = label_text[1]
        else:
            text = str(label_text)
        text = (text or "").strip()
        if text:
            opts.append(text)
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
