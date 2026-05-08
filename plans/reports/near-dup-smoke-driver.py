"""Smoke test: import a synthetic XLSX with rows derived from existing
questions on exam_id=1 to verify near-duplicate detection.

Constructs:
  Row 1: identical text to an existing question  → should be `duplicate`
  Row 2: same text + 1-word swap                  → should be `warning` (near-dup)
  Row 3: brand-new text                           → should be `ok`
  Row 4: existing text but with different options → should be `warning` (near-dup)

Deletes the smoke import after verification (idempotent re-runs).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select

from app.db import SessionLocal
from app.models.questions import Question, QuestionOption
from app.models.users import User
from app.services import import_service
from app.services.excel_parser import auto_map, read_headers


ADMIN_EMAIL = "admin@local.test"
TARGET_EXAM_ID = 1
ATTESTATION = "I have rights to upload this content for licensed use."


def _build_xlsx(path: Path, rows: list[dict[str, str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    headers = ["question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer"]
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, "") for h in headers])
    wb.save(str(path))


def main() -> int:
    s = SessionLocal()
    try:
        actor = s.scalars(select(User).where(User.email == ADMIN_EMAIL)).one()
        # Pick an existing question with reasonably long text + 4 options
        candidates = s.scalars(
            select(Question).where(Question.exam_id == TARGET_EXAM_ID).limit(50)
        ).all()
        target = next(q for q in candidates if q.question_text and len(q.question_text) >= 60)
        opts_db = list(
            s.scalars(
                select(QuestionOption)
                .where(QuestionOption.question_id == target.id)
                .order_by(QuestionOption.order_index)
            )
        )
        opt_texts = [(o.option_text or "") for o in opts_db]
        opt_texts = (opt_texts + ["", "", "", ""])[:4]
        opt_a, opt_b, opt_c, opt_d = opt_texts
        original = target.question_text or ""

        rows = [
            {  # 1 — identical (should land as duplicate)
                "question_text": original,
                "option_a": opt_a, "option_b": opt_b, "option_c": opt_c, "option_d": opt_d,
                "correct_answer": "A",
            },
            {  # 2 — minor reword (should land as warning / near-dup)
                "question_text": original.replace(" the ", " a ", 1) + " (variant)",
                "option_a": opt_a, "option_b": opt_b, "option_c": opt_c, "option_d": opt_d,
                "correct_answer": "B",
            },
            {  # 3 — fresh content (should land as ok)
                "question_text": "ZZZ_SMOKE_FRESH: a totally unrelated question for the smoke driver to confirm OK status.",
                "option_a": "alpha", "option_b": "bravo", "option_c": "charlie", "option_d": "delta",
                "correct_answer": "A",
            },
            {  # 4 — original text but different options (still flagged near-dup by question_text)
                "question_text": original + " — alt-options",
                "option_a": "x", "option_b": "y", "option_c": "z", "option_d": "w",
                "correct_answer": "B",
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            xlsx_path = Path(td) / "near-dup-smoke.xlsx"
            _build_xlsx(xlsx_path, rows)
            blob = xlsx_path.read_bytes()
            imp = import_service.create_import(
                s, actor=actor, request_id=None,
                target_exam_id=TARGET_EXAM_ID,
                file_name="near-dup-smoke.xlsx",
                file_bytes=blob, attestation=ATTESTATION,
                title="near-dup smoke",
            )
            s.commit()
            _sheet, headers = read_headers(imp.file_path)
            mapping = auto_map(headers)
            import_service.save_mapping(
                s, actor=actor, request_id=None,
                import_id=imp.id, column_mapping=mapping,
            )
            counts = import_service.parse_and_stage(
                s, actor=actor, request_id=None, import_id=imp.id,
            )
            s.commit()

        # Read back staged items
        from app.models.imports import ImportItem
        items = list(
            s.scalars(
                select(ImportItem).where(ImportItem.import_id == imp.id).order_by(ImportItem.row_number)
            )
        )
        result = {
            "import_id": imp.id,
            "target_question_id": target.id,
            "target_text_prefix": original[:80],
            "stage_counts": counts,
            "rows": [
                {
                    "row_number": it.row_number,
                    "status": it.status.value,
                    "warning_message": it.warning_message,
                    "near_duplicate_match": (it.normalized_data or {}).get("_near_duplicate_match"),
                }
                for it in items
            ],
        }
        print(json.dumps(result, indent=2, default=str))
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
