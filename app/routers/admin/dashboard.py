"""Admin home dashboard — quick navigation without memorizing URLs."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.models.catalog import Course, Exam, Provider
from app.models.imports import Import
from app.routers.admin._common import render_with_csrf
from app.routers.admin.imports import (
    RecentImportRow,
    _build_recent_import_rows,
    _imported_question_counts,
)

router = APIRouter(prefix="/admin", tags=["admin", "dashboard"])

_RECENT_IMPORT_LIMIT = 10
_RECENT_EXAM_LIMIT = 12


def _imports_needing_attention(rows: list[RecentImportRow]) -> list[RecentImportRow]:
    """Imports with staged row errors or header-level failed_questions."""
    out: list[RecentImportRow] = []
    for row in rows:
        err_staged = row.item_counts.get("error", 0)
        failed_hdr = row.imp.failed_questions or 0
        if err_staged > 0 or failed_hdr > 0:
            out.append(row)
    return out


@router.get("", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    user: RequireAdmin,
    session: SessionDep,
) -> HTMLResponse:
    """GET /admin — entry point for admin UI (cards + snapshot tables)."""
    recent = list(
        session.scalars(select(Import).order_by(Import.id.desc()).limit(_RECENT_IMPORT_LIMIT))
    )
    imported_counts = _imported_question_counts(session, [r.id for r in recent])
    recent_rows = _build_recent_import_rows(session, recent, imported_counts)
    attention = _imports_needing_attention(recent_rows)

    exam_rows = list(
        session.execute(
            select(Exam, Course, Provider)
            .join(Course, Exam.course_id == Course.id)
            .join(Provider, Course.provider_id == Provider.id)
            .where(Exam.deleted_at.is_(None))
            .order_by(Exam.updated_at.desc())
            .limit(_RECENT_EXAM_LIMIT)
        ).all()
    )

    return render_with_csrf(
        request,
        "admin/dashboard.html",
        {
            "current_user": user,
            "recent_rows": recent_rows,
            "import_attention": attention,
            "exam_rows": exam_rows,
        },
    )
