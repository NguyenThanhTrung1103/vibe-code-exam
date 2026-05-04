"""Phase 05 — Excel-import orchestrator.

Funnels every state change through `write_audit_log()` in the same
session as the SQL write — same pattern as Phases 03 and 04.

Public surface (called by the admin router):

    create_import(...)        — store file + insert `imports` row.
    save_mapping(...)         — persist `column_mapping` JSONB.
    parse_and_stage(...)      — read the workbook, write `import_items`
                                rows, validate + dedup each.
    toggle_row(...)           — flip an item between `ok` and `skipped`
                                (used by the preview deselect/reselect).
    confirm_import(...)       — idempotently insert `questions` for every
                                item with `status='ok'`.

Errors:
    `ImportNotFoundError`, `ImportStateError`,
    `UploadValidationError`.
"""

from __future__ import annotations

import contextlib
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit.events import AuditAction
from app.audit.writer import write_audit_log
from app.config import get_settings
from app.models.catalog import Exam
from app.models.enums import (
    ActorType,
    ConfidenceLevel,
    ExplanationStatus,
    ImportItemStatus,
    ImportStatus,
    QuestionStatus,
    QuestionType,
    Visibility,
)
from app.models.imports import Import, ImportItem
from app.models.questions import (
    Question,
    QuestionExplanation,
    QuestionOption,
)
from app.models.users import User
from app.security.upload_validator import (
    XLSX_MAGIC as _XLSX_MAGIC_RE,  # re-export below
)
from app.security.upload_validator import (
    validate_upload_bytes,
)
from app.services.excel_parser import (
    CANONICAL_FIELDS,
    auto_map,
    read_headers,
    stream_rows,
)
from app.services.excel_parser import (
    ParsedRow as _ParsedRow,
)
from app.services.import_community import upsert_community_source
from app.services.import_dedup import content_hash, existing_question_hashes_for_exam
from app.services.import_normalizer import normalize_row
from app.services.import_validator import OPTION_LABELS, ValidationResult, validate_row
from app.services.parsers import detect_adapter as _detect_adapter

XLSX_MAGIC = _XLSX_MAGIC_RE  # zip header — `.xlsx` is a zip (Phase 09 owner: app.security)


class ImportNotFoundError(LookupError):
    pass


class ImportStateError(RuntimeError):
    pass


class UploadValidationError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 1. Upload + persist file
# ---------------------------------------------------------------------------


def create_import(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    target_exam_id: int,
    file_name: str,
    file_bytes: bytes,
    attestation: str,
    title: str | None = None,
) -> Import:
    """Validate the upload bytes, save the file, insert the `imports` row.

    `title` is an optional admin-supplied label; falls back to file_name in UI.
    Caller commits.
    """
    settings = get_settings()
    # Phase 09: extension + magic + size validation centralised in app.security.
    # Multi-format extension (Milestone 1): accept xlsx / html / pdf / txt.
    try:
        family = validate_upload_bytes(
            file_bytes,
            max_bytes=settings.import_max_bytes,
            filename=file_name,
        )
    except ValueError as exc:  # UploadValidationError is a ValueError subclass
        raise UploadValidationError(str(exc)) from exc

    safe_name = _sanitize_filename(file_name)
    exam = session.get(Exam, target_exam_id)
    if exam is None or exam.deleted_at is not None:
        raise UploadValidationError(f"exam {target_exam_id} not found")

    if not attestation or len(attestation.strip()) < 4:
        raise UploadValidationError("attestation required (≥4 chars)")

    title_clean = (title or "").strip() or None
    imp = Import(
        uploaded_by=actor.id,
        file_name=safe_name,
        file_type=family,
        target_exam_id=target_exam_id,
        status=ImportStatus.uploaded,
        import_source_claim=attestation.strip(),
        title=title_clean,
    )
    session.add(imp)
    session.flush()  # assign id

    # Save file at uploads_dir/imports/{import_id}.{ext} — keep the family
    # extension so the on-disk shape matches what parsers expect to open.
    ext_for_family = {"xlsx": ".xlsx", "html": ".html", "pdf": ".pdf", "txt": ".txt"}
    base = Path(settings.uploads_dir) / "imports"
    base.mkdir(parents=True, exist_ok=True)
    final_path = base / f"{imp.id}{ext_for_family.get(family, '.bin')}"
    final_path.write_bytes(file_bytes)
    # Some filesystems (Windows tests) don't honour POSIX perms.
    with contextlib.suppress(OSError):
        final_path.chmod(0o600)
    imp.file_path = str(final_path)

    # Run the format detector now that the file is on disk. Failure to
    # detect is non-fatal — admin can still proceed with the wizard and
    # the XLSX path always wins for `.xlsx` uploads via the alias map.
    try:
        adapter = _detect_adapter(filename=safe_name, file_path=final_path)
        if adapter is not None:
            imp.detected_format = adapter.name
    except Exception:  # noqa: BLE001 — detector failure must never block upload
        imp.detected_format = None

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.IMPORT_UPLOADED,
        entity_type="import",
        entity_id=imp.id,
        new_value={
            "file_name": safe_name,
            "target_exam_id": target_exam_id,
            "size_bytes": len(file_bytes),
        },
        request_id=request_id,
    )
    return imp


