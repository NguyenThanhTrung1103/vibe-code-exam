# Multi-format Import + Guest Practice — Implementation Report

**Date:** 2026-05-02
**Scope:** Milestone 1 (multi-format import + admin review link) shipped; Milestone 2 (guest practice) deferred and unexposed.
**Branch:** master (working tree, not committed)
**Migrations:** 0007 (`imports.title`), 0008 (`attempts.guest_token`), 0009 (`imports.detected_format`)

## Summary

Two slices were planned. **Only Milestone 1 is wired into HTTP routes and intended for deploy.** Milestone 2 ships in a dormant, unreachable state — see "Guest practice disposition" below.

| Slice | Milestone | Status |
|---|---|---|
| Parser-adapter layer (xlsx / examtopics_html / qblock_pdf / qblock_text) | M1 | Complete + wired |
| `imports.title` + UI title fallback | M1 | Complete + wired |
| `imports.detected_format` + detector hook on upload | M1 | Complete + wired |
| Combined-options + Vietnamese XLSX alias map (preserved) | M1 | Complete (regression-tested) |
| Import preview / done UI refresh | M1 | Complete + wired |
| "Review imported questions" link (`done.html` → `/admin/questions?source_import_id=`) | M1 | Complete + wired |
| Guest cookie helpers (`app/auth/guest.py`) | M2 | Code present, **NOT imported by any router** |
| `attempts.guest_token` column + CHECK constraint | M2 | Migration applied; column unused at HTTP layer |
| Guest practice flow (cookie-bound attempts, JSON public review) | M2 | **Not started** |

## Milestone 1 — what was built

### Parser-adapter layer

`app/services/parsers/`

- `base.py` — `ParserAdapter` Protocol with `detect()` + `parse()`. `CANONICAL_FIELDS` tuple is the single source of truth for output row keys consumed by `import_service.parse_and_stage`.
- `detector.py` — registry-based dispatcher. `detect_adapter(filename, file_path)` reads the first 4 KiB of the file and picks the highest-priority adapter whose `detect()` claims it. Priority order: XLSX (80) > ExamTopics HTML (70) > qblock PDF (60) > qblock text (50).
- `xlsx_adapter.py` — wraps existing `excel_parser.stream_rows`. Preserves canonical English headers AND the Vietnamese alias map AND `combined_options` synthetic column. **No behaviour change** vs. Phase 05.
- `examtopics_html_adapter.py` — best-effort DOM walk over a saved HTML page (NOT a remote scrape). Recognises `.question-body`, `.voted-answers-tally`, `[data-id]`, `.correct-answer`, etc. Falls back to regex-based option extraction.
- `qblock_text_adapter.py` — pure-function parser for `QUESTION N` / `A.` / `B.` / `Answer:` / `Explanation:` blocks. Page-number lines are filtered.
- `qblock_pdf_adapter.py` — extracts text via `pdfminer.six` then delegates to `parse_qblock_text` (the pure function from `qblock_text_adapter`).

### Wiring

- `import_service.create_import` (line 154–160) calls `detect_adapter` after the file lands on disk. The adapter `name` is stamped onto `imports.detected_format` (nullable; `NULL` when nothing claims the file).
- Detection failure is non-fatal: `try/except Exception → detected_format = None` keeps upload working even if a future adapter raises.
- All adapters return `dict[str, Any]` with the `CANONICAL_FIELDS` shape, so `import_normalizer`, `import_validator`, dedup, and community-source upsert paths see exactly the same row dicts they always saw.

### Imports model + UI

- `imports.title` — `String(255) NULL`. UI falls back to `file_name` when blank (Jinja-only, no Python fallback logic).
- `imports.detected_format` — `String(32) NULL`. Surfaced on `/admin/imports/{id}/done` and on the import-list row.
- `app/templates/admin/imports/done.html` — "Review imported questions" CTA (line 68) links to `/admin/questions?source_import_id={imp.id}`.

### Confirm guard (regression-protected)

