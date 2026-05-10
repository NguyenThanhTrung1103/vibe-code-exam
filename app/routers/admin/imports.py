"""Admin Excel-import wizard.

Step 1  GET/POST /admin/imports                  upload
Step 2  GET/POST /admin/imports/{id}/mapping     column mapping
Step 3  GET/POST /admin/imports/{id}/preview     preview + row toggle
Step 4  POST    /admin/imports/{id}/confirm     finalize
        GET     /admin/imports/{id}/done        summary
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import func, select, text

from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.catalog import Course, Exam, Provider
from app.models.enums import ImportItemStatus
from app.models.imports import Import, ImportItem
from app.models.questions import Question
from app.routers.admin._common import (
    flash_error,
    render_with_csrf,
    require_csrf,
    templates,
)
from app.schemas.catalog import ExamCreate
from app.schemas.import_form import ImportUploadForm
from app.security.rate_limits import RL_ADMIN_IMPORT
from app.services import catalog_service, import_service
from app.services.excel_parser import auto_map, read_headers

router = APIRouter(prefix="/admin/imports", tags=["admin", "imports"])


# Canonical fields, grouped for the mapping page UI. Order matters in the UI.
_REQUIRED_FIELDS: tuple[str, ...] = ("question_text", "option_a", "option_b", "correct_answer")
_COMMUNITY_FIELDS: tuple[str, ...] = (
    "discussion_url",
    "external_question_id",
    "discussion_count",
    "vote_a",
    "vote_b",
    "vote_c",
    "vote_d",
    "vote_e",
    "vote_f",
    "vote_g",
    "vote_h",
)
_OPTIONAL_FIELDS: tuple[str, ...] = (
    "option_c",
    "option_d",
    "option_e",
    "option_f",
    "option_g",
    "option_h",
    # Alternative to option_a/b/.../h: a single dump-style cell containing
    # all options separated by `;` / `；` / newlines. Surfacing it under the
    # "Optional metadata" group keeps the required-fields card focused on
    # the canonical question_text / option_a / option_b shape.
    "combined_options",
    "question_type",
    "difficulty",
    "topic",
    "explanation",
    "reference",
    "tags",
)
_ALL_CANONICAL_FIELDS: tuple[str, ...] = _REQUIRED_FIELDS + _COMMUNITY_FIELDS + _OPTIONAL_FIELDS


# ---------------------------------------------------------------------------
# Step 1 — upload
# ---------------------------------------------------------------------------


class _InlineExamError(ValueError):
    """Raised when the inline +new-exam fields can't be resolved into an Exam."""


def _create_exam_from_inline_fields(
    session,
    *,
    actor,
    request_id: str | None,
    exam_name: str,
    course_name: str,
) -> int:
    """Resolve "+ Create new exam" inline fields → Exam id.

    Mirrors the flat catalog flow in `app.routers.admin.exams.create_exam`:
    auto-creates Provider+Course by course/provider name (idempotent on slug),
    then creates the Exam under that course. Slug derives from `exam_name`.
    """
    exam_name_clean = (exam_name or "").strip()
    course_name_clean = (course_name or "").strip()
    if not exam_name_clean or not course_name_clean:
        raise _InlineExamError(
            "exam name and course/provider are required when creating a new exam"
        )
    try:
        course = catalog_service.get_or_create_course_by_name(
            session,
            actor=actor,
            request_id=request_id,
            course_name=course_name_clean,
        )
    except catalog_service.DuplicateSlugError as exc:
        raise _InlineExamError(str(exc)) from exc

    try:
        payload = ExamCreate.model_validate(
            {"course_id": course.id, "name": exam_name_clean, "slug": None}
        )
    except ValidationError as exc:
        raise _InlineExamError(str(exc.errors()[0]["msg"])) from exc
    assert payload.slug is not None  # set by ExamCreate validator

    try:
        exam = catalog_service.create_exam(
            session,
            actor=actor,
            request_id=request_id,
            course_id=payload.course_id,
            name=payload.name,
            slug=payload.slug,
        )
    except catalog_service.DuplicateSlugError as exc:
        raise _InlineExamError(str(exc)) from exc
    session.flush()
    return exam.id


