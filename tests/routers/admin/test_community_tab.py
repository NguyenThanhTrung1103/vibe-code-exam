"""Phase 16a — admin community tab route (read-only).

Real-DB-gated by `EXAM_PLATFORM_TEST_REAL_DB=1`. Skipped by default so
the hermetic suite stays fast and prod databases stay untouched.

Covers:
  * RBAC: anonymous → 401, student → 403, admin → 200.
  * Empty state when question has no CDS rows.
  * Three-section render when question has CDS rows.
  * Vote bars rendered (CSS markup); raw JSON NOT rendered.
  * 404 for missing or soft-deleted question.
  * Ordering: high confidence first, then created_at desc.
  * Cap at 20 rows with truncation notice when exceeded.

Each test creates an isolated provider→course→exam→question→CDS chain and
cleans it up via the autouse `_cleanup_phase16a` fixture (slug prefix
`p16t-` makes scope filtering trivial).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.main import create_app
from app.models.catalog import Course, Exam, Provider
from app.models.community import (
    CommunityConfidence,
    CommunityConsensus,
    CommunityDiscussionSource,
    CommunityFetchStatus,
    CommunitySourceName,
)
from app.models.enums import (
    ConfidenceLevel,
    ExamPublishStatus,
    QuestionStatus,
    QuestionType,
    UserRole,
    Visibility,
)
from app.models.questions import Question
from app.models.users import User
from app.redis_client import get_redis

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
def client(app_real) -> Generator[TestClient, None, None]:
    with TestClient(app_real) as c:
        yield c


@pytest.fixture()
def nonce() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def _flush_login_rate_limits() -> Generator[None, None, None]:
    r = get_redis()
    for key in r.scan_iter(match="rl:*"):
        r.delete(key)
    yield


@pytest.fixture(autouse=True)
def _cleanup_phase16a() -> Generator[None, None, None]:
    """Tear-down: delete every catalog/question/CDS row this file created."""
    yield
    with SessionLocal() as s:
        provider_ids = list(s.scalars(select(Provider.id).where(Provider.slug.like("p16t-%"))))
        if provider_ids:
            course_ids = list(
                s.scalars(select(Course.id).where(Course.provider_id.in_(provider_ids)))
            )
            exam_ids = list(
                s.scalars(select(Exam.id).where(Exam.course_id.in_(course_ids or [-1])))
            )
            question_ids = list(
                s.scalars(select(Question.id).where(Question.exam_id.in_(exam_ids or [-1])))
            )
            if question_ids:
                s.execute(
                    delete(CommunityDiscussionSource).where(
                        CommunityDiscussionSource.question_id.in_(question_ids)
                    )
                )
                s.execute(delete(Question).where(Question.id.in_(question_ids)))
            if exam_ids:
                s.execute(delete(Exam).where(Exam.id.in_(exam_ids)))
            if course_ids:
                s.execute(delete(Course).where(Course.id.in_(course_ids)))
            s.execute(delete(Provider).where(Provider.id.in_(provider_ids)))
        # Wipe test users
        s.execute(delete(User).where(User.email.like("%@p16test.local")))
        s.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(nonce: str, role: UserRole) -> User:
    from app.auth.service import register_user

    with SessionLocal() as s:
        u = register_user(
            s,
            email=f"{role.value}-{nonce}@p16test.local",
            username=f"u{role.value[:3]}{nonce}",
            password="Phase16-good-pw",
            role=role,
            request_id=None,
        )
        s.commit()
        return s.get(User, u.id)


def _login(client: TestClient, user: User) -> None:
    csrf = client.get("/auth/login").cookies.get("exam_csrf")
    r = client.post(
        "/auth/login",
        data={
            "identifier": user.email,
            "password": "Phase16-good-pw",
            "csrf_token": csrf,
        },
    )
    assert r.status_code in (200, 302), f"login failed: {r.status_code}"


def _make_question(nonce: str, given_answer: str | None = "A") -> int:
    """Create a provider→course→exam→question chain. Returns question_id."""
    with SessionLocal() as s:
        provider = Provider(name=f"P{nonce}", slug=f"p16t-{nonce}")
        s.add(provider)
        s.flush()
        course = Course(provider_id=provider.id, name="C", slug=f"p16tc-{nonce}")
        s.add(course)
        s.flush()
        exam = Exam(
            course_id=course.id,
            name="E",
            slug=f"p16te-{nonce}",
            exam_version=1,
            visibility=Visibility.private,
            publish_status=ExamPublishStatus.draft,
        )
        s.add(exam)
        s.flush()
        q = Question(
            exam_id=exam.id,
            question_text="Phase 16a smoke",
            question_type=QuestionType.single,
            status=QuestionStatus.imported,
            confidence_level=ConfidenceLevel.unknown,
            verification_ttl_days=90,
            needs_human_review=False,
            given_answer=given_answer,
        )
        s.add(q)
        s.flush()
        s.commit()
        return q.id


def _add_cds(
    question_id: int,
    *,
    source_url: str,
    confidence: CommunityConfidence = CommunityConfidence.unknown,
    consensus: CommunityConsensus = CommunityConsensus.unknown,
    community_answer: str | None = None,
    vote_distribution: dict[str, int] | None = None,
    discussion_count: int | None = None,
    summary: str | None = None,
) -> int:
    with SessionLocal() as s:
        cds = CommunityDiscussionSource(
            question_id=question_id,
            source_name=CommunitySourceName.examtopics,
            source_url=source_url,
            external_question_id=None,
            discussion_count=discussion_count,
            vote_distribution=vote_distribution,
            total_votes=sum(vote_distribution.values()) if vote_distribution else None,
            fetch_status=CommunityFetchStatus.pending,
            community_answer=community_answer,
            community_confidence=confidence,
            community_consensus=consensus,
            summary=summary,
        )
        s.add(cds)
        s.flush()
        cds_id = cds.id
        s.commit()
        return cds_id


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_anonymous_returns_401(client: TestClient) -> None:
    r = client.get("/admin/questions/1/community")
    assert r.status_code == 401


def test_student_returns_403(client: TestClient, nonce: str) -> None:
    student = _make_user(nonce, UserRole.student)
    _login(client, student)
    qid = _make_question(nonce)
    r = client.get(f"/admin/questions/{qid}/community")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Happy path + empty state
# ---------------------------------------------------------------------------


def test_admin_with_no_cds_renders_empty_state(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    _login(client, admin)
    qid = _make_question(nonce)
    r = client.get(f"/admin/questions/{qid}/community")
    assert r.status_code == 200
    body = r.text
    assert "No community data for this question." in body
    assert "Community Signal — not authoritative" in body


def test_admin_with_cds_renders_three_sections_and_vote_bars(
    client: TestClient, nonce: str
) -> None:
    admin = _make_user(nonce, UserRole.admin)
    _login(client, admin)
    qid = _make_question(nonce, given_answer="A")
    _add_cds(
        qid,
        source_url="https://www.examtopics.com/discussions/x",
        confidence=CommunityConfidence.high,
        consensus=CommunityConsensus.disagrees_with_given,
        community_answer="D",
        vote_distribution={"A": 21, "D": 6},
        discussion_count=12,
        summary="Brief summary text.",
    )
    r = client.get(f"/admin/questions/{qid}/community")
    assert r.status_code == 200
    body = r.text
    # Three section labels.
    assert ">Answer<" in body
    assert ">Community Insight<" in body
    assert ">Metadata<" in body
    # Vote bar markup, NOT raw JSON.
    assert "vote-bar" in body
    assert '{"A": 21, "D": 6}' not in body
    assert '{"A":21,"D":6}' not in body
    # Conflict warning since given=A but community=D.
    assert "Conflict" in body
    # Confidence + fetch status badges.
    assert ">high<" in body
    assert ">pending<" in body
    # Source link with safe rel attributes.
    assert 'rel="noopener noreferrer nofollow"' in body
    assert 'target="_blank"' in body
    # Summary plain-text.
    assert "Brief summary text." in body


def test_summary_xss_is_autoescaped(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    _login(client, admin)
    qid = _make_question(nonce)
    _add_cds(
        qid,
        source_url="https://www.examtopics.com/discussions/y",
        summary="<script>alert(1)</script>NOT_A_REAL_TAG",
    )
    r = client.get(f"/admin/questions/{qid}/community")
    assert r.status_code == 200
    # Raw script tag must NOT appear in body — autoescape converts < to &lt;
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text


# ---------------------------------------------------------------------------
# 404 paths
# ---------------------------------------------------------------------------


def test_missing_question_returns_404(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    _login(client, admin)
    r = client.get("/admin/questions/999999999/community")
    assert r.status_code == 404


def test_soft_deleted_question_returns_404(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    _login(client, admin)
    qid = _make_question(nonce)
    # Soft-delete the question.
    with SessionLocal() as s:
        from datetime import UTC, datetime

        q = s.get(Question, qid)
        assert q is not None
        q.deleted_at = datetime.now(UTC)
        s.commit()
    r = client.get(f"/admin/questions/{qid}/community")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Ordering + truncation
# ---------------------------------------------------------------------------


def test_orders_by_confidence_desc_then_created_at_desc(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    _login(client, admin)
    qid = _make_question(nonce)
    # Add a low-confidence row first, then high — high should appear first
    # in the rendered HTML even though it was inserted last.
    low_id = _add_cds(
        qid,
        source_url="https://www.examtopics.com/discussions/low",
        confidence=CommunityConfidence.low,
    )
    high_id = _add_cds(
        qid,
        source_url="https://www.examtopics.com/discussions/high",
        confidence=CommunityConfidence.high,
    )
    r = client.get(f"/admin/questions/{qid}/community")
    assert r.status_code == 200
    body = r.text
    high_idx = body.find(f"cds-{high_id}")
    low_idx = body.find(f"cds-{low_id}")
    assert high_idx > 0 and low_idx > 0
    assert high_idx < low_idx, "high-confidence card must render before low"


def test_caps_at_twenty_rows_with_truncation_notice(client: TestClient, nonce: str) -> None:
    admin = _make_user(nonce, UserRole.admin)
    _login(client, admin)
    qid = _make_question(nonce)
    # Insert 25 distinct CDS rows for the same question.
    for i in range(25):
        _add_cds(
            qid,
            source_url=f"https://www.examtopics.com/discussions/n{i:03d}",
        )
    r = client.get(f"/admin/questions/{qid}/community")
    assert r.status_code == 200
    body = r.text
    assert "Showing first 20 of 25 sources." in body
    # Card count: count occurrences of `community-card` div openings.
    assert body.count('class="community-card"') == 20