`import_service.confirm_import` raises `ImportStateError("No rows were staged...")` when `import_items` count is zero. Originally added after the Import #135 ghost-confirm post-mortem (2026-05-02). New test case (`tests/test_import_unit.py::test_confirm_blocks_on_zero_staged`) protects the guard.

## Guest practice disposition (Milestone 2)

**Decision: Option B — keep code in place, but unexposed and documented.**

### What lands in production

- `app/auth/guest.py` — module is present in the deploy.
- `attempts.guest_token` column — created on `exam_platform_db` via migration 0008.
- `attempts.user_id` becomes nullable (was NOT NULL).
- CHECK constraint `ck_attempts_owner` enforces `user_id IS NOT NULL OR guest_token IS NOT NULL`.

### Why this is safe

- `app/auth/guest.py` is **not imported by any router**. Verified via grep across `app/routers/`. No HTTP code path can issue or read `exam_guest_token` cookies.
- All attempt-creation routes (`app/routers/practice.py`, `app/routers/attempts.py`) require `CurrentUser` (authenticated). There is no route that accepts a `guest_token` form field or query parameter.
- Existing rows have `user_id` populated, so the CHECK constraint is satisfied for all of them after migration.
- Adding a nullable column has no runtime cost and no backward-incompatible effect.

### What WILL be done in Milestone 2

- Add a `dependencies=[Depends(ensure_guest_owner)]`-style helper that mints a guest token only on practice-start of a published exam.
- Public review page (`GET /attempts/{id}/review`) gated by either authed `CurrentUser` OR matching cookie `exam_guest_token`.
- Tests for the guest path (cookie issue, isolation between two cookies, ownership check on review).
- Update legal pages + readiness checklist.

Milestone 2 is **not** authorised to deploy yet (per operator instruction 2026-05-02).

## Quality gates

Run before deploy:

```bash
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run pytest -q
```

Result of the run that gated this report: **see `docs/reports/changelog-local.md`** for exact pass/fail counts.

## Migrations

```
0007_c2d3e4f5a6b7_imports_add_title.py        (was b1c2d3e4f5a6 → c2d3e4f5a6b7)
0008_d3e4f5a6b7c8_attempts_guest_token.py     (was c2d3e4f5a6b7 → d3e4f5a6b7c8)
0009_e4f5a6b7c8d9_imports_detected_format.py  (was d3e4f5a6b7c8 → e4f5a6b7c8d9)
```

Apply in numeric order via `uv run alembic upgrade head`. Roll back per-revision via `alembic downgrade -1`.

## Dependencies

Added `pdfminer.six>=20240706` to `pyproject.toml`. No other deps changed. PDF parsing fails gracefully with a clear `RuntimeError` if the wheel is somehow missing on the target.

## Files touched (high level)

**New**
- `app/services/parsers/{__init__,base,detector,xlsx_adapter,examtopics_html_adapter,qblock_pdf_adapter,qblock_text_adapter}.py`
- `app/auth/guest.py` (Milestone 2; unwired)
- `app/templates/admin/_layout.html`, `app/static/css/admin.css`
- `migrations/versions/0007_*`, `0008_*`, `0009_*`

**Modified**
- `app/models/imports.py`, `app/models/attempts.py`
- `app/auth/permissions.py`, `app/routers/auth.py` (HTML→303 login redirect)
- `app/routers/admin/imports.py`, `app/routers/admin/questions.py`
- `app/services/{excel_parser,import_normalizer,import_service,import_validator}.py`
- `app/templates/admin/imports/{upload,mapping,preview,done,_row}.html`
- `app/templates/admin/catalog/_error.html`
- `app/templates/auth/{_layout,login}.html`, `app/templates/base.html`
- `pyproject.toml`

## Unresolved questions

- Should `imports.detected_format` be displayed on the imports list page (currently only on `done`)?
- Vietnamese-keyword detection for non-XLSX (HTML/PDF/TXT) is not yet implemented — adapter detection is filename + magic-bytes only. Acceptable for Milestone 1 scope.
