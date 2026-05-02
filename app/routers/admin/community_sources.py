"""Phase 16a — admin community tab (read-only).

ONE GET route + one inline helper. No mutations, no audit emission, no CSRF
(read-only), no HTMX. Matches the strict-read-only refinement of the
prior Phase 16a plan; mutations land in Phase 16b.

Per refinement plan:
  * Column projection (13 columns) — not full ORM row.
  * ORDER BY community_confidence DESC, created_at DESC.
  * LIMIT 20 with truncation notice in template.
  * `format_vote_distribution` helper renders human-readable bars; no raw JSON.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select

from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.models.catalog import Exam
from app.models.community import CommunityDiscussionSource
from app.models.questions import Question
from app.routers.admin._common import templates

router = APIRouter(prefix="/admin/questions", tags=["admin", "community"])

_MAX_ROWS = 20


def format_vote_distribution(
    raw: dict[str, int] | None,
    community_pick: str | None,
) -> list[dict[str, Any]]:
    """Convert ``{"A": 21, "D": 6}`` into a render-ready list.

    Sorted by count DESC, then label ASC for deterministic output. Each
    item carries label / count / percent (1-decimal) / is_pick boolean.
    Empty / None input → empty list.
    """
    if not raw:
        return []
    total = sum(raw.values()) or 1  # all-zeros edge — avoid /0
    pick_upper = community_pick.upper() if isinstance(community_pick, str) else None
    items: list[dict[str, Any]] = [
        {
            "label": label,
            "count": count,
            "percent": round(100 * count / total, 1),
            "is_pick": pick_upper is not None and label.upper() == pick_upper,
        }
        for label, count in raw.items()
    ]
    items.sort(key=lambda x: (-x["count"], x["label"]))
    return items


@router.get("/{question_id}/community", response_class=HTMLResponse)
def get_community_tab(
    question_id: int,
    request: Request,
    user: RequireAdmin,  # noqa: ARG001 — RBAC dep, used by FastAPI
    session: SessionDep,
) -> HTMLResponse:
    """Render the community discussion tab for one question.

    404 if the question is missing or soft-deleted. Empty state when no
    CDS rows. Cap rendered rows at `_MAX_ROWS`; show truncation notice
    when total exceeds the cap.
    """
    q_row = session.execute(
        select(
            Question.id,
            Question.exam_id,
            Question.given_answer,
            Question.question_text,
        )
        .where(Question.id == question_id)
        .where(Question.deleted_at.is_(None))
    ).one_or_none()
    if q_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="question not found")

    exam_name = session.execute(
        select(Exam.name).where(Exam.id == q_row.exam_id)
    ).scalar_one_or_none()

    total_cds = session.execute(
        select(func.count())
        .select_from(CommunityDiscussionSource)
        .where(CommunityDiscussionSource.question_id == question_id)
    ).scalar_one()

    cds_rows = session.execute(
        select(
            CommunityDiscussionSource.id,
            CommunityDiscussionSource.source_name,
            CommunityDiscussionSource.source_url,
            CommunityDiscussionSource.external_question_id,
            CommunityDiscussionSource.discussion_count,
            CommunityDiscussionSource.vote_distribution,
            CommunityDiscussionSource.total_votes,
            CommunityDiscussionSource.fetch_status,
            CommunityDiscussionSource.community_answer,
            CommunityDiscussionSource.community_confidence,
            CommunityDiscussionSource.community_consensus,
            CommunityDiscussionSource.summary,
            CommunityDiscussionSource.created_at,
        )
        .where(CommunityDiscussionSource.question_id == question_id)
        .order_by(
            CommunityDiscussionSource.community_confidence.desc(),
            CommunityDiscussionSource.created_at.desc(),
        )
        .limit(_MAX_ROWS)
    ).all()

    cards = [_card_from_row(r, q_row.given_answer) for r in cds_rows]

    return templates.TemplateResponse(
        request,
        "admin/questions/community_tab.html",
        {
            "question_id": q_row.id,
            "question_text": q_row.question_text,
            "given_answer": q_row.given_answer,
            "exam_name": exam_name,
            "cards": cards,
            "total_cds": total_cds,
            "max_rows": _MAX_ROWS,
            "truncated": total_cds > _MAX_ROWS,
        },
    )


def _card_from_row(row: Any, given_answer: str | None) -> dict[str, Any]:
    """Reshape a SQLAlchemy `Row` into the template's per-card context."""
    votes = format_vote_distribution(row.vote_distribution, row.community_answer)
    return {
        "id": row.id,
        "source_name": row.source_name.value,
        "source_url": row.source_url,
        "external_question_id": row.external_question_id,
        "discussion_count": row.discussion_count,
        "votes": votes,
        "total_votes": row.total_votes,
        "fetch_status": row.fetch_status.value,
        "given_answer": given_answer,
        "community_answer": row.community_answer,
        "community_confidence": row.community_confidence.value,
        "community_consensus": row.community_consensus.value,
        "summary": row.summary,
        "created_at": row.created_at,
        "answer_conflict": (
            given_answer is not None
            and row.community_answer is not None
            and given_answer.upper() != row.community_answer.upper()
        ),
    }


__all__ = ["router", "format_vote_distribution"]