# ---------------------------------------------------------------------------
# 2. Header / mapping
# ---------------------------------------------------------------------------


def detect_headers(
    import_id_or_path: int | Path | str,
) -> tuple[str, list[str], dict[str, str | None]]:
    """Return `(sheet_name, headers, auto_mapping)`."""
    if isinstance(import_id_or_path, int):
        raise ValueError("pass a path, not an import id")
    sheet, headers = read_headers(import_id_or_path)
    return sheet, headers, auto_map(headers)


def required_mapping_missing(column_mapping: dict[str, str | None]) -> list[str]:
    """Return the list of missing required canonical fields for a mapping.

    Pure function — no DB access. Encodes the contract enforced by
    `save_mapping` and rendered by `admin/imports/mapping.html`:

      * `question_text` must be mapped.
      * `correct_answer` must be mapped.
      * Either both `option_a` and `option_b` are mapped individually,
        or `combined_options` is mapped (it is split into
        `option_a..option_f` at parse time).

    Empty list = mapping is valid. Used by tests to exercise the rule
    without a database session.
    """
    mapped_fields = {v for v in column_mapping.values() if v}
    has_options = "combined_options" in mapped_fields or (
        "option_a" in mapped_fields and "option_b" in mapped_fields
    )
    missing: list[str] = []
    for required_core in ("question_text", "correct_answer"):
        if required_core not in mapped_fields:
            missing.append(required_core)
    if not has_options:
        missing.append("option_a + option_b OR combined_options")
    return missing


def save_mapping(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    import_id: int,
    column_mapping: dict[str, str | None],
) -> Import:
    imp = _get_import_or_raise(session, import_id)
    # Reject mappings that don't cover all required canonical fields.
    # Either option_a+option_b OR combined_options satisfies the option
    # requirement — combined_options is split into option_a..f at parse time.
    missing = required_mapping_missing(column_mapping)
    if missing:
        raise UploadValidationError(f"mapping missing required fields: {missing}")
    # Validate every mapped value lands in the canonical set.
    for v in column_mapping.values():
        if v is not None and v not in CANONICAL_FIELDS:
            raise UploadValidationError(f"unknown canonical field {v!r}")

    imp.column_mapping = column_mapping
    imp.status = ImportStatus.needs_mapping
    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.IMPORT_MAPPING_SAVED,
        entity_type="import",
        entity_id=imp.id,
        new_value={"column_mapping": column_mapping},
        request_id=request_id,
    )
    return imp


# ---------------------------------------------------------------------------
# 3. Parse + stage rows
# ---------------------------------------------------------------------------


