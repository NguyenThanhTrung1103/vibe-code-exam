"""Empirical demo: does the current dedup flag minor variations?

Computes content_hash() for an existing question + 6 progressively-modified
variants, and reports whether each would dedup against the original.
No DB writes, read-only.
"""
from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models.questions import Question, QuestionOption
from app.services.import_dedup import content_hash, existing_question_hashes_for_exam


def main() -> None:
    s = SessionLocal()
    q = s.scalars(select(Question).where(Question.exam_id == 1).limit(1)).one()
    opts = list(
        s.scalars(
            select(QuestionOption)
            .where(QuestionOption.question_id == q.id)
            .order_by(QuestionOption.order_index)
        )
    )
    base_text = q.question_text or ""
    base_options = [(o.label, o.option_text or "") for o in opts]

    def h(text: str, options: list[tuple[str, str]]) -> str:
        return content_hash({"question_text": text, "options": options})

    print(f"Question id={q.id}  exam_id={q.exam_id}")
    print(f"  Original text: {base_text[:90]}...")
    print(f"  Original n_options: {len(base_options)}")
    print(f"  DB content_hash: {q.content_hash}")
    print()

    cases = [
        ("identical (control)", base_text, base_options),
        ("trailing space", base_text + " ", base_options),
        ("one word swap", base_text.replace(" the ", " THE ", 1), base_options),
        ("typo fix", base_text + ".", base_options),
        ("uppercase first letter", base_text[0].upper() + base_text[1:], base_options),
        ("added new option G", base_text, base_options + [("G", "(new option)")]),
        ("changed one option text", base_text, [
            (lbl, txt + " ") if i == 0 else (lbl, txt)
            for i, (lbl, txt) in enumerate(base_options)
        ]),
        ("re-ordered options (sorted should not matter)", base_text, list(reversed(base_options))),
    ]

    existing = existing_question_hashes_for_exam(s, exam_id=q.exam_id)
    print(f"{'case':<48} {'hash[:12]':<14} would_dedup?")
    print("-" * 80)
    for name, text, opts_in in cases:
        hh = h(text, opts_in)
        flagged = hh in existing
        print(f"{name:<48} {hh[:12]:<14} {'YES' if flagged else 'no'}")
    s.close()


if __name__ == "__main__":
    main()
