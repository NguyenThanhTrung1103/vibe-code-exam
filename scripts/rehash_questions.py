"""CLI: recompute `questions.content_hash` with the canonicalised recipe.

After `import_dedup.content_hash` was hardened to fold case / accents /
whitespace (Bug 2 fix, 2026-05-05), pre-existing rows still carry hashes
computed under the old recipe. Without a one-off rehash, the dedup query
treats them as "new" content and admins re-import the same questions.

Usage (operator-gated; never auto-run on startup):

    uv run python -m scripts.rehash_questions [--dry-run] [--exam-id N]

Reads each non-deleted Question + its QuestionOptions, recomputes the
hash via `import_dedup.content_hash`, and updates in place. Commits in
chunks of 500 to keep transaction size sane on large banks.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.questions import Question, QuestionOption
from app.services.import_dedup import content_hash

_CHUNK = 500


def _options_for(session: Session, question_id: int) -> list[tuple[str, str]]:
    rows = list(
        session.scalars(
            select(QuestionOption)
            .where(QuestionOption.question_id == question_id)
            .order_by(QuestionOption.order_index)
        )
    )
    return [(o.label or "", o.option_text or "") for o in rows]


def _iter_questions(session: Session, exam_id: int | None) -> Iterable[Question]:
    stmt = select(Question).where(Question.deleted_at.is_(None)).order_by(Question.id)
    if exam_id is not None:
        stmt = stmt.where(Question.exam_id == exam_id)
    yield from session.scalars(stmt).yield_per(200)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="don't write — print stats only")
    parser.add_argument("--exam-id", type=int, default=None, help="restrict to a single exam")
    args = parser.parse_args()

    inspected = 0
    changed = 0
    with SessionLocal() as session:
        pending = 0
        for q in _iter_questions(session, args.exam_id):
            inspected += 1
            options = _options_for(session, q.id)
            new_hash = content_hash(
                {"question_text": q.question_text or "", "options": options}
            )
            if (q.content_hash or "") == new_hash:
                continue
            changed += 1
            if not args.dry_run:
                q.content_hash = new_hash
                pending += 1
                if pending >= _CHUNK:
                    session.commit()
                    pending = 0
        if not args.dry_run and pending:
            session.commit()

    mode = "would update" if args.dry_run else "updated"
    print(f"rehash_questions: inspected={inspected}, {mode}={changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
