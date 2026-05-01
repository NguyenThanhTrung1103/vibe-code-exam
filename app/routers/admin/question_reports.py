"""Phase 08 — admin queue for question reports.

GET  /admin/question-reports                list (filter open/resolved/rejected)
POST /admin/question-reports/{id}/resolve   mark resolved + audit
POST /admin/question-reports/{id}/reject    mark rejected + audit
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.enums import ActorType, ReportStatus
from app.models.questions import Question
from app.models.reports import QuestionReport
from app.routers.admin._common import (
    render_with_csrf,
    require_csrf,
    templates,
)

router = APIRouter(prefix="/admin/question-reports", tags=["admin", "reports"])


@router.get("", response_class=HTMLResponse)
def list_reports(request: Request, user: RequireAdmin, session: SessionDep) -> HTMLResponse:
    f = request.query_params.get("status", "open").lower()
    page = int(request.query_params.get("page") or 1)
    page_size = 50

    stmt = select(QuestionReport, Question).join(
        Question, Question.id == QuestionReport.question_id
    )
    if f != "all":
        with contextlib.suppress(ValueError):
            stmt = stmt.where(QuestionReport.status == ReportStatus(f))
    stmt = stmt.order_by(QuestionReport.id.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = session.execute(stmt).all()
    return render_with_csrf(
        request,
        "admin/question_reports/list.html",
        {"current_user": user, "rows": rows, "filter": f, "page": page},
    )


@router.post("/{report_id}/resolve", response_class=HTMLResponse)
def mark_resolved(
    request: Request,
    report_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    return _set_status(
        session=session,
        report_id=report_id,
        new_status=ReportStatus.resolved,
        action=AuditAction.QUESTION_REPORT_RESOLVED,
        user=user,
        request=request,
    )


@router.post("/{report_id}/reject", response_class=HTMLResponse)
def mark_rejected(
    request: Request,
    report_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    return _set_status(
        session=session,
        report_id=report_id,
        new_status=ReportStatus.rejected,
        action=AuditAction.QUESTION_REPORT_REJECTED,
        user=user,
        request=request,
    )


def _set_status(
    *,
    session,
    report_id: int,
    new_status: ReportStatus,
    action: AuditAction,
    user,
    request: Request,
) -> HTMLResponse:
    row = session.get(QuestionReport, report_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    q = session.get(Question, row.question_id)
    if row.status == new_status:
        # idempotent — return current row partial unchanged.
        return templates.TemplateResponse(
            request,
            "admin/question_reports/_row.html",
            {"report": row, "q": q},
        )
    old = row.status.value
    row.status = new_status
    if new_status in (ReportStatus.resolved, ReportStatus.rejected):
        row.resolved_at = datetime.now(UTC)
    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=user.id,
        action=action,
        entity_type="question_report",
        entity_id=row.id,
        old_value={"status": old},
        new_value={"status": new_status.value},
        request_id=request.headers.get(REQUEST_ID_HEADER),
    )
    session.commit()
    return templates.TemplateResponse(
        request,
        "admin/question_reports/_row.html",
        {"report": row, "q": q},
    )
