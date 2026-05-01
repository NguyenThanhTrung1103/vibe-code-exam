---
phase: 05
title: Excel import pipeline with mapping UI, dedup, sanitization
status: pending
effort: 5-6 days
priority: critical
depends_on: [04]
---

# Phase 05 — Excel Import Pipeline

## Context Links
- PRD §5 (Excel template), §8 (import workflow), §11 (dedup), §22 (prompt-injection / untrusted content), §24 (private-default)
- Phase 02 (`imports`, **`import_items`**, `questions`, `question_options`) tables ready
- Phase 04 (admin can create exams to import into)

## Overview
The most complex Phase 1 phase. Build the end-to-end pipeline: upload XLSX → store file outside public path → create `imports` row → parse with openpyxl → write each row as an `import_items` record → mapping UI → validate + sanitize + dedup (each row's status updated in place) → preview reads from `import_items` → admin selects/deselects → confirm idempotently converts selected items into `questions` (private/unpublished). Admin publishes the exam manually.

**Mutation & audit:** Use named service methods (e.g. `confirm_import`, `skip_row`) — **not** a single generic `mutate()` for all entities. Every state change that reflects an admin action must call **`audit_log_writer.write()` in the same transaction** as DB updates (import confirm, row status changes where required by product).

## Key Insights
- **DB-backed staging (revised)** — *Every parsed row is persisted to `import_items` immediately.* No in-memory staging list. Reasons: 1000+ row imports survive browser close, server restart, or admin returning later. Preview/mapping/confirm all read/write `import_items`. Counters derive from a single `GROUP BY status` query.
- **Real-world Excel files do not match the template.** Every uploader has different column headers ("Q", "Question", "QuestionText"). The mapping UI is what makes this work — auto-detect best guesses, let admin override. Mapping stored on `imports` (JSONB column or new field) so re-rendering preview is deterministic.
- **Idempotent confirm** — re-running confirm on the same `import_id` must not create duplicate questions. Implemented via `import_items.question_id IS NOT NULL` check; only items with `status='ok'` (selected, not yet imported) are written, then status flipped to `'imported'` in the same transaction.
- **Partial-failure tolerance** — if one row fails mid-confirm, successful rows keep their `question_id` link and `status='imported'`; failed row keeps `status='error'` with `error_message`. Admin retries; re-confirm picks up only remaining `'ok'` rows.
- **Source locator** — every created `question` carries `source_locator JSONB` with `{import_id, import_item_id, file_name, sheet_name, row_number}`. Used for debugging, audit, DMCA review.
- **Exact dedup uses one canonical hash** (same as `plan.md` and Phase 06): normalize `question_text` and each non-empty option; **sort** normalized option strings; then  
  `sha256(normalized_question + "|" + "||".join(sorted_normalized_options))`.  
  Computed during parse, persisted on `import_items.content_hash` / copied to `questions.content_hash`. Lookup against existing `questions.content_hash` *for the same exam* + against earlier rows in the same import. **Exact duplicate only** — near-duplicate detection is Phase 3.
- **Sanitization runs on import**, not just on render. Strip HTML tags, normalize Unicode (NFKC), strip RTL/zero-width. Applied to every text field. `import_items.raw_data` keeps the pre-sanitize snapshot for debugging.
- **No AI involvement yet.** Static `explanation` and `reference` columns from Excel are saved verbatim to `question_explanations.overall_explanation` and to a single `question_references` row (with `source_type='docs_other'`, `trust_level='low'` since unverified).
- **File storage:** uploaded XLSX stored at `/srv/exam-platform/uploads/imports/{import_id}.xlsx` (outside public path, mode 600). Kept for re-runs / audit / DMCA evidence.
- **Background jobs deferred:** parsing runs synchronously in the request for MVP. 5000 rows from openpyxl is OK (<10 s). RQ scaffolded but not used here.

## Requirements
**Functional**
- Admin uploads `.xlsx` (max 25 MB, ≤5000 rows) → file stored at `/srv/exam-platform/uploads/imports/{import_id}.xlsx` → server reads sheet headers.
- Mapping UI shows: Excel headers vs canonical fields (`question_text`, `option_a..e`, `correct_answer`, `explanation`, `reference`, `topic`, `difficulty`, `tags`, `question_type`). Auto-suggest best guess; admin can override. Mapping persisted on `imports.column_mapping` JSONB so admin can come back later.
- After mapping confirmation: server iterates rows, writes one `import_items` row per Excel row (`status='parsed'` initially), then runs validate + normalize + dedup which transitions each item to `'ok'`, `'duplicate'`, `'warning'`, `'error'`, or `'skipped'`.
- Preview page reads `import_items` for the import; pagination 50/page; filter chips: All / OK / Duplicates / Errors / Warnings / Skipped.
- Admin can deselect specific rows in preview (toggles a per-item flag, e.g. `import_items.status='skipped'`).
- Admin can leave the page and return; preview state survives.
- **Confirm is idempotent.** It selects only `import_items` where `status='ok'` AND `question_id IS NULL`; for each: insert question + options + explanation + reference; set `import_items.question_id` and flip `status='imported'`. Re-running confirm reproducibly creates 0 new questions.
- **Partial-failure tolerance.** If commit hits an error mid-batch, the failing item is rolled back and marked `status='error'` with `error_message`; successful items already committed remain. Admin sees an error summary.
- On successful confirm: questions inserted as `status='imported'`, `visibility=private`, `publish_status=draft`. Exam stays unpublished unless explicitly published.
- Dedup is enforced in two layers: (a) within the import (later rows whose hash matches earlier same-import rows → `status='duplicate'`); (b) against existing published questions in the same exam (→ `status='duplicate'`).
- Each created question stores `source_locator JSONB` linking back to import_item.
- Import attestation checkbox: admin attests they have rights (`imports.import_source_claim`).

**Non-functional**
- 1000-row Excel parses + previews in <10 s.
- Memory bounded — stream rows, don't materialize entire workbook in RAM.
- Sanitize cost <1 ms per row.

## Architecture

```
app/
├── routers/admin/import.py           # /admin/imports
├── services/
│   ├── import_service.py             # orchestrates parse → preview → commit
│   ├── excel_parser.py               # openpyxl read_only=True streaming
│   ├── import_normalizer.py          # whitespace, unicode, html sanitize
│   ├── import_validator.py           # required fields, type checks, hash
│   └── import_dedup.py               # content_hash + lookup
├── schemas/import_form.py
├── templates/admin/imports/
│   ├── upload.html                   # step 1: file upload
│   ├── mapping.html                  # step 2: column mapping
│   ├── preview.html                  # step 3: preview with row statuses
│   └── done.html                     # step 4: success summary
└── static/css/import.css
```

### State machines

**`imports.status`**
```
uploaded → needs_mapping → normalized → ready_to_publish → published
                       └→ failed (any step)
```
Phase 1 uses up to `ready_to_publish`; the last hop happens when admin publishes the exam.

**`import_items.status`** (per row)
```
parsed → ok       → imported           (happy path)
       → duplicate                     (dedup hit, not imported)
       → warning  → ok / skipped       (admin reviews)
       → error                         (validation failed; admin fixes Excel + re-uploads or skips)
       → skipped                       (admin deselected)
```
Counters everywhere derive from `SELECT status, COUNT(*) FROM import_items WHERE import_id=:id GROUP BY status`.

### Canonical fields and mapping
```
canonical fields:
  question_text*, question_type, difficulty, topic,
  option_a*, option_b*, option_c, option_d, option_e,
  correct_answer*, explanation, reference, tags
* = required
```

Auto-mapping: case-insensitive match on field name + common aliases (`question` → `question_text`, `answer` → `correct_answer`, etc.).

## Related Code Files
**Create**
- `app/services/import_service.py`, `excel_parser.py`, `import_normalizer.py`, `import_validator.py`, `import_dedup.py`
- `app/schemas/import_form.py`
- `app/routers/admin/import.py`
- `app/templates/admin/imports/{upload,mapping,preview,done}.html`
- `tests/test_excel_parser.py`, `test_import_normalizer.py`, `test_import_dedup.py`, `test_import_pipeline.py`
- `samples/import-template.xlsx` (admin reference template, committed)

## Implementation Steps

1. **Upload + persist file**
   - Validate ext + magic-number + size (Phase 09 helper if available; otherwise local check).
   - Create `imports` row with `status='uploaded'`, `attestation`, `import_source_claim`.
   - Save file to `/srv/exam-platform/uploads/imports/{import_id}.xlsx`, mode 600.

2. **Excel parser**
   - `openpyxl.load_workbook(path, read_only=True, data_only=True)`.
   - First row = headers; iterate rows lazily.
   - Cap rows at 5000; reject larger files.
   - Cap cell length per field (4000 for question_text, 1000 per option).

3. **Mapping UI**
   - Detected headers shown left, canonical fields shown right (select dropdown).
   - Auto-fill best-guess via alias table.
   - On save: persist mapping to `imports.column_mapping` JSONB; transition `status='needs_mapping' → 'normalized'` after parsing rows; advance to preview.

4. **Row materialization to `import_items`**
   - For each row in the workbook: write `import_items(import_id, row_number, sheet_name, raw_data, status='parsed')`. `raw_data` = pre-normalize JSONB snapshot of mapped row.
   - Then run normalize + validate + dedup; update each item's `normalized_data`, `content_hash`, `status` (`ok` / `duplicate` / `warning` / `error`), `error_message` / `warning_message`.
   - This loop is one DB transaction *per chunk* (e.g., 200 rows) to bound transaction size.

5. **Normalizer** — for each text field:
   - Strip leading/trailing whitespace; collapse internal whitespace.
   - Unicode NFKC normalization.
   - Strip zero-width chars (`​-‍﻿`) and RTL/LTR overrides.
   - Run through `bleach` HTML sanitizer with empty tag allowlist (strips all HTML).
   - Pre-normalize value persisted in `raw_data`; post-normalize in `normalized_data`.

6. **Validator** — per-row checks:
   - Required fields present.
   - `question_type` ∈ {`single`, `multiple`, `true_false`}; auto-detect if absent (multiple if `correct_answer` has comma).
   - `correct_answer` references valid option labels.
   - `difficulty` ∈ {`easy`, `medium`, `hard`}; default `medium`.
   - Sets `import_items.status` accordingly + `error_message`/`warning_message`.

7. **Dedup** — compute `content_hash` (**must match** `plan.md` / Phase 06):
   ```python
   def content_hash(row) -> str:
       norm_q = normalize(row.question_text)
       sorted_opts = sorted(normalize(o) for o in row.options if o)  # lexicographic sort of normalized strings
       payload = norm_q + "|" + "||".join(sorted_opts)
       return sha256(payload.encode()).hexdigest()
   ```
   - **Within-import dedup**: later rows whose hash matches earlier same-import items → `status='duplicate'`.
   - **Cross-import dedup**: hash matches existing `questions.content_hash` *for the same exam* → `status='duplicate'`.

8. **Preview UI**
   - Reads `import_items` paginated 50/page (filter by status).
   - Each row shows: `[checkbox] row# | Q text | A..E | correct | status badge | reason`.
   - Filter chips: `All / OK / Duplicates / Errors / Warnings / Skipped`.
   - Bulk-toggle checkbox.
   - Deselect: HTMX `hx-post` flips `import_items.status='skipped'` (or back to `'ok'`); page survives reload.
   - "Confirm import" button.

9. **Confirm step (idempotent)**
   - Query: `import_items WHERE import_id=:id AND status='ok' AND question_id IS NULL`.
   - For each: in a per-item subtransaction (savepoint):
     - insert `question` with `source_locator={import_id, import_item_id, file_name, sheet_name, row_number}`, `status='imported'`, `visibility=private`, `publish_status=draft`, `content_hash` copied from item.
     - insert `question_options` rows.
     - if explanation present → insert `question_explanations.overall_explanation` with `status='approved'`.
     - if reference URL present → insert one `question_references` row with `source_type='docs_other'`, `trust_level='low'`.
     - update `import_items` set `question_id`, `status='imported'`.
     - emit audit log entry.
   - Per-item failure: roll back that savepoint, set `import_items.status='error'` + `error_message`, continue.
   - After loop: update `imports.status` to `ready_to_publish` (or `partially_verified` if any errors).
   - Re-running confirm: 0 new questions because filter excludes `status='imported'` and `question_id IS NOT NULL`.

10. **Attestation** — checkbox on upload page: "I attest I have the right to upload this content." Stored in `imports.import_source_claim` + timestamp.

11. **Sample template** — Author `samples/import-template.xlsx` matching PRD §5. Linkable from upload page.

12. **Tests**
    - parse 200-row template → 200 `import_items` rows with `status='ok'`.
    - re-import same Excel into same exam → second pass produces 200 items with `status='duplicate'`, 0 new questions on confirm.
    - within-import dup (row 50 same as row 10) → row 50 marked duplicate.
    - malformed row (missing question_text) → `status='error'` with message.
    - HTML in question_text → stripped; `raw_data` preserves original.
    - **Idempotent confirm**: run confirm twice → row count of `questions` unchanged on second run.
    - **Partial-failure**: simulate FK error on row 5 → rows 1–4 get `status='imported'`, row 5 gets `status='error'`, rows 6+ remain `status='ok'`. Re-confirm processes 6+ correctly.
    - Visibility: imported questions are `private`/`draft` until exam published.
    - `source_locator` populated on every imported question.

## Todo List
- [ ] Upload route persists file + creates `imports` row + records attestation
- [ ] Excel parser (openpyxl streaming, cap 5000 rows, 25 MB)
- [ ] Mapping UI saves `imports.column_mapping`
- [ ] Row materialization writes one `import_items` per Excel row
- [ ] Normalizer (unicode + html sanitize + whitespace)
- [ ] Validator (required fields, types, defaults) updates `import_items.status`
- [ ] Content hash + within-import + cross-import dedup
- [ ] Preview UI reads from `import_items` (paginated, filterable, deselectable)
- [ ] Preview state survives navigation away
- [ ] Idempotent confirm step (savepoint per item, partial-failure tolerant)
- [ ] `source_locator` populated on every imported question
- [ ] Per-row audit log entries
- [ ] Attestation captured at upload
- [ ] File retained at `/srv/exam-platform/uploads/imports/`
- [ ] Sample template committed under `samples/`
- [ ] Tests: parser, normalizer, dedup, idempotent confirm, partial-failure, source_locator

## Success Criteria
- Admin imports 200-row Fortinet NSE4 Excel in <10 minutes total wall time (incl. clicks).
- Re-importing same Excel produces 0 new rows (all dups detected).
- **Idempotent confirm verified**: running confirm twice on same import produces 0 new questions on the second run.
- **Partial-failure tolerated**: simulated FK violation on one row leaves other rows imported correctly.
- Admin can leave the preview page and return — preview state is intact (filters, deselected rows).
- Hand-malformed row (missing `question_text`) appears in preview with red status.
- Excel containing `<script>alert(1)</script>` in question_text is stripped — render check passes XSS scan.
- Every imported question has `source_locator` JSONB populated.
- Imports default `private`/`draft`; not visible on public exam page until exam published.

## Risk Assessment
- **openpyxl memory blow-up** with very wide sheets. Mitigate: cap columns at 32; reject more.
- **Mapping UI complexity** is the single largest UX risk. Mitigate: keep it server-rendered with one select per column, no drag-and-drop.
- **`import_items` table grows fast** — one row per imported Excel row across all imports forever. At MVP scale (~50 imports × 1000 rows = 50k rows) this is trivial. Re-evaluate at Phase 2.
- **Confirm-step concurrency** — admin clicks confirm twice quickly. Idempotent design plus a unique `(import_id, status='imported', question_id)` constraint prevents duplicates. Add light row-level locking via `SELECT FOR UPDATE SKIP LOCKED` on `import_items` if needed.
- **Dedup misses near-duplicates** (different wording). Acceptable at MVP; Phase 3 adds vector dedup.
- **Excel formula injection** (CSV/Excel `=cmd|`) — when admin re-exports back to Excel later. Mitigate: Phase 1 doesn't auto-export; Phase 12 export will prefix `'` to suspicious cells.

## Security Considerations
- File extension + magic-number check (`xlsx` zip header). Reject mismatched.
- Size limit 25 MB enforced before parsing.
- Files stored outside public static path; served only via authenticated admin route if at all.
- Sanitize all imported text fields BEFORE storage. Re-sanitize at render in Phase 09 (defense in depth).
- Imported text never executed; never passed to AI verifier in Phase 1 (no AI yet) but Phase 22 prompt-injection rules already documented.
- Per-import rate limit: 5 imports/hour/admin (rate_limit middleware from Phase 03).

## Next Steps
Phase 06 — Question bank CRUD lets admin edit imported questions, add manual ones, and prepare for Phase 07's practice flow.
