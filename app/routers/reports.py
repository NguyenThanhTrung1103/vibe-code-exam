"""Phase 08 — student-side question report endpoint.

POST /questions/{id}/reports — file a `question_reports` row.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.auth.csrf import verify_csrf
from app.auth.permissions import CurrentUser
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.enums import ActorType, ReportReason, ReportStatus
from app.models.questions import Question
from app.models.reports import QuestionReport
from app.paths import TEMPLATES_DIR
from app.schemas.report import QuestionReportForm
from app.security.rate_limits import RL_QUESTION_REPORT

router = APIRouter(prefix="/questions", tags=["reports"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.post(
    "/{question_id}/reports",
    response_class=HTMLResponse,
    dependencies=[Depends(RL_QUESTION_REPORT)],
)
def file_report(
    request: Request,
    question_id: int,
    user: CurrentUser,
    session: SessionDep,
    reason: str = Form(...),
    comment: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    if not verify_csrf(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid csrf")

    if session.get(Question, question_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="question not found")

    try:
        payload = QuestionReportForm.model_validate(
            {"reason": reason, "comment": (comment or None)}
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc.errors()[0]["msg"]),
        ) from exc

    row = QuestionReport(
        question_id=question_id,
        user_id=user.id,
        reason=ReportReason(payload.reason),
        comment=payload.comment,
        status=ReportStatus.open,
    )
    session.add(row)
    session.flush()

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=user.id,
        action=AuditAction.QUESTION_REPORT_FILED,
        entity_type="question_report",
        entity_id=row.id,
        new_value={
            "question_id": question_id,
            "reason": payload.reason,
            "comment": payload.comment,
        },
        request_id=request.headers.get(REQUEST_ID_HEADER),
    )
    session.commit()
    return templates.TemplateResponse(
        request,
        "reports/_filed.html",
        {"current_user": user, "report": row},
    )
