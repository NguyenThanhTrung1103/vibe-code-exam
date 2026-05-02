"""Milestone 1 fixture-import smoke driver.

Runs ONE fixture file end-to-end through the same `app.services.import_service`
calls that the admin HTTP routes use. Exits non-zero on any guard failure.

Usage (on the LXC, run from /srv/exam-platform):
    sudo -u exam-platform .venv/bin/python -m scripts.smoke_milestone1_fixture \\
        --fixture /tmp/fixtures/import_quiz_question_ccna_online.xlsx \\
        --target-exam-id 1 \\
        --admin-email admin@local.test

This intentionally does NOT go through the HTTP layer (no admin session
on the LXC right now, and we are forbidden from updating existing user
rows). It exercises the same service code path the HTTP route calls.

Strict boundaries:
  * Reads from --fixture only.
  * Writes only via the standard import pipeline (imports, import_items,
    questions, question_options, question_explanations, audit_logs,
    community_discussion_sources). No DELETE / UPDATE of pre-existing rows.
  * No internet IO.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models.imports import Import, ImportItem
from app.models.questions import Question
from app.models.users import User
from app.services import import_service
from app.services.excel_parser import auto_map, read_headers


def _print(label: str, obj) -> None:
    print(f"{label}: {obj}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--target-exam-id", required=True, type=int)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument(
        "--title",
        default="Milestone 1 fixture smoke",
        help="Optional admin label; falls back to file_name.",
    )
    args = parser.parse_args()

    fixture: Path = args.fixture
    if not fixture.exists():
        print(f"ERROR: fixture not found: {fixture}", file=sys.stderr)
        return 2

    file_bytes = fixture.read_bytes()
    file_name = fixture.name

    with SessionLocal() as session:
        actor: User | None = session.scalars(
            select(User).where(User.email == args.admin_email)
        ).first()
        if actor is None:
            print(f"ERROR: admin user not found: {args.admin_email}", file=sys.stderr)
            return 2

        # 1. Upload
        imp = import_service.create_import(
            session,
            actor=actor,
            request_id="smoke-m1",
            target_exam_id=args.target_exam_id,
            file_name=file_name,
            file_bytes=file_bytes,
            attestation="milestone-1 fixture smoke (private/draft)",
            title=args.title,
        )
        session.commit()
        session.refresh(imp)
        _print("import_id", imp.id)
        _print("file_type", imp.file_type)
        _print("detected_format", imp.detected_format)
        _print("file_path", imp.file_path)

        # 2. Mapping (XLSX only) + parse_and_stage
        if imp.file_type == "xlsx":
            sheet, headers = read_headers(imp.file_path)
            mapping = auto_map(headers)
            _print("xlsx_sheet", sheet)
            _print("xlsx_headers", headers)
            _print("xlsx_mapping", mapping)
            import_service.save_mapping(
                session,
                actor=actor,
                request_id="smoke-m1",
                import_id=imp.id,
                column_mapping=mapping,
            )
            session.commit()
        counts = import_service.parse_and_stage(
            session,
            actor=actor,
            request_id="smoke-m1",
            import_id=imp.id,
        )
        session.commit()
        _print("parse_counts", counts)

        # 3. Confirm
        summary = import_service.confirm_import(
            session,
            actor=actor,
            request_id="smoke-m1",
            import_id=imp.id,
        )
        session.commit()
        _print("confirm_summary", summary)

        # 4. Per-status row counts on import_items + questions
        item_status_rows = session.execute(
            select(ImportItem.status, ImportItem.id).where(ImportItem.import_id == imp.id)
        ).all()
        per_status: dict[str, int] = {}
        for st, _id in item_status_rows:
            per_status[st.value] = per_status.get(st.value, 0) + 1
        _print("import_item_per_status", per_status)

        questions = list(
            session.scalars(
                select(Question).where(Question.source_import_id == imp.id)
            )
        )
        missing_explanation = sum(
            1
            for q in questions
            if not session.scalars(
                select(1).select_from(
                    __import__(
                        "app.models.questions", fromlist=["QuestionExplanation"]
                    ).QuestionExplanation
                ).where(
                    __import__(
                        "app.models.questions", fromlist=["QuestionExplanation"]
                    ).QuestionExplanation.question_id
                    == q.id
                )
            ).first()
        )
        _print("imported_question_count", len(questions))
        _print("missing_explanation_count", missing_explanation)

        # Community sources count via raw SQL — same pattern the done page uses.
        from sqlalchemy import text as _text

        cds_count = (
            session.execute(
                _text(
                    "SELECT count(*) FROM community_discussion_sources "
                    "WHERE question_id IN ("
                    "  SELECT id FROM questions WHERE source_import_id = :iid"
                    ")"
                ),
                {"iid": imp.id},
            ).scalar()
            or 0
        )
        _print("community_sources_count", cds_count)

        # First question id for the Review URL
        first_qid = questions[0].id if questions else None
        _print("first_question_id", first_qid)

        review_url = f"/admin/imports/{imp.id}/done"
        questions_filter_url = f"/admin/questions?source_import_id={imp.id}"
        _print("done_url", review_url)
        _print("questions_filter_url", questions_filter_url)

        # Final structured JSON for easy capture by the calling shell.
        result = {
            "import_id": imp.id,
            "detected_format": imp.detected_format,
            "file_type": imp.file_type,
            "target_exam_id": imp.target_exam_id,
            "title": imp.title,
            "parse_counts": counts,
            "confirm_summary": summary,
            "import_item_per_status": per_status,
            "imported_question_count": len(questions),
            "missing_explanation_count": missing_explanation,
            "community_sources_count": int(cds_count),
            "first_question_id": first_qid,
            "done_url": review_url,
            "questions_filter_url": questions_filter_url,
        }
        print("---SMOKE_RESULT---")
        print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