def _imported_question_counts(session: object, import_ids: list[int]) -> dict[int, int]:
    """Return live count of non-deleted, non-retired questions per source_import_id.

    Drives the 'Review questions' / 'No imported questions' affordance in the
    Recent imports table. Retired questions are excluded so the counter
    matches the pool that's actually eligible for new attempts (mirrors
    `publishable_question_filter`). Empty input → empty dict (one fewer
    round-trip).
    """
    if not import_ids:
        return {}
    rows = session.execute(  # type: ignore[attr-defined]
        select(Question.source_import_id, func.count(Question.id))
        .where(Question.source_import_id.in_(import_ids))
        .where(Question.deleted_at.is_(None))
        .where(Question.retired_at.is_(None))
        .group_by(Question.source_import_id)
    ).all()
    return {sid: cnt for sid, cnt in rows if sid is not None}


def _import_item_status_breakdown(
    session: object, import_ids: list[int]
) -> dict[int, dict[str, int]]:
    """Per-import counts of staged rows by `import_items.status` (ok / error / …)."""
    if not import_ids:
        return {}
    rows = session.execute(  # type: ignore[attr-defined]
        select(ImportItem.import_id, ImportItem.status, func.count(ImportItem.id))
        .where(ImportItem.import_id.in_(import_ids))
        .group_by(ImportItem.import_id, ImportItem.status)
    ).all()
    out: dict[int, dict[str, int]] = {}
    for iid, st, cnt in rows:
        bucket = out.setdefault(int(iid), {})
        bucket[st.value] = int(cnt)
    return out


def _exams_with_catalog(
    session: object, exam_ids: list[int]
) -> dict[int, tuple[Exam, Course, Provider]]:
    """Map exam_id → (Exam, Course, Provider) for table columns."""
    if not exam_ids:
        return {}
    uq = list({eid for eid in exam_ids if eid})
    if not uq:
        return {}
    rows = session.execute(  # type: ignore[attr-defined]
        select(Exam, Course, Provider)
        .join(Course, Exam.course_id == Course.id)
        .join(Provider, Course.provider_id == Provider.id)
        .where(Exam.id.in_(uq))
    ).all()
    return {e.id: (e, c, p) for e, c, p in rows}


@dataclass(frozen=True, slots=True)
class RecentImportRow:
    """One row in the Recent imports admin table (enriched for display)."""

    imp: Import
    exam: Exam | None
    course: Course | None
    provider: Provider | None
    in_bank: int
    item_counts: dict[str, int]

    @property
    def public_exam_path(self) -> str | None:
        if self.exam is None or self.provider is None:
            return None
        return f"/exams/{self.provider.slug}/{self.exam.slug}"


def _build_recent_import_rows(
    session: object,
    recent: list[Import],
    imported_counts: dict[int, int],
) -> list[RecentImportRow]:
    """Join target exam / catalog + staging counts for the upload page table."""
    ids = [r.id for r in recent]
    breakdown = _import_item_status_breakdown(session, ids)
    eids = [r.target_exam_id for r in recent if r.target_exam_id]
    catalog = _exams_with_catalog(session, eids)
    out: list[RecentImportRow] = []
    for imp in recent:
        pack = catalog.get(imp.target_exam_id) if imp.target_exam_id else None
        ex, co, pr = pack if pack else (None, None, None)
        out.append(
            RecentImportRow(
                imp=imp,
                exam=ex,
                course=co,
                provider=pr,
                in_bank=imported_counts.get(imp.id, 0),
                item_counts=breakdown.get(imp.id, {}),
            )
        )
    return out


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
    imported_counts = _imported_question_counts(session, [r.id for r in recent])
    recent_rows = _build_recent_import_rows(session, recent, imported_counts)
    return render_with_csrf(
        request,
        "admin/imports/upload.html",
        {
            "current_user": user,
            "exams": exams,
            "recent": recent,
            "recent_rows": recent_rows,
            "imported_counts": imported_counts,
            "error": None,
        },
    )


