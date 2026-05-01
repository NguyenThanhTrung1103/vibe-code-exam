"""Real-DB smoke test — Phase 02.

Skipped unless `EXAM_PLATFORM_TEST_REAL_DB=1` is set in the environment AND
`DATABASE_URL` points at a Postgres instance with the migrated schema.

Inserts one of every Phase 1 active entity inside a transaction, then ROLLS
BACK so seed data and the schema state stay clean. The transaction is
**always** rolled back, even if assertions pass — we only need to prove that
inserts respect FK / NOT NULL / UNIQUE / type constraints.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Attempt,
    AttemptAnswer,
    AuditLog,
    Course,
    Exam,
    Import,
    ImportItem,
    ProductVersion,
    Provider,
    Question,
    QuestionExplanation,
    QuestionOption,
    QuestionReport,
    SourceDomain,
    Topic,
    User,
)
from app.models.enums import (
    ActorType,
    AttemptMode,
    ConfidenceLevel,
    ExamPublishStatus,
    ExplanationStatus,
    ImportItemStatus,
    ImportPublishStatus,
    ImportStatus,
    QuestionStatus,
    QuestionType,
    ReportReason,
    ReportStatus,
    SourceType,
    StaleStatus,
    TrustLevel,
    UserRole,
    Visibility,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("EXAM_PLATFORM_TEST_REAL_DB") != "1",
    reason="real-DB smoke test gated by EXAM_PLATFORM_TEST_REAL_DB=1",
)


@pytest.fixture(scope="module")
def real_engine():
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def rollback_session(real_engine):
    """Yields a session bound to a connection in a transaction that always rolls back."""
    connection = real_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, autocommit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_full_entity_graph_inserts_and_rolls_back(rollback_session: Session) -> None:
    s = rollback_session
    nonce = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)

    # users
    user = User(
        email=f"smoke-{nonce}@example.com",
        username=f"smoke-{nonce}",
        password_hash="argon2-placeholder",
        role=UserRole.admin,
    )
    s.add(user)
    s.flush()

    # catalog: provider → product_version + course → exam → topic
    provider = Provider(name=f"Smoke-{nonce}", slug=f"smoke-{nonce}")
    s.add(provider)
    s.flush()

    pv = ProductVersion(
        provider_id=provider.id,
        product_name="SmokeOS",
        product_version="1.0",
    )
    s.add(pv)

    course = Course(
        provider_id=provider.id,
        name=f"Smoke Course {nonce}",
        slug=f"smoke-course-{nonce}",
    )
    s.add(course)
    s.flush()

    exam = Exam(
        course_id=course.id,
        name=f"Smoke Exam {nonce}",
        slug=f"smoke-exam-{nonce}",
        exam_version=1,
        visibility=Visibility.private,
        publish_status=ExamPublishStatus.draft,
    )
    s.add(exam)
    s.flush()

    topic = Topic(
        exam_id=exam.id,
        name="Smoke Topic",
        slug=f"smoke-topic-{nonce}",
    )
    s.add(topic)
    s.flush()

    # imports + import_items (Phase 02 plan addition)
    imp = Import(
        uploaded_by=user.id,
        file_name=f"smoke-{nonce}.xlsx",
        file_type="xlsx",
        status=ImportStatus.uploaded,
        visibility=Visibility.private,
        publish_status=ImportPublishStatus.draft,
        duplicates_detected=0,
    )
    s.add(imp)
    s.flush()

    item = ImportItem(
        import_id=imp.id,
        row_number=1,
        sheet_name="Sheet1",
        raw_data={"q": "raw"},
        normalized_data={"q": "norm"},
        status=ImportItemStatus.parsed,
        content_hash="0" * 64,
    )
    s.add(item)
    s.flush()

    # question with source_locator JSONB (Phase 02 plan addition)
    question = Question(
        exam_id=exam.id,
        topic_id=topic.id,
        question_text="What is 2 + 2?",
        question_type=QuestionType.single,
        question_version=1,
        product_version_id=pv.id,
        status=QuestionStatus.imported,
        source_import_id=imp.id,
        given_answer="A",
        confidence_level=ConfidenceLevel.unknown,
        needs_human_review=False,
        verification_ttl_days=90,
        stale_status=StaleStatus.fresh,
        source_locator={
            "import_id": imp.id,
            "import_item_id": item.id,
            "file_name": imp.file_name,
            "sheet_name": item.sheet_name,
            "row_number": item.row_number,
        },
    )
    s.add(question)
    s.flush()

    # question_options
    s.add_all(
        [
            QuestionOption(
                question_id=question.id,
                label="A",
                option_text="4",
                is_correct=True,
                order_index=1,
            ),
            QuestionOption(
                question_id=question.id,
                label="B",
                option_text="3",
                is_correct=False,
                order_index=2,
            ),
        ]
    )

    # question_explanations
    s.add(
        QuestionExplanation(
            question_id=question.id,
            overall_explanation="Basic arithmetic.",
            status=ExplanationStatus.draft,
        )
    )

    # source_domains (separate insert; seeded in 0002 also exists)
    sd = SourceDomain(
        domain=f"smoke-{nonce}.example.com",
        source_type=SourceType.docs_other,
        trust_level=TrustLevel.low,
    )
    s.add(sd)

    # attempts + attempt_answers (with order_index NEW)
    attempt = Attempt(
        user_id=user.id,
        exam_id=exam.id,
        exam_version=1,
        mode=AttemptMode.practice,
        started_at=now,
    )
    s.add(attempt)
    s.flush()

    answer = AttemptAnswer(
        attempt_id=attempt.id,
        question_id=question.id,
        question_version=1,
        selected_options="A",
        is_correct=True,
        order_index=1,
        flagged=False,
    )
    s.add(answer)
    s.flush()

    # question_reports
    s.add(
        QuestionReport(
            question_id=question.id,
            user_id=user.id,
            reason=ReportReason.typo,
            status=ReportStatus.open,
        )
    )

    # audit_logs
    s.add(
        AuditLog(
            actor_type=ActorType.user,
            actor_id=user.id,
            action="question.created",
            entity_type="question",
            entity_id=question.id,
            new_value={"id": question.id},
            request_id=uuid.uuid4(),
        )
    )

    s.flush()

    # Sanity: round-trip the source_locator JSONB.
    fetched = s.get(Question, question.id)
    assert fetched is not None
    assert fetched.source_locator is not None
    assert fetched.source_locator["import_item_id"] == item.id

    # Sanity: order_index UNIQUE constraint.
    duplicate_order = AttemptAnswer(
        attempt_id=attempt.id,
        question_id=question.id,
        question_version=1,
        order_index=1,  # same as `answer` above → must error on flush
        flagged=False,
    )
    s.add(duplicate_order)
    with pytest.raises(IntegrityError):
        s.flush()
    s.rollback()  # rollback the SAVEPOINT-equivalent inside the outer txn
