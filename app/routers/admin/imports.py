"""Admin Excel-import wizard.

Step 1  GET/POST /admin/imports                  upload
Step 2  GET/POST /admin/imports/{id}/mapping     column mapping
Step 3  GET/POST /admin/imports/{id}/preview     preview + row toggle
Step 4  POST    /admin/imports/{id}/confirm     finalize
        GET     /admin/imports/{id}/done        summary
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.catalog import Course, Exam, Provider
from app.models.enums import ImportItemStatus
from app.models.imports import Import, ImportItem
from app.routers.admin._common import (
    flash_error,
    render_with_csrf,
    require_csrf,
    templates,
)
from app.schemas.import_form import ImportUploadForm
from app.security.rate_limits import RL_ADMIN_IMPORT
from app.services import import_service
from app.services.excel_parser import auto_map, read_headers

router = APIRouter(prefix="/admin/imports", tags=["admin", "imports"])


# ---------------------------------------------------------------------------
# Step 1 — upload
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def upload_page(request: Request, user: RequireAdmin, session: SessionDep) -> HTMLResponse:
    exams = session.execute(
        select(Exam, Course, Provider)
        .join(Course, Exam.course_id == Course.id)
        .join(Provider, Course.provider_id == Provider.id)
        .where(Exam.deleted_at.is_(None))
        .order_by(Provider.name, Course.name, Exam.name)
    ).all()
    recent = list(session.scalars(select(Import).order_by(Import.id.desc()).limit(20)))
    return render_with_csrf(
        request,
        "admin/imports/upload.html",
        {"current_user": user, "exams": exams, "recent": recent},
    )


@router.post("", response_class=HTMLResponse, dependencies=[Depends(RL_ADMIN_IMPORT)])
async def upload(
    request: Request,
    user: RequireAdmin,
    session: SessionDep,
    target_exam_id: int = Form(...),
    attestation: str = Form(...),
    csrf_token: str = Form(""),
    file: UploadFile = File(...),  # noqa: B008 — FastAPI marker
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        ImportUploadForm.model_validate(
            {"target_exam_id": target_exam_id, "attestation": attestation}
        )
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    if file.filename is None:
        return flash_error(request, "no file uploaded")
    file_bytes = await file.read()
    try:
        imp = import_service.create_import(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            target_exam_id=target_exam_id,
            file_name=file.filename,
            file_bytes=file_bytes,
            attestation=attestation,
        )
    except import_service.UploadValidationError as exc:
        return flash_error(request, str(exc))
    session.commit()
    # Redirect to mapping step via HTMX HX-Redirect.
    response = HTMLResponse(content="", status_code=200)
    response.headers["HX-Redirect"] = f"/admin/imports/{imp.id}/mapping"
    response.headers["Location"] = f"/admin/imports/{imp.id}/mapping"
    return response


# ---------------------------------------------------------------------------
# Step 2 — mapping
# ---------------------------------------------------------------------------


@router.get("/{import_id}/mapping", response_class=HTMLResponse)
def mapping_page(
    request: Request,
    import_id: int,
    user: RequireAdmin,
    session: SessionDep,
) -> HTMLResponse:
    imp = session.get(Import, import_id)
    if imp is None or imp.file_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    sheet, headers = read_headers(imp.file_path)
    suggested = auto_map(headers)
    if imp.column_mapping:
        # Prefer admin's saved mapping if present.
        for h in headers:
            if h in imp.column_mapping:
                suggested[h] = imp.column_mapping[h]
    return render_with_csrf(
        request,
        "admin/imports/mapping.html",
        {
            "current_user": user,
            "imp": imp,
            "sheet": sheet,
            "headers": headers,
            "suggested": suggested,
        },
    )


@router.post("/{import_id}/mapping", response_class=HTMLResponse)
async def save_mapping(
    request: Request,
    import_id: int,
    user: RequireAdmin,
    session: SessionDep,
) -> HTMLResponse:
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    column_mapping: dict[str, str | None] = {}
    for k, v in form.items():
        if not k.startswith("map__"):
            continue
        header = k[len("map__") :]
        column_mapping[header] = (str(v).strip() or None) if v else None

    try:
        import_service.save_mapping(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            import_id=import_id,
            column_mapping=column_mapping,
        )
        # Run parse+stage immediately — keeps the wizard linear.
        counts = import_service.parse_and_stage(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            import_id=import_id,
        )
    except import_service.UploadValidationError as exc:
        return flash_error(request, str(exc))
    except import_service.ImportStateError as exc:
        return flash_error(request, str(exc))
    session.commit()

    response = HTMLResponse(content="", status_code=200)
    response.headers["HX-Redirect"] = f"/admin/imports/{import_id}/preview"
    response.headers["Location"] = f"/admin/imports/{import_id}/preview"
    response.headers["X-Import-Counts"] = json.dumps(counts)
    return response


# ---------------------------------------------------------------------------
# Step 3 — preview
# ---------------------------------------------------------------------------


_STATUS_FILTERS = {
    "all": None,
    "ok": ImportItemStatus.ok,
    "duplicates": ImportItemStatus.duplicate,
    "errors": ImportItemStatus.error,
    "warnings": ImportItemStatus.warning,
    "skipped": ImportItemStatus.skipped,
    "imported": ImportItemStatus.imported,
}


@router.get("/{import_id}/preview", response_class=HTMLResponse)
def preview_page(
    request: Request,
    import_id: int,
    user: RequireAdmin,
    session: SessionDep,
) -> HTMLResponse:
    imp = session.get(Import, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    f = request.query_params.get("filter", "all").lower()
    chosen = _STATUS_FILTERS.get(f)
    page = int(request.query_params.get("page", 1) or 1)
    page_size = 50

    stmt = select(ImportItem).where(ImportItem.import_id == imp.id)
    if chosen is not None:
        stmt = stmt.where(ImportItem.status == chosen)
    stmt = stmt.order_by(ImportItem.row_number).offset((page - 1) * page_size).limit(page_size)
    items = list(session.scalars(stmt))

    # Counts per status — single GROUP BY query.
    from sqlalchemy import func

    counts_rows = session.execute(
        select(ImportItem.status, func.count(ImportItem.id))
        .where(ImportItem.import_id == imp.id)
        .group_by(ImportItem.status)
    ).all()
    counts = {r[0].value: r[1] for r in counts_rows}

    return render_with_csrf(
        request,
        "admin/imports/preview.html",
        {
            "current_user": user,
            "imp": imp,
            "items": items,
            "filter": f,
            "page": page,
            "counts": counts,
        },
    )


@router.post("/{import_id}/items/{item_id}/toggle", response_class=HTMLResponse)
def toggle_item(
    request: Request,
    import_id: int,
    item_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        item = import_service.toggle_row(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            item_id=item_id,
        )
    except import_service.ImportStateError as exc:
        return flash_error(request, str(exc))
    except import_service.ImportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    return templates.TemplateResponse(request, "admin/imports/_row.html", {"item": item})


# ---------------------------------------------------------------------------
# Step 4 — confirm + done
# ---------------------------------------------------------------------------


@router.post("/{import_id}/confirm", response_class=HTMLResponse)
def confirm(
    request: Request,
    import_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        summary = import_service.confirm_import(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            import_id=import_id,
        )
    except import_service.ImportStateError as exc:
        return flash_error(request, str(exc))
    except import_service.ImportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()

    response = HTMLResponse(content="", status_code=200)
    response.headers["HX-Redirect"] = f"/admin/imports/{import_id}/done"
    response.headers["Location"] = f"/admin/imports/{import_id}/done"
    response.headers["X-Confirm-Summary"] = json.dumps(summary)
    return response


@router.get("/{import_id}/done", response_class=HTMLResponse)
def done(
    request: Request,
    import_id: int,
    user: RequireAdmin,
    session: SessionDep,
) -> HTMLResponse:
    imp = session.get(Import, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    from sqlalchemy import func

    counts_rows = session.execute(
        select(ImportItem.status, func.count(ImportItem.id))
        .where(ImportItem.import_id == imp.id)
        .group_by(ImportItem.status)
    ).all()
    counts: dict[str, Any] = {r[0].value: r[1] for r in counts_rows}
    return render_with_csrf(
        request,
        "admin/imports/done.html",
        {"current_user": user, "imp": imp, "counts": counts},
    )
