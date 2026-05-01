"""Admin-only paginated audit-log viewer (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select

from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.models.audit import AuditLog
from app.paths import TEMPLATES_DIR

router = APIRouter(prefix="/admin/audit", tags=["admin", "audit"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("", response_class=HTMLResponse)
def list_audit_logs_html(
    request: Request,
    user: RequireAdmin,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    entity_type: str | None = Query(None, max_length=64),
    actor_id: int | None = Query(None, ge=1),
) -> HTMLResponse:
    rows, total = _fetch(session, page, page_size, entity_type, actor_id)
    return templates.TemplateResponse(
        request,
        "admin/audit_list.html",
        {
            "current_user": user,
            "rows": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "entity_type": entity_type or "",
            "actor_id": actor_id or "",
            "has_next": (page * page_size) < total,
            "has_prev": page > 1,
        },
    )


@router.get(".json")
def list_audit_logs_json(
    user: RequireAdmin,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    entity_type: str | None = Query(None, max_length=64),
    actor_id: int | None = Query(None, ge=1),
) -> JSONResponse:
    rows, total = _fetch(session, page, page_size, entity_type, actor_id)
    return JSONResponse(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "rows": [
                {
                    "id": r.id,
                    "actor_type": r.actor_type.value if r.actor_type else None,
                    "actor_id": r.actor_id,
                    "action": r.action,
                    "entity_type": r.entity_type,
                    "entity_id": r.entity_id,
                    "reason": r.reason,
                    "request_id": str(r.request_id) if r.request_id else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
    )


def _fetch(
    session,
    page: int,
    page_size: int,
    entity_type: str | None,
    actor_id: int | None,
) -> tuple[list[AuditLog], int]:
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    stmt = stmt.order_by(desc(AuditLog.created_at)).offset((page - 1) * page_size).limit(page_size)

    rows = list(session.scalars(stmt))
    # cheap count — use COUNT(*) over the filtered set
    count_stmt = select(AuditLog.id)
    if entity_type:
        count_stmt = count_stmt.where(AuditLog.entity_type == entity_type)
    if actor_id:
        count_stmt = count_stmt.where(AuditLog.actor_id == actor_id)
    total = len(list(session.scalars(count_stmt)))
    return rows, total