def parse_and_stage(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    import_id: int,
) -> dict[str, int]:
    """Read the file, write one `import_items` row per data row.

    Apply normalize → validate → within-import + cross-exam dedup. Returns
    a `{status -> count}` summary. Caller commits.

    Dispatch:
      * `file_type='xlsx'`  → legacy openpyxl streamer (needs column_mapping).
      * Anything else       → `app.services.parsers` adapter selected via the
                              detector at upload time.
    """
    imp = _get_import_or_raise(session, import_id)
    if not imp.target_exam_id:
        raise ImportStateError("target_exam_id missing")
    if not imp.file_path:
        raise ImportStateError("file_path missing")

    settings = get_settings()
    seen_hashes: dict[str, int] = {}  # hash -> earlier row_number
    cross_exam_hashes = existing_question_hashes_for_exam(session, exam_id=imp.target_exam_id)

    is_xlsx_family = (imp.file_type == "xlsx") or (imp.detected_format == "xlsx")
    if is_xlsx_family:
        if not imp.column_mapping:
            raise ImportStateError("column_mapping not set; call save_mapping first")
        row_iter = _xlsx_rows(imp, max_rows=settings.import_max_rows)
    else:
        row_iter = _adapter_rows(imp, max_rows=settings.import_max_rows)

    counts: dict[str, int] = {}
    parsed = 0
    for parsed_row in row_iter:
        parsed += 1
        normalized = normalize_row(parsed_row.raw)
        validation: ValidationResult = validate_row(normalized)
        h = content_hash(validation.canonical) if validation.canonical else None

        # Dedup overrides validation status (only when row is otherwise OK).
        dup_message: str | None = None
        if validation.status == ImportItemStatus.ok and h:
            if h in cross_exam_hashes:
                validation.status = ImportItemStatus.duplicate
                dup_message = "duplicate of an existing question in this exam"
            elif h in seen_hashes:
                validation.status = ImportItemStatus.duplicate
                dup_message = f"duplicate of row {seen_hashes[h]} earlier in this import"
            else:
                seen_hashes[h] = parsed_row.row_number

        item = ImportItem(
            import_id=imp.id,
            row_number=parsed_row.row_number,
            sheet_name=parsed_row.sheet_name,
            raw_data=_jsonable(parsed_row.raw),
            normalized_data=_jsonable(_canonical_to_jsonable(validation.canonical)),
            content_hash=h,
            status=validation.status,
            error_message=validation.error_message,
            warning_message=dup_message or validation.warning_message,
        )
        session.add(item)
        counts[validation.status.value] = counts.get(validation.status.value, 0) + 1

    imp.total_questions = parsed
    imp.parsed_questions = parsed
    imp.duplicates_detected = counts.get("duplicate", 0)
    imp.failed_questions = counts.get("error", 0)
    imp.status = ImportStatus.normalized

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.IMPORT_PARSED,
        entity_type="import",
        entity_id=imp.id,
        new_value={"counts": counts, "total": parsed},
        request_id=request_id,
    )
    # Flush so confirm_import (and any same-session SELECT) sees the just-added
    # import_items. Without this, autoflush=False keeps them in session.new only.
    session.flush()
    return counts


# ---------------------------------------------------------------------------
# 4. Preview row toggle (deselect / reselect)
# ---------------------------------------------------------------------------


def toggle_row(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    item_id: int,
) -> ImportItem:
    """Flip `ok` ↔ `skipped`. Other statuses are immutable here."""
    item = session.get(ImportItem, item_id)
    if item is None:
        raise ImportNotFoundError(f"import_item {item_id} not found")
    old = item.status.value
    if item.status == ImportItemStatus.ok:
        item.status = ImportItemStatus.skipped
    elif item.status == ImportItemStatus.skipped:
        item.status = ImportItemStatus.ok
    else:
        raise ImportStateError(f"cannot toggle item in status {old!r}; only ok/skipped")
    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.IMPORT_ROW_TOGGLED,
        entity_type="import_item",
        entity_id=item.id,
        old_value={"status": old},
        new_value={"status": item.status.value},
        request_id=request_id,
    )
    return item


# ---------------------------------------------------------------------------
# 5. Confirm — idempotent + partial-failure-tolerant
# ---------------------------------------------------------------------------


