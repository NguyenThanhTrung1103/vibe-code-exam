"""Run admin practice preview for exam #1 + sample content for mismatch audit.

Equivalent to `POST /admin/exams/1/practice-preview/start` minus HTTP/CSRF —
calls `attempt_service.start_admin_preview_attempt` directly with the admin
user, then samples first/middle/last questions to surface content origin.
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from sqlalchemy import select

from app.db import SessionLocal
from app.models.catalog import Exam
from app.models.questions import Question
from app.models.users import User
from app.services import attempt_service


ADMIN_EMAIL = "admin@local.test"
EXAM_ID = 1


def main() -> int:
    s = SessionLocal()
    try:
        exam = s.get(Exam, EXAM_ID)
        actor = s.scalars(select(User).where(User.email == ADMIN_EMAIL)).one()
        # Verify status before starting
        publish_status = exam.publish_status.value
        bank_size = s.scalar(
            select(Question.id).where(Question.exam_id == EXAM_ID).where(Question.deleted_at.is_(None))
        )
        # Start admin preview attempt
        attempt = attempt_service.start_admin_preview_attempt(
            s, actor=actor, request_id=None, exam_id=EXAM_ID,
        )
        s.commit()

        # Sample the bank: first 3, middle, last by source_import_id distribution
        rows = s.execute(
            select(Question.id, Question.question_text, Question.source_import_id)
            .where(Question.exam_id == EXAM_ID)
            .where(Question.deleted_at.is_(None))
            .order_by(Question.id)
        ).all()
        ids = [(qid, src) for qid, _t, src in rows]
        by_src = Counter(src for _qid, src in ids)
        # Pick one question per source
        samples = {}
        for qid, txt, src in rows:
            if src not in samples:
                samples[src] = {"id": qid, "snippet": (txt or "")[:140]}

        out = {
            "exam_id": EXAM_ID,
            "exam_name": exam.name,
            "exam_publish_status_before": publish_status,
            "bank_size_alive": len(ids),
            "by_source_import_id": dict(by_src),
            "attempt_id": attempt.id,
            "attempt_first_question_url": f"/attempts/{attempt.id}/q/1",
            "samples_by_source": samples,
        }
        print(json.dumps(out, indent=2, default=str))
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
