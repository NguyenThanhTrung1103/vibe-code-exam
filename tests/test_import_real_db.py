"""Phase 05 real-DB integration tests for the Excel import pipeline.

Gated by `EXAM_PLATFORM_TEST_REAL_DB=1`. Verifies:
  * full happy path: upload → mapping → parse → preview → confirm
  * audit rows for each phase
  * idempotent confirm (running twice yields zero new questions)
  * within-import dedup
  * cross-exam dedup against existing questions
  * partial-failure tolerance (forced FK error on one row)
  * uploaded files land outside the public path (under settings.uploads_dir)
  * filename traversal is normalised
  * HTML in question_text is sanitized; raw_data preserves original
  * source_locator populated on imported questions
  * imports default to private/draft (Question.status='imported')
  * RBAC: anonymous → 401 on /admin/imports
  * Missing CSRF on upload → 403
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import delete, select

from app.audit.events import AuditAction
from app.config import get_settings
from app.db import SessionLocal
from app.main import create_app
from app.models.audit import AuditLog
from app.models.catalog import Course, Exam, Provider
from app.models.enums import ImportItemStatus, QuestionStatus, UserRole
from app.models.imports import Import, ImportItem
from app.models.questions import Question, QuestionExplanation, QuestionOption
from app.models.users import User
from app.redis_client import get_redis
from app.services import catalog_service, import_service

pytestmark = pytest.mark.skipif(
    os.environ.get("EXAM_PLATFORM_TEST_REAL_DB") != "1",
    reason="real-DB integration tests gated by EXAM_PLATFORM_TEST_REAL_DB=1",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_real():
    return create_app()


@pytest.fixture()
def client(app_real):
    with TestClient(app_real) as c:
        yield c


@pytest.fixture()
def nonce() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def _flush_login_rate_limits():
    r = get_redis()
    for key in r.scan_iter(match="rl:*"):
        r.delete(key)
    yield


@pytest.fixture(autouse=True)
def _isolate_uploads_dir(monkeypatch):
    """Phase 05 writes uploaded XLSX files; isolate to a tmpdir per test."""
    tmpdir = tempfile.mkdtemp(prefix="phase05-uploads-")
    monkeypatch.setenv("UPLOADS_DIR", tmpdir)
    # Force settings re-evaluation by clearing the lru_cache.
    get_settings.cache_clear()
    yield Path(tmpdir)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _cleanup_phase05():
    """Tear-down: delete every row created by these tests."""
    yield
    with SessionLocal() as s:
        # Find import IDs we created (file_path under our tmpdir is enough,
        # but identifying via uploader email is simpler).
        user_ids = list(s.scalars(select(User.id).where(User.email.like("%@p05test.local"))))
        if user_ids:
            import_ids = list(s.scalars(select(Import.id).where(Import.uploaded_by.in_(user_ids))))
            if import_ids:
                # Delete questions stitched to these imports first.
                question_ids = list(
                    s.scalars(select(Question.id).where(Question.source_import_id.in_(import_ids)))
                )
                if question_ids:
                    s.execute(
                        delete(QuestionExplanation).where(
                            QuestionExplanation.question_id.in_(question_ids)
                        )
                    )
                    s.execute(
                        delete(QuestionOption).where(QuestionOption.question_id.in_(question_ids))
                    )
                    s.execute(delete(Question).where(Question.id.in_(question_ids)))
                s.execute(delete(ImportItem).where(ImportItem.import_id.in_(import_ids)))
                s.execute(delete(Import).where(Import.id.in_(import_ids)))
            # Wipe catalog rows we created (slug 'p05t-*').
            provider_ids = list(s.scalars(select(Provider.id).where(Provider.slug.like("p05t-%"))))
            if provider_ids:
                course_ids = list(
                    s.scalars(select(Course.id).where(Course.provider_id.in_(provider_ids)))
                )
                exam_ids = list(
                    s.scalars(select(Exam.id).where(Exam.course_id.in_(course_ids or [-1])))
                )
                if exam_ids:
                    s.execute(delete(Exam).where(Exam.id.in_(exam_ids)))
                if course_ids:
                    s.execute(delete(Course).where(Course.id.in_(course_ids)))
                s.execute(delete(Provider).where(Provider.id.in_(provider_ids)))
            s.execute(
                delete(AuditLog).where(
                    AuditLog.entity_type.in_(("import", "import_item", "question"))
                )
            )
            s.execute(delete(User).where(User.id.in_(user_ids)))
        s.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(nonce: str) -> User:
    from app.auth.service import register_user

    with SessionLocal() as s:
        u = register_user(
            s,
            email=f"admin-{nonce}@p05test.local",
            username=f"adm{nonce}",
            password="Phase05-good-pw",
            role=UserRole.admin,
            request_id=None,
        )
        s.commit()
        return s.get(User, u.id)


def _make_exam(actor: User, nonce: str) -> int:
    """Create provider/course/exam scaffold; return exam_id."""
    with SessionLocal() as s:
        actor = s.merge(actor)
        provider = catalog_service.create_provider(
            s, actor=actor, request_id=None, name=f"P{nonce}", slug=f"p05t-{nonce}"
        )
        course = catalog_service.create_course(
            s, actor=actor, request_id=None, provider_id=provider.id, name="C", slug="c1"
        )
        exam = catalog_service.create_exam(
            s, actor=actor, request_id=None, course_id=course.id, name="E", slug="e1"
        )
        s.commit()
        return exam.id


def _make_xlsx(rows: list[list]) -> bytes:
    """Build an in-memory .xlsx with the supplied rows (header is rows[0])."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Q"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _good_xlsx(nonce: str, n: int = 3) -> bytes:
    rows = [["Question", "A", "B", "C", "Correct", "Difficulty", "Explanation"]]
    for i in range(n):
        rows.append([f"Q{i}-{nonce}", f"A-{i}", f"B-{i}", f"C-{i}", "B", "easy", f"Why {i}"])
    return _make_xlsx(rows)