def _render_upload_with_error(
    request: Request, user: object, session: object, message: str
) -> HTMLResponse:
    """Re-render the upload page with an inline error banner."""
    exams = session.execute(  # type: ignore[attr-defined]
        select(Exam, Course, Provider)
        .join(Course, Exam.course_id == Course.id)
        .join(Provider, Course.provider_id == Provider.id)
        .where(Exam.deleted_at.is_(None))
        .order_by(Provider.name, Course.name, Exam.name)
    ).all()
    recent = list(session.scalars(select(Import).order_by(Import.id.desc()).limit(20)))  # type: ignore[attr-defined]
    imported_counts = _imported_question_counts(session, [r.id for r in recent])
    recent_rows = _build_recent_import_rows(session, recent, imported_counts)
    return render_with_csrf(
        request,
        "admin/imports/upload.html",
        {
            "current_user": user,
            "exams": exams,
            "recent": recent,
            "recent_rows": recent_rows,
            "imported_counts": imported_counts,
            "error": message,
        },
    )


@router.post("", dependencies=[Depends(RL_ADMIN_IMPORT)])
async def upload(
    request: Request,
    user: RequireAdmin,
    session: SessionDep,
    target_exam_id: str = Form(...),
    attestation: str = Form(...),
    csrf_token: str = Form(""),
    title: str = Form(""),
    new_exam_name: str = Form(""),
    new_course_name: str = Form(""),
    file: UploadFile = File(...),  # noqa: B008 — FastAPI marker
) -> Response:
    require_csrf(request, csrf_token)
    request_id = request.headers.get(REQUEST_ID_HEADER)
    # Resolve target exam: existing dropdown id OR sentinel "__new__" with
    # inline exam-name + course-name fields → auto-create provider+course+exam.
    if target_exam_id == "__new__":
        try:
            resolved_exam_id = _create_exam_from_inline_fields(
                session,
                actor=user,
                request_id=request_id,
                exam_name=new_exam_name,
                course_name=new_course_name,
            )
        except _InlineExamError as exc:
            return _render_upload_with_error(request, user, session, str(exc))
    else:
        try:
            resolved_exam_id = int(target_exam_id)
        except ValueError:
            return _render_upload_with_error(
                request, user, session, "invalid target_exam_id"
            )
    try:
        ImportUploadForm.model_validate(
            {"target_exam_id": resolved_exam_id, "attestation": attestation}
        )
    except ValidationError as exc:
        return _render_upload_with_error(request, user, session, str(exc.errors()[0]["msg"]))
    if file.filename is None:
        return _render_upload_with_error(request, user, session, "No file uploaded.")
    file_bytes = await file.read()
    try:
        imp = import_service.create_import(
            session,
            actor=user,
            request_id=request_id,
            target_exam_id=resolved_exam_id,
            file_name=file.filename,
            file_bytes=file_bytes,
            attestation=attestation,
            title=title,
        )
    except import_service.UploadValidationError as exc:
        return _render_upload_with_error(request, user, session, str(exc))
    # Multi-format dispatch: XLSX needs the column-mapping wizard; HTML /
    # PDF / TXT yield canonical rows from the adapter directly, so we
    # parse + stage immediately and skip straight to the preview.
    if imp.file_type == "xlsx":
        session.commit()
        return RedirectResponse(
            url=f"/admin/imports/{imp.id}/mapping",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        counts = import_service.parse_and_stage(
            session,
            actor=user,
            request_id=request_id,
            import_id=imp.id,
        )
    except (import_service.UploadValidationError, import_service.ImportStateError) as exc:
        session.rollback()
        return _render_upload_with_error(request, user, session, str(exc))
    session.commit()
    redirect = RedirectResponse(
        url=f"/admin/imports/{imp.id}/preview",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    redirect.headers["X-Import-Counts"] = json.dumps(counts)
    return redirect


# ---------------------------------------------------------------------------
# Step 2 — mapping
# ---------------------------------------------------------------------------


def _render_mapping(
    request: Request,
    user: object,
    session: object,
    import_id: int,
    *,
    override_mapping: dict[str, str | None] | None = None,
    error: str | None = None,
) -> HTMLResponse:
    """Render `mapping.html` with optional override mapping + error banner.

    `override_mapping` lets the POST handler preserve the admin's just-attempted
    selections when re-rendering after a validation failure (so the form state
    doesn't reset to whatever was last persisted on disk).
    """
    imp = session.get(Import, import_id)  # type: ignore[attr-defined]
    if imp is None or imp.file_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    sheet, headers = read_headers(imp.file_path)
    suggested = auto_map(headers)
    persisted = imp.column_mapping or {}
    for h in headers:
        if override_mapping is not None and h in override_mapping:
            suggested[h] = override_mapping[h]
        elif h in persisted:
            suggested[h] = persisted[h]
    mapped_fields = {v: k for k, v in suggested.items() if v}
    target_exam = (
        session.get(Exam, imp.target_exam_id) if imp.target_exam_id else None  # type: ignore[attr-defined]
    )
    return render_with_csrf(
        request,
        "admin/imports/mapping.html",
        {
            "current_user": user,
            "imp": imp,
            "sheet": sheet,
            "headers": headers,
            "suggested": suggested,
            "mapped_fields": mapped_fields,
            "target_exam": target_exam,
            "required_fields": _REQUIRED_FIELDS,
            "community_fields": _COMMUNITY_FIELDS,
            "optional_fields": _OPTIONAL_FIELDS,
            "all_canonical_fields": _ALL_CANONICAL_FIELDS,
            "error": error,
        },
    )


@router.get("/{import_id}/mapping")
def mapping_page(
    request: Request,
    import_id: int,
    user: RequireAdmin,
    session: SessionDep,
) -> Response:
    imp = session.get(Import, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # Adapter-based formats produce canonical rows directly — no mapping
    # step. Bounce straight to the preview.
    if imp.file_type and imp.file_type != "xlsx":
        return RedirectResponse(
            url=f"/admin/imports/{import_id}/preview",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return _render_mapping(request, user, session, import_id)


@router.post("/{import_id}/mapping")
async def save_mapping(
    request: Request,
    import_id: int,
    user: RequireAdmin,
    session: SessionDep,
) -> Response:
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
        # Re-render the mapping page (with the admin's just-attempted picks
        # preserved) instead of dropping them on a raw plain-text error page.
        session.rollback()
        return _render_mapping(
            request,
            user,
            session,
            import_id,
            override_mapping=column_mapping,
            error=str(exc),
        )
    except import_service.ImportStateError as exc:
        session.rollback()
        return _render_mapping(
            request,
            user,
            session,
            import_id,
            override_mapping=column_mapping,
            error=str(exc),
        )
    session.commit()

    redirect = RedirectResponse(
        url=f"/admin/imports/{import_id}/preview",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    redirect.headers["X-Import-Counts"] = json.dumps(counts)
    return redirect


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
    counts_rows = session.execute(
        select(ImportItem.status, func.count(ImportItem.id))
        .where(ImportItem.import_id == imp.id)
        .group_by(ImportItem.status)
    ).all()
    counts = {r[0].value: r[1] for r in counts_rows}

    target_exam = session.get(Exam, imp.target_exam_id) if imp.target_exam_id else None
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
            "target_exam": target_exam,
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


@router.post("/{import_id}/confirm")
def confirm(
    request: Request,
    import_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> Response:
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

    redirect = RedirectResponse(
        url=f"/admin/imports/{import_id}/done",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    redirect.headers["X-Confirm-Summary"] = json.dumps(summary)
    return redirect


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
    counts_rows = session.execute(
        select(ImportItem.status, func.count(ImportItem.id))
        .where(ImportItem.import_id == imp.id)
        .group_by(ImportItem.status)
    ).all()
    counts: dict[str, Any] = {r[0].value: r[1] for r in counts_rows}

    target_exam = session.get(Exam, imp.target_exam_id) if imp.target_exam_id else None
    # Read-only ad-hoc queries: first question id + community sources count for
    # this import. Avoid hard ORM coupling to the Question/CDS models — keeps
    # the import wizard module self-contained.
    first_q = session.execute(
        text(
            "SELECT id FROM questions WHERE source_import_id = :iid "
            "AND deleted_at IS NULL ORDER BY id ASC LIMIT 1"
        ),
        {"iid": imp.id},
    ).first()
    first_question_id = first_q[0] if first_q else None
    community_sources_count = (
        session.execute(
            text(
                "SELECT count(*) FROM community_discussion_sources "
                "WHERE question_id IN ("
                "  SELECT id FROM questions WHERE source_import_id = :iid"
                ")"
            ),
            {"iid": imp.id},
        ).scalar()
        or 0
    )

    return render_with_csrf(
        request,
        "admin/imports/done.html",
        {
            "current_user": user,
            "imp": imp,
            "counts": counts,
            "target_exam": target_exam,
            "first_question_id": first_question_id,
            "community_sources_count": community_sources_count,
        },
    )
