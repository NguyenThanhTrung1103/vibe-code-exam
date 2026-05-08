"""One-shot dev driver: import the 4 sample dumps via the service layer.

Mirrors the admin wizard flow (create → [save_mapping] → parse_and_stage → confirm)
without going through HTTP / CSRF. Idempotent across runs only if rows are wiped first.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.orm import Session

# App imports (app must be on sys.path; run from /srv/exam-platform)
from app.db import SessionLocal  # type: ignore
from app.models.users import User
from app.services import import_service
from app.services.excel_parser import auto_map, read_headers


ADMIN_EMAIL = "admin@local.test"
TARGET_EXAM_ID = 1
ATTESTATION = "I have rights to upload this content for licensed use."

DUMPS_DIR = Path("/tmp/template-dumps")
FILES = [
    "import_quiz_question_ccna_online.xlsx",
    "57q_efw.html",
    "57q_efw(1).html",
    "646b6d2013bb103e361af8674630dcb6_2.pdf",
]


def _import_one(s: Session, actor: User, fname: str) -> dict:
    fpath = DUMPS_DIR / fname
    blob = fpath.read_bytes()
    try:
        imp = import_service.create_import(
            s,
            actor=actor,
            request_id=None,
            target_exam_id=TARGET_EXAM_ID,
            file_name=fname,
            file_bytes=blob,
            attestation=ATTESTATION,
            title=f"auto-import {fname}",
        )
        s.commit()
    except Exception as e:
        s.rollback()
        return {"file": fname, "stage": "create_import", "error": repr(e)}

    # XLSX: auto-map columns then save_mapping, else go straight to parse_and_stage.
    try:
        if (imp.file_type or "").lower() == "xlsx":
            _sheet, headers = read_headers(imp.file_path)
            mapping = auto_map(headers)
            import_service.save_mapping(
                s, actor=actor, request_id=None,
                import_id=imp.id, column_mapping=mapping,
            )
            s.commit()

        counts = import_service.parse_and_stage(
            s, actor=actor, request_id=None, import_id=imp.id,
        )
        s.commit()
    except Exception as e:
        s.rollback()
        return {"file": fname, "import_id": imp.id, "stage": "parse_and_stage", "error": repr(e)}

    try:
        summary = import_service.confirm_import(
            s, actor=actor, request_id=None, import_id=imp.id,
        )
        s.commit()
    except Exception as e:
        s.rollback()
        return {"file": fname, "import_id": imp.id, "stage": "confirm_import", "error": repr(e), "stage_counts": counts}

    return {
        "file": fname,
        "import_id": imp.id,
        "file_type": imp.file_type,
        "detected_format": imp.detected_format,
        "stage_counts": counts,
        "confirm_summary": summary,
    }


def main() -> int:
    s = SessionLocal()
    try:
        actor = s.query(User).filter(User.email == ADMIN_EMAIL).one_or_none()
        if actor is None:
            print(f"FATAL: admin user {ADMIN_EMAIL} not found", file=sys.stderr)
            return 1
        results = [_import_one(s, actor, f) for f in FILES]
    finally:
        s.close()
    import json
    print(json.dumps(results, indent=2, default=str))
    return 0 if all("error" not in r for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