def confirm_import(
    session: Session,
    *,
    actor: User,
    request_id: str | None,
    import_id: int,
) -> dict[str, int]:
    """Insert questions for items with `status='ok' AND question_id IS NULL`.

    Idempotent — re-running on the same import yields zero new questions
    once items are flipped to `imported`.
    Partial-failure tolerant — per-item savepoint; on failure the item is
    marked `error` and the loop continues with the next item.
    """
    imp = _get_import_or_raise(session, import_id)
    if not imp.target_exam_id:
        raise ImportStateError("target_exam_id missing")

    # Guard: refuse to confirm an import with zero staged rows. Otherwise the
    # import header gets stamped 'ready_to_publish' with no actual data — see
    # Import #135 ghost-confirm post-mortem (2026-05-02).
    items_total = (
        session.scalar(select(func.count(ImportItem.id)).where(ImportItem.import_id == imp.id)) or 0
    )
    if items_total == 0:
        raise ImportStateError(
            "No rows were staged for this import. "
            "Please complete the mapping step before confirming."
        )

    items = list(
        session.scalars(
            select(ImportItem)
            .where(ImportItem.import_id == imp.id)
            .where(ImportItem.status == ImportItemStatus.ok)
            .where(ImportItem.question_id.is_(None))
            .order_by(ImportItem.row_number)
        )
    )

    summary = {"imported": 0, "errors": 0, "skipped": 0}
    for item in items:
        sp = session.begin_nested()  # savepoint
        try:
            question = _create_question_from_item(
                session,
                imp=imp,
                item=item,
                actor=actor,
                request_id=request_id,
            )
            item.question_id = question.id
            item.status = ImportItemStatus.imported
            sp.commit()
            summary["imported"] += 1
        except SQLAlchemyError as exc:
            sp.rollback()
            item.status = ImportItemStatus.error
            item.error_message = f"confirm failed: {exc.__class__.__name__}: {exc}"
            summary["errors"] += 1

    if summary["errors"]:
        imp.status = ImportStatus.partially_verified
        write_audit_log(
            session,
            actor_type=ActorType.user,
            actor_id=actor.id,
            action=AuditAction.IMPORT_PARTIAL_FAILURE,
            entity_type="import",
            entity_id=imp.id,
            new_value=summary,
            request_id=request_id,
        )
    else:
        imp.status = ImportStatus.ready_to_publish
    imp.finished_at = datetime.now(UTC)

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.IMPORT_CONFIRMED,
        entity_type="import",
        entity_id=imp.id,
        new_value=summary,
        request_id=request_id,
    )
    return summary


def _create_question_from_item(
    session: Session,
    *,
    imp: Import,
    item: ImportItem,
    actor: User,
    request_id: str | None,
) -> Question:
    canonical = item.normalized_data or {}
    options_raw = canonical.get("options") or []
    correct = canonical.get("correct_answer") or []

    qtype = canonical.get("question_type") or "single"

    question = Question(
        exam_id=imp.target_exam_id,
        topic_id=None,  # admin assigns in Phase 06; topic strings ignored here
        question_text=canonical.get("question_text") or "",
        question_type=QuestionType(qtype),
        difficulty=None,  # canonical has 'difficulty' string; mapping to enum below
        status=QuestionStatus.imported,
        content_hash=item.content_hash,
        given_answer=",".join(correct) if correct else None,
        confidence_level=ConfidenceLevel.unknown,
        source_locator={
            "import_id": imp.id,
            "import_item_id": item.id,
            "file_name": imp.file_name,
            "sheet_name": item.sheet_name,
            "row_number": item.row_number,
        },
        source_import_id=imp.id,
        verification_ttl_days=90,
    )
    diff = canonical.get("difficulty")
    if diff in ("easy", "medium", "hard"):
        from app.models.enums import QuestionDifficulty

        question.difficulty = QuestionDifficulty(diff)
    session.add(question)
    session.flush()

    # Options
    correct_set = set(correct)
    for idx, label in enumerate(OPTION_LABELS):
        # `options_raw` is list[[label, text]] (jsonable form).
        text = None
        for entry in options_raw:
            if isinstance(entry, list | tuple) and len(entry) == 2 and entry[0] == label:
                text = entry[1]
                break
        if not text:
            continue
        opt = QuestionOption(
            question_id=question.id,
            label=label,
            option_text=text,
            is_correct=label in correct_set,
            order_index=idx,
        )
        session.add(opt)

    # Overall explanation
    explanation_text = canonical.get("explanation")
    if explanation_text:
        session.add(
            QuestionExplanation(
                question_id=question.id,
                overall_explanation=explanation_text,
                status=ExplanationStatus.approved,
            )
        )

    # Reference URL — Phase 02's question_references model is more involved;
    # we record the URL in `error_log`-equivalent later when source_domain is
    # set up. For Phase 05 we keep the URL on the import_item normalized_data
    # already, and skip creating a `question_references` row that would
    # require matching `source_domains`. Phase 09 hardens this.
    _ = canonical.get("reference")  # noqa: F841

    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=actor.id,
        action=AuditAction.QUESTION_IMPORTED,
        entity_type="question",
        entity_id=question.id,
        new_value={
            "exam_id": imp.target_exam_id,
            "import_id": imp.id,
            "import_item_id": item.id,
            "content_hash": item.content_hash,
            "qtype": qtype,
            "correct": correct,
        },
        request_id=request_id,
    )

    # Phase 13 — community discussion source candidate (CDEA Sprint-1).
    # The validator stuck a JSONB-safe community payload onto canonical
    # when the row had any community columns. We upsert the CDS row in
    # the SAME transaction as the question + audit log; commit happens
    # at the caller (savepoint scope of `confirm_import`).
    community_payload = canonical.get("community")
    if community_payload:
        upsert_community_source(
            session,
            question_id=question.id,
            payload=community_payload,
            request_id=request_id,
        )

    # Default visibility/publish_status
    # Phase 02 model already uses defaults Visibility.private + ExamPublishStatus.draft
    # for `exams`. Questions have no visibility/publish_status columns; they
    # inherit visibility from their exam. Status begins at `imported` (above).
    _ = Visibility.private  # explicit reference for grep-ability.

    return question


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_import_or_raise(session: Session, import_id: int) -> Import:
    imp = session.get(Import, import_id)
    if imp is None:
        raise ImportNotFoundError(f"import {import_id} not found")
    return imp


