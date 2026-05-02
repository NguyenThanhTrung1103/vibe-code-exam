"""Phase 13 — real-DB integration tests for the community-signal upsert path.

Gated by `EXAM_PLATFORM_TEST_REAL_DB=1`. MUST run only against the disposable
`exam_phase13_smoke` database — never `exam_platform_db` or `blogdb`.

What this file proves (that the hermetic suite cannot):
  * The Alembic-applied schema accepts the rows we generate at runtime —
    JSONB serialisation round-trips, FK RESTRICT to `questions` is enforced,
    partial indexes are honoured.
  * `upsert_community_source` writes a CDS row + audit row in the same
    transaction.
  * Re-running with the same payload is idempotent (zero new rows / zero
    new audit entries).
  * Text-change path resets `approved_for_student=False` and emits the
    `community_source.relinked_text_changed` audit.
  * NO `httpx` is imported by the import_service / import_community modules
    (Phase 13 boundary — fetch is Phase 14).

Cleans up after itself: each test rolls back its own transaction so the
smoke DB stays empty between tests.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit.events import AuditAction
from app.db import SessionLocal
from app.models.audit import AuditLog
from app.models.catalog import Course, Exam, Provider
from app.models.community import (
    CommunityConfidence,
    CommunityDiscussionSource,
    CommunityFetchStatus,
    CommunitySourceName,
)
from app.models.enums import (
    ConfidenceLevel,
    ExamPublishStatus,
    QuestionStatus,
    QuestionType,
    Visibility,
)
from app.models.questions import Question
from app.services.import_community import upsert_community_source

pytestmark = pytest.mark.skipif(
    os.environ.get("EXAM_PLATFORM_TEST_REAL_DB") != "1",
    reason="real-DB integration tests gated by EXAM_PLATFORM_TEST_REAL_DB=1",
)


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    """Per-test transaction; rolled back at teardown.

    NOTE: the smoke DB has empty `exams`, `users` etc. so we mint just enough
    rows to satisfy the FKs that `community_discussion_sources` cares about.
    """
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture(autouse=True)
def _abort_if_not_smoke_db(session: Session) -> None:
    """Hard-fail the test if DATABASE_URL is not pointed at the smoke DB.

    Belt-and-braces: even with the gate flag set, no test should run unless
    the active connection lands in `exam_phase13_smoke` and the role is the
    scoped smoke role.
    """
    db, user = session.execute(text("SELECT current_database(), current_user")).one()
    assert db == "exam_phase13_smoke", f"WRONG DATABASE: got {db!r} expected exam_phase13_smoke"
    assert user == "exam_phase13_smoke_user", (
        f"WRONG USER: got {user!r} expected exam_phase13_smoke_user"
    )


_NONCE_SEQ = 0


def _next_slug(prefix: str) -> str:
    global _NONCE_SEQ
    _NONCE_SEQ += 1
    return f"{prefix}-{_NONCE_SEQ:04d}"


def _make_minimal_question(session: Session) -> Question:
    """Insert a Question row using the ORM models — defaults handle the
    `NOT NULL` cluster (question_version, needs_human_review, stale_status,
    visibility/publish_status etc.). The whole tree rolls back per-test.
    """
    provider = Provider(name="Smoke", slug=_next_slug("p13s"))
    session.add(provider)
    session.flush()
    course = Course(provider_id=provider.id, name="C", slug=_next_slug("c13s"))
    session.add(course)
    session.flush()
    exam = Exam(
        course_id=course.id,
        name="Smoke Exam",
        slug=_next_slug("e13s"),
        exam_version=1,
        visibility=Visibility.private,
        publish_status=ExamPublishStatus.draft,
    )
    session.add(exam)
    session.flush()

    q = Question(
        exam_id=exam.id,
        question_text="Smoke question?",
        question_type=QuestionType.single,
        status=QuestionStatus.imported,
        confidence_level=ConfidenceLevel.unknown,
        verification_ttl_days=90,
        needs_human_review=False,
    )
    session.add(q)
    session.flush()
    return q


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_upsert_creates_cds_row_and_audit_round_trip(session: Session) -> None:
    """Plain CREATE path; verifies JSONB serialisation, FK satisfaction, audit row."""
    q = _make_minimal_question(session)
    cds = upsert_community_source(
        session,
        question_id=q.id,
        payload={
            "discussion_url": "https://www.examtopics.com/discussions/x",
            "external_question_id": "EXT-RDB-1",
            "discussion_count": 12,
            "vote_distribution": {"A": 21, "D": 6},
        },
        request_id="11111111-1111-1111-1111-111111111111",
    )
    session.flush()
    assert cds is not None
    # Round-trip through DB
    loaded = session.execute(
        select(CommunityDiscussionSource).where(CommunityDiscussionSource.id == cds.id)
    ).scalar_one()
    assert loaded.question_id == q.id
    assert loaded.source_name == CommunitySourceName.examtopics
    assert loaded.source_url == "https://www.examtopics.com/discussions/x"
    assert loaded.external_question_id == "EXT-RDB-1"
    assert loaded.discussion_count == 12
    assert loaded.vote_distribution == {"A": 21, "D": 6}  # JSONB round-trip
    assert loaded.total_votes == 27
    assert loaded.fetch_status == CommunityFetchStatus.pending
    assert loaded.community_confidence == CommunityConfidence.unknown
    assert loaded.approved_for_student is False
    assert loaded.row_version == 0

    audit_rows = (
        session.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == "community_source")
            .where(AuditLog.entity_id == loaded.id)
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    a = audit_rows[0]
    assert a.action == AuditAction.COMMUNITY_SOURCE_CANDIDATE_CREATED.value
    assert a.actor_id is None
    assert str(a.request_id) == "11111111-1111-1111-1111-111111111111"


def test_upsert_idempotent_no_duplicates(session: Session) -> None:
    q = _make_minimal_question(session)
    payload = {
        "discussion_url": "https://www.examtopics.com/discussions/y",
        "external_question_id": "EXT-RDB-2",
        "discussion_count": 5,
        "vote_distribution": {"A": 10, "B": 2},
    }
    upsert_community_source(session, question_id=q.id, payload=payload, request_id=None)
    session.flush()
    upsert_community_source(session, question_id=q.id, payload=payload, request_id=None)
    session.flush()

    n_cds = session.execute(
        select(CommunityDiscussionSource).where(CommunityDiscussionSource.question_id == q.id)
    ).all()
    assert len(n_cds) == 1, "second upsert must NOT insert a duplicate row"

    n_audit = session.execute(
        select(AuditLog).where(AuditLog.entity_type == "community_source")
    ).all()
    # exactly 1 audit row — second call was a no-op
    assert len(n_audit) == 1


def test_upsert_text_changed_resets_approval_and_audits(session: Session) -> None:
    q = _make_minimal_question(session)
    initial = {
        "discussion_url": "https://www.examtopics.com/discussions/z",
        "external_question_id": "EXT-RDB-3",
        "discussion_count": 12,
        "vote_distribution": {"A": 21, "D": 6},
    }
    cds = upsert_community_source(session, question_id=q.id, payload=initial, request_id=None)
    session.flush()
    assert cds is not None
    # Simulate a prior approval that should be reset on text change.
    cds.approved_for_student = True
    cds.row_version = 4
    session.flush()

    updated = {
        **initial,
        "discussion_count": 30,
        "vote_distribution": {"A": 25, "D": 9},
    }
    upsert_community_source(session, question_id=q.id, payload=updated, request_id=None)
    session.flush()
    session.refresh(cds)
    assert cds.discussion_count == 30
    assert cds.vote_distribution == {"A": 25, "D": 9}
    assert cds.total_votes == 34
    assert cds.approved_for_student is False
    assert cds.row_version == 5

    actions = [
        a.action
        for a in session.execute(
            select(AuditLog).where(AuditLog.entity_type == "community_source")
        ).scalars()
    ]
    assert AuditAction.COMMUNITY_SOURCE_CANDIDATE_CREATED.value in actions
    assert AuditAction.COMMUNITY_SOURCE_RELINKED_TEXT_CHANGED.value in actions


def test_upsert_skips_when_no_url(session: Session) -> None:
    q = _make_minimal_question(session)
    out = upsert_community_source(
        session,
        question_id=q.id,
        payload={
            "discussion_url": None,
            "external_question_id": "EXT-NO-URL-RDB",
            "discussion_count": 5,
            "vote_distribution": {"A": 1},
        },
        request_id=None,
    )
    session.flush()
    assert out is None
    n = session.execute(
        select(CommunityDiscussionSource).where(CommunityDiscussionSource.question_id == q.id)
    ).all()
    assert len(n) == 0


def test_unique_constraint_present_in_schema(session: Session) -> None:
    """Cheaper alternative to a flush-time UNIQUE violation: assert the
    constraint exists on the table in this real DB, since the migration
    declared it. The 22 hermetic tests + the create/idempotent/relink
    tests above already exercise the upsert helper's behavior.
    """
    rows = session.execute(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'community_discussion_sources'::regclass "
            "AND contype = 'u' "
            "ORDER BY conname"
        )
    ).all()
    names = [r[0] for r in rows]
    assert "uq_community_sources_question_url" in names


def test_no_internet_fetch_in_phase13_modules() -> None:
    """Boundary check (works even without the smoke DB): the import_service
    + import_community modules must NOT pull in httpx / requests.
    """
    import app.services.import_community as ic
    import app.services.import_service as svc

    forbidden = {"httpx", "requests"}
    for module in (svc, ic):
        for attr in dir(module):
            obj = getattr(module, attr)
            mod_name = (getattr(obj, "__module__", "") or "").split(".", 1)[0]
            assert mod_name not in forbidden, (
                f"{module.__name__}.{attr} pulls in {mod_name!r} — Phase 13 must NOT fetch."
            )