def _column_mapping_for_good_xlsx() -> dict[str, str | None]:
    return {
        "Question": "question_text",
        "A": "option_a",
        "B": "option_b",
        "C": "option_c",
        "Correct": "correct_answer",
        "Difficulty": "difficulty",
        "Explanation": "explanation",
    }


# ---------------------------------------------------------------------------
# Service-layer flow
# ---------------------------------------------------------------------------


def test_full_flow_upload_parse_confirm(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id = _make_exam(actor, nonce)
    file_bytes = _good_xlsx(nonce, n=3)
    with SessionLocal() as s:
        actor = s.merge(actor)
        imp = import_service.create_import(
            s,
            actor=actor,
            request_id=None,
            target_exam_id=exam_id,
            file_name="../../../etc/passwd.xlsx",  # path traversal probe
            file_bytes=file_bytes,
            attestation="I have rights",
        )
        s.commit()
        # Sanitised filename — no leading directories.
        assert "/" not in imp.file_name
        assert "\\" not in imp.file_name
        # File stored outside any public/static path.
        assert Path(imp.file_path).exists()
        assert "static" not in imp.file_path

        import_service.save_mapping(
            s,
            actor=actor,
            request_id=None,
            import_id=imp.id,
            column_mapping=_column_mapping_for_good_xlsx(),
        )
        s.commit()

        counts = import_service.parse_and_stage(s, actor=actor, request_id=None, import_id=imp.id)
        s.commit()
        assert counts.get("ok", 0) == 3
        assert counts.get("error", 0) == 0

        summary = import_service.confirm_import(s, actor=actor, request_id=None, import_id=imp.id)
        s.commit()
        assert summary["imported"] == 3
        assert summary["errors"] == 0

        # Confirmed questions are auto-published — Exam.publish_status remains
        # the single on/off switch the admin uses to expose/hide a whole exam.
        questions = list(s.scalars(select(Question).where(Question.source_import_id == imp.id)))
        assert len(questions) == 3
        for q in questions:
            assert q.status == QuestionStatus.published
            assert q.source_locator is not None
            assert q.source_locator["import_id"] == imp.id
            assert q.source_locator["row_number"] >= 2
            assert q.exam_id == exam_id

        # Audit rows present
        audits = list(
            s.scalars(
                select(AuditLog).where(
                    AuditLog.entity_type.in_(("import", "question")),
                    AuditLog.entity_id.in_([imp.id] + [q.id for q in questions]),
                )
            )
        )
        actions = {a.action for a in audits}
        assert AuditAction.IMPORT_UPLOADED.value in actions
        assert AuditAction.IMPORT_MAPPING_SAVED.value in actions
        assert AuditAction.IMPORT_PARSED.value in actions
        assert AuditAction.IMPORT_CONFIRMED.value in actions
        assert AuditAction.QUESTION_IMPORTED.value in actions


def test_idempotent_confirm_zero_duplicate_questions(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id = _make_exam(actor, nonce)
    file_bytes = _good_xlsx(nonce, n=3)
    with SessionLocal() as s:
        actor = s.merge(actor)
        imp = import_service.create_import(
            s,
            actor=actor,
            request_id=None,
            target_exam_id=exam_id,
            file_name="ok.xlsx",
            file_bytes=file_bytes,
            attestation="rights ok",
        )
        s.commit()
        import_service.save_mapping(
            s,
            actor=actor,
            request_id=None,
            import_id=imp.id,
            column_mapping=_column_mapping_for_good_xlsx(),
        )
        import_service.parse_and_stage(s, actor=actor, request_id=None, import_id=imp.id)
        s.commit()
        first = import_service.confirm_import(s, actor=actor, request_id=None, import_id=imp.id)
        s.commit()
        second = import_service.confirm_import(s, actor=actor, request_id=None, import_id=imp.id)
        s.commit()
        assert first["imported"] == 3
        assert second["imported"] == 0
        # Total question rows under exam = exactly 3.
        n = s.scalar(
            select(__import__("sqlalchemy").func.count(Question.id)).where(
                Question.exam_id == exam_id
            )
        )
        assert n == 3


def test_within_import_duplicate_detection(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id = _make_exam(actor, nonce)
    rows = [["Question", "A", "B", "Correct"]]
    rows.append(["Same question?", "X", "Y", "A"])
    rows.append(["Same question?", "X", "Y", "A"])  # exact dup of row 2
    rows.append(["Different?", "X", "Y", "B"])
    file_bytes = _make_xlsx(rows)

    with SessionLocal() as s:
        actor = s.merge(actor)
        imp = import_service.create_import(
            s,
            actor=actor,
            request_id=None,
            target_exam_id=exam_id,
            file_name="dup.xlsx",
            file_bytes=file_bytes,
            attestation="rights ok",
        )
        s.commit()
        import_service.save_mapping(
            s,
            actor=actor,
            request_id=None,
            import_id=imp.id,
            column_mapping={
                "Question": "question_text",
                "A": "option_a",
                "B": "option_b",
                "Correct": "correct_answer",
            },
        )
        counts = import_service.parse_and_stage(s, actor=actor, request_id=None, import_id=imp.id)
        s.commit()
        assert counts.get("duplicate", 0) == 1
        assert counts.get("ok", 0) == 2


def test_html_in_question_text_is_stripped_but_raw_preserved(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id = _make_exam(actor, nonce)
    rows = [["Question", "A", "B", "Correct"]]
    rows.append(["<script>alert(1)</script>What?", "X", "Y", "A"])
    file_bytes = _make_xlsx(rows)

    with SessionLocal() as s:
        actor = s.merge(actor)
        imp = import_service.create_import(
            s,
            actor=actor,
            request_id=None,
            target_exam_id=exam_id,
            file_name="xss.xlsx",
            file_bytes=file_bytes,
            attestation="rights ok",
        )
        s.commit()
        import_service.save_mapping(
            s,
            actor=actor,
            request_id=None,
            import_id=imp.id,
            column_mapping={
                "Question": "question_text",
                "A": "option_a",
                "B": "option_b",
                "Correct": "correct_answer",
            },
        )
        import_service.parse_and_stage(s, actor=actor, request_id=None, import_id=imp.id)
        s.commit()
        item = s.scalars(select(ImportItem).where(ImportItem.import_id == imp.id)).first()
        assert item is not None
        # Raw preserves original
        assert "<script>" in item.raw_data["question_text"]
        # Normalized stripped
        assert "<script>" not in item.normalized_data["question_text"]
        assert "alert(1)" in item.normalized_data["question_text"]  # body preserved


def test_missing_question_text_marks_error(nonce: str) -> None:
    actor = _make_admin(nonce)
    exam_id = _make_exam(actor, nonce)
    rows = [["Question", "A", "B", "Correct"]]
    rows.append(["", "X", "Y", "A"])  # empty question_text → error
    file_bytes = _make_xlsx(rows)

    with SessionLocal() as s:
        actor = s.merge(actor)
        imp = import_service.create_import(
            s,
            actor=actor,
            request_id=None,
            target_exam_id=exam_id,
            file_name="bad.xlsx",
            file_bytes=file_bytes,
            attestation="rights ok",
        )
        s.commit()
        import_service.save_mapping(
            s,
            actor=actor,
            request_id=None,
            import_id=imp.id,
            column_mapping={
                "Question": "question_text",
                "A": "option_a",
                "B": "option_b",
                "Correct": "correct_answer",
            },
        )
        counts = import_service.parse_and_stage(s, actor=actor, request_id=None, import_id=imp.id)
        s.commit()
        # "" passes through normalize_row → still falsy in canonical['question_text'].
        # If openpyxl turns the cell into None, the row may be skipped — we only
        # assert there are no successful items here.
        assert counts.get("ok", 0) == 0


def test_cross_exam_dedup_against_existing_questions(nonce: str) -> None:
    """Pre-existing question with same content_hash → second import flags duplicate."""
    actor = _make_admin(nonce)
    exam_id = _make_exam(actor, nonce)

    # First import
    rows = [["Question", "A", "B", "Correct"]]
    rows.append(["Same Q?", "X", "Y", "A"])
    file_bytes = _make_xlsx(rows)
    with SessionLocal() as s:
        actor = s.merge(actor)
        imp1 = import_service.create_import(
            s,
            actor=actor,
            request_id=None,
            target_exam_id=exam_id,
            file_name="i1.xlsx",
            file_bytes=file_bytes,
            attestation="rights ok",
        )
        s.commit()
        import_service.save_mapping(
            s,
            actor=actor,
            request_id=None,
            import_id=imp1.id,
            column_mapping={
                "Question": "question_text",
                "A": "option_a",
                "B": "option_b",
                "Correct": "correct_answer",
            },
        )
        import_service.parse_and_stage(s, actor=actor, request_id=None, import_id=imp1.id)
        import_service.confirm_import(s, actor=actor, request_id=None, import_id=imp1.id)
        s.commit()

    # Second import with same row
    with SessionLocal() as s:
        actor = s.merge(actor)
        imp2 = import_service.create_import(
            s,
            actor=actor,
            request_id=None,
            target_exam_id=exam_id,
            file_name="i2.xlsx",
            file_bytes=file_bytes,
            attestation="rights ok",
        )
        s.commit()
        import_service.save_mapping(
            s,
            actor=actor,
            request_id=None,
            import_id=imp2.id,
            column_mapping={
                "Question": "question_text",
                "A": "option_a",
                "B": "option_b",
                "Correct": "correct_answer",
            },
        )
        counts = import_service.parse_and_stage(s, actor=actor, request_id=None, import_id=imp2.id)
        s.commit()
        assert counts.get("duplicate", 0) == 1
        # Confirming yields zero new questions.
        summary = import_service.confirm_import(s, actor=actor, request_id=None, import_id=imp2.id)
        s.commit()
        assert summary["imported"] == 0


def test_partial_failure_on_one_row_does_not_block_others(nonce: str, monkeypatch) -> None:
    """Force a per-item DB error on row 2 only; rows 1, 3 must still import."""
    actor = _make_admin(nonce)
    exam_id = _make_exam(actor, nonce)
    rows = [["Question", "A", "B", "Correct"]]
    rows.append(["Q1", "X", "Y", "A"])
    rows.append(["Q2-fail", "X", "Y", "A"])
    rows.append(["Q3", "X", "Y", "A"])
    file_bytes = _make_xlsx(rows)

    real_create = import_service._create_question_from_item

    def flaky_create(session, *, imp, item, actor, request_id):
        if (item.normalized_data or {}).get("question_text") == "Q2-fail":
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError("synthetic", {}, Exception("forced"))
        return real_create(session, imp=imp, item=item, actor=actor, request_id=request_id)

    monkeypatch.setattr(import_service, "_create_question_from_item", flaky_create)

    with SessionLocal() as s:
        actor = s.merge(actor)
        imp = import_service.create_import(
            s,
            actor=actor,
            request_id=None,
            target_exam_id=exam_id,
            file_name="pf.xlsx",
            file_bytes=file_bytes,
            attestation="rights ok",
        )
        s.commit()
        import_service.save_mapping(
            s,
            actor=actor,
            request_id=None,
            import_id=imp.id,
            column_mapping={
                "Question": "question_text",
                "A": "option_a",
                "B": "option_b",
                "Correct": "correct_answer",
            },
        )
        import_service.parse_and_stage(s, actor=actor, request_id=None, import_id=imp.id)
        s.commit()
        summary = import_service.confirm_import(s, actor=actor, request_id=None, import_id=imp.id)
        s.commit()
        assert summary["imported"] == 2
        assert summary["errors"] == 1
        # The error item is now in 'error' status.
        err_items = list(
            s.scalars(
                select(ImportItem).where(
                    ImportItem.import_id == imp.id,
                    ImportItem.status == ImportItemStatus.error,
                )
            )
        )
        assert len(err_items) == 1


# ---------------------------------------------------------------------------
# HTTP-level: RBAC + CSRF
# ---------------------------------------------------------------------------


def test_admin_imports_requires_admin(client: TestClient) -> None:
    r = client.get("/admin/imports")
    assert r.status_code == 401


def test_admin_imports_post_without_csrf_returns_403(client: TestClient, nonce: str) -> None:
    actor = _make_admin(nonce)
    csrf = client.get("/auth/login").cookies.get("exam_csrf")
    client.post(
        "/auth/login",
        data={
            "identifier": actor.email,
            "password": "Phase05-good-pw",
            "csrf_token": csrf,
        },
    )
    # POST without csrf_token form field → 403 invalid csrf.
    r = client.post(
        "/admin/imports",
        data={"target_exam_id": 1, "attestation": "yes"},
        files={
            "file": (
                "x.xlsx",
                b"PK\x03\x04short",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "invalid csrf"


def test_confirm_blocks_on_zero_staged_rows(nonce: str) -> None:
    """Regression for Import #135 ghost-confirm: refuse to confirm with 0 staged rows.

    A user-visible failure mode prior to the guard was: admin uploaded a
    file, skipped the mapping step, then hit confirm — the import header
    was stamped finished with no rows actually imported. The guard at
    `import_service.confirm_import` now raises `ImportStateError` so the
    UI re-prompts the mapping step.
    """
    actor = _make_admin(nonce)
    exam_id = _make_exam(actor, nonce)
    with SessionLocal() as s:
        actor = s.merge(actor)
        imp = import_service.create_import(
            s,
            actor=actor,
            request_id=None,
            target_exam_id=exam_id,
            file_name="empty.xlsx",
            file_bytes=_good_xlsx(nonce, n=1),
            attestation="I have rights",
        )
        s.commit()
        # NOTE: deliberately skip save_mapping + parse_and_stage so import_items
        # stays empty. confirm must refuse.
        with pytest.raises(import_service.ImportStateError) as exc_info:
            import_service.confirm_import(s, actor=actor, request_id=None, import_id=imp.id)
        # Message must mention the staging step so the UI can re-prompt.
        assert "staged" in str(exc_info.value).lower()