# ---------------------------------------------------------------------------
# Row stream helpers — XLSX (legacy) vs adapter (Milestone 1 multi-format)
# ---------------------------------------------------------------------------


def _xlsx_rows(imp: Import, *, max_rows: int):
    """Stream rows from an XLSX import via the existing column-mapping pipeline."""
    if imp.file_path is None:
        raise ImportStateError("file_path missing for XLSX import")
    yield from stream_rows(
        imp.file_path,
        column_mapping=imp.column_mapping or {},
        max_rows=max_rows,
    )


def _adapter_rows(imp: Import, *, max_rows: int):
    """Stream rows from a non-XLSX import via the parser-adapter detector.

    Yields `ParsedRow` objects so the rest of `parse_and_stage` is dispatch-
    agnostic. `sheet_name` is set to the adapter family so the preview UI
    still has something to show; `row_number` is monotonically incremented
    starting at 2 to mirror XLSX (row 1 = header).
    """
    file_path = Path(imp.file_path or "")
    adapter = _detect_adapter(filename=imp.file_name, file_path=file_path)
    if adapter is None:
        raise ImportStateError(
            f"no parser adapter could claim {imp.file_name!r} "
            f"(detected_format={imp.detected_format!r}, file_type={imp.file_type!r})"
        )
    for seen, (idx, row) in enumerate(
        enumerate(adapter.parse(file_path=file_path), start=2), start=1
    ):
        if seen > max_rows:
            raise ValueError(f"too many data rows (>{max_rows})")
        yield _ParsedRow(sheet_name=adapter.name, row_number=idx, raw=dict(row))


def _sanitize_filename(name: str) -> str:
    """Strip path components + non-printable chars; cap length."""
    base = Path(name).name  # drop directory traversal segments
    base = "".join(ch for ch in base if ch.isprintable() and ch not in ('"', "<", ">", "|"))
    base = base.strip().lstrip(".")
    if not base:
        base = f"upload-{secrets.token_hex(4)}.xlsx"
    if len(base) > 200:
        base = base[-200:]
    return base


def _jsonable(value: Any) -> Any:
    """Coerce arbitrary parser values into JSONB-safe primitives."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _canonical_to_jsonable(canonical: dict[str, Any]) -> dict[str, Any]:
    """Coerce validator output (with tuples) to JSONB-safe form."""
    out = dict(canonical)
    opts = out.get("options")
    if opts:
        out["options"] = [list(t) if isinstance(t, tuple) else t for t in opts]
    return out


__all__ = [
    "ImportNotFoundError",
    "ImportStateError",
    "UploadValidationError",
    "confirm_import",
    "create_import",
    "detect_headers",
    "parse_and_stage",
    "required_mapping_missing",
    "save_mapping",
    "toggle_row",
]
