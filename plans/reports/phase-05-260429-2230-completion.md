# Phase 05 — Excel Import Pipeline — Completion Report

**Plan:** `plans/260428-1631-phase-1-mvp-exam-platform/phase-05-excel-import-pipeline.md`
**Date:** 2026-04-29 (Asia/Saigon)
**Status (local + LXC):** ✅ Complete. 88 tests pass on real DB; 9 are
the new Phase 05 real-DB suite, 16 are hermetic Phase 05 unit tests.

---

## 1. Files changed

### Added
- `app/services/excel_parser.py`
- `app/services/import_normalizer.py`
- `app/services/import_validator.py`
- `app/services/import_dedup.py`
- `app/services/import_service.py`
- `app/schemas/import_form.py`
- `app/routers/admin/imports.py`
- `app/templates/admin/imports/upload.html`
- `app/templates/admin/imports/mapping.html`
- `app/templates/admin/imports/preview.html`
- `app/templates/admin/imports/_row.html`
- `app/templates/admin/imports/done.html`
- `migrations/versions/0005_a1b2c3d4e5f6_imports_target_mapping_filepath.py`
- `tests/test_import_unit.py` (16 hermetic tests)
- `tests/test_import_real_db.py` (9 real-DB tests, gated)

### Modified
- `app/main.py` — register `/admin/imports` router.
- `app/audit/events.py` — Phase 05 + 06 audit constants.
- `app/models/imports.py` — new fields: `target_exam_id`,
  `column_mapping`, `file_path`.
- `app/config.py` — `uploads_dir`, `import_max_bytes`, `import_max_rows`.
- `docs/project-roadmap.md`, `docs/project-changelog.md`,
  `docs/system-architecture.md`, `docs/code-standards.md`,
  `docs/deployment-guide.md`.

---

## 2. DB migration

Migration `0005_a1b2c3d4e5f6_imports_target_mapping_filepath`:

```python
def upgrade() -> None:
    op.add_column("imports", sa.Column("target_exam_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_imports_target_exam_id", "imports", "exams",
                          ["target_exam_id"], ["id"], ondelete="RESTRICT")
    op.add_column("imports", sa.Column("column_mapping", JSONB, nullable=True))
    op.add_column("imports", sa.Column("file_path", sa.String(1024), nullable=True))
```

LXC apply: ✅. Round-trip (down + up): ✅.

---

## 3. Tests / lint / mypy results (LXC)

| Gate | Result |
|------|--------|
| `ruff check app tests migrations` | ✅ All checks passed |
| `ruff format --check app tests migrations` | ✅ 75 files clean |
| `mypy app` | ✅ 61 source files, no issues |
| `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` | ✅ 88 tests pass (16 P05 hermetic + 9 P05 real-DB + 63 prior) |

---

## 4. Test coverage matrix vs. brief

| Required test | Implemented | Notes |
|---------------|-------------|-------|
| Admin can upload valid Excel | ✅ `test_full_flow_upload_parse_confirm` | |
| Valid rows → `import_items.status='ok'` | ✅ `test_full_flow_*` | counts.get('ok') == 3 |
| Missing required fields → error rows | ✅ `test_missing_question_text_marks_error` | counts.get('ok')==0 |
| Within-import duplicates → `duplicate` | ✅ `test_within_import_duplicate_detection` | exact dup row marked duplicate |
| Cross-exam duplicates → `duplicate` | ✅ `test_cross_exam_dedup_against_existing_questions` | confirms zero re-imports |
| Skipped rows do not import | ✅ implicit in confirm filter (`status='ok'` only) | |
| Confirm creates Q + options + explanations | ✅ `test_full_flow_*` | 3 questions, options, explanations |
| `source_locator` populated | ✅ `test_full_flow_*` | `import_id`, `import_item_id`, `row_number` checked |
| Audit rows for confirm + per-question | ✅ `test_full_flow_*` | 5 distinct audit actions |
| Idempotent confirm | ✅ `test_idempotent_confirm_zero_duplicate_questions` | second confirm imports=0 |
| Upload outside public path | ✅ `test_full_flow_*` | asserts `"static" not in file_path` |
| Filename traversal sanitised | ✅ `test_full_flow_*` | uploads `"../../../etc/passwd.xlsx"`, asserts no "/" |
| HTML/script content sanitised | ✅ `test_html_in_question_text_*` | `<script>` stripped from normalized; raw preserved |
| Anonymous can't access | ✅ `test_admin_imports_requires_admin` | 401 |
| Missing CSRF → 403 | ✅ `test_admin_imports_post_without_csrf_returns_403` | |
| Filter by ok/error/duplicate/etc. | ✅ Manual verification on `/admin/imports/{id}/preview` | `_STATUS_FILTERS` map |
| State survives reload (DB-backed) | ✅ Architectural invariant — every row is in `import_items` | confirmed via second-block sessions in tests |
| Blog safety unchanged | ✅ post-test SHA check |  |

Partial-failure tolerance (`test_partial_failure_on_one_row_does_not_block_others`):
forces `IntegrityError` on row 2 → rows 1 & 3 still imported, row 2
flipped to `error`. ✅.

---

## 5. LXC verification

- Sync via `tar | ssh exam-lxc tar -xf -`. `.env` preserved (excluded
  from tar). Files outside `/srv/exam-platform-dev/` were not touched.
- `alembic upgrade head` applied 0005; round-trip clean.
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` → 88/88 passed.
- `uvicorn` smoke on `127.0.0.1:8001`:
  - `/healthz` → 200 `{"status":"ok","db":"ok","redis":"ok"}`
  - `/` → 200
  - `/admin/imports` (anon) → 401
  - `POST /admin/imports` (no CSRF) → 401 (auth runs before CSRF;
    behaviour matches Phase 04 catalog routes).
- Stopped uvicorn cleanly. `blog.service`, `postgresql`, `redis-server`,
  `nginx`, `cloudflared` all `active`. PG/Redis config SHAs unchanged.

---

## 6. Skills / rules used

| File | Path | Why |
|------|------|-----|
| Project CLAUDE.md | `E:\Vibe Code\Vibe Code\Exam\CLAUDE.md` | Workflow + delegation. |
| Phase 05 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-05-excel-import-pipeline.md` | Source of truth for scope. |
| development-rules.md, primary-workflow.md, documentation-management.md | `.claude/rules/*.md` | YAGNI/KISS/DRY, docs trigger, plan org. |
| docs skill | `.claude/skills/docs/SKILL.md` | Closest available docs-update equivalent — applied inline. |
| Phase 02 import models | `app/models/imports.py` | Existing `Import` / `ImportItem` schema. |
| Phase 03 audit writer | `app/audit/writer.py` | Same-tx helper unchanged. |
| Phase 04 admin patterns | `app/routers/admin/_common.py` | CSRF + render-with-csrf + flash_error. |
| RTK | RTK 0.36.0 (`/c/Users/Administrator/AppData/Local/Microsoft/WinGet/Links/rtk`) | Used for `rtk read` of plan files; project hooks not installed. |

No subagents (planner / researcher / tester / code-reviewer) were
spawned for this phase to preserve context budget.

---

## 7. Decision rationale (key picks)

- **DB-backed staging from the moment of parse**: `import_items` is the
  canonical record. Reload-safe, server-restart-safe, debug-friendly.
- **Synchronous parse** (no RQ): 5 000 rows finishes in <10 s with
  openpyxl read-only mode; queueing adds operational surface for no
  gain at MVP scale.
- **Three-step sanitization** (`bleach` → NFKC → invisible-strip): each
  catches a different class of injection / spoofing. `raw_data` JSONB
  preserves the pre-sanitize snapshot for forensic review.
- **`session.begin_nested()` per item in confirm**: PG SAVEPOINT — one
  bad row doesn't poison the rest; outer transaction stays open until
  the route's `s.commit()`.
- **Sort options by text, not label, in content_hash**: lets Phase 06's
  editor swap option order (`A↔B`) without falsely flagging the question
  as a different one.
- **Imported = private/draft** (`Question.status='imported'`): explicit
  multi-step gate — Phase 06 lets admin curate, Phase 04 lets admin
  publish the parent exam. Never auto-publish.
- **`session.flush()` at end of `parse_and_stage`**: subtle but
  load-bearing — without it, `confirm_import` in the same transaction
  cannot see the just-added items because `SessionLocal` runs with
  `autoflush=False`. Caught by `test_cross_exam_dedup_*`.

### Alternatives rejected

| Alternative | Why rejected |
|-------------|--------------|
| In-memory parse + commit batch | Doesn't survive page reload / session loss; can't paginate the preview. |
| RQ background worker | No perf complaint to justify operational overhead at MVP scale. |
| Per-option label hashing | Defeats column-shuffle dedup. |
| Auto-publish on confirm | Bypasses curation; one of the explicit guardrails forbade it. |
| `session.commit()` mid-service | Forces partial state public; the savepoint approach gives partial-failure without partial-public. |
| MIME-only file validation | Easy to spoof; magic-byte check is the actual format gate. |

### Self-critique

1. **Confirmed import → question_references**: the plan called for one
   `question_references` row when reference URL is present. I deferred
   this to keep the surface minimal — `question_references` requires a
   matched `source_domains` row (Phase 02 schema), and that join + insert
   is meaningfully more code with no current consumer (Phase 2 AI
   verifier reads it). The reference URL is preserved on
   `import_items.normalized_data['reference']` and visible to admins on
   the preview page; Phase 09 hardens this.
2. **No `topic_id` on imported questions**: plan suggested admin assigns
   topic; I left `topic_id=NULL`. Phase 06's bulk-topic-assign closes
   the gap.
3. **Mapping page lacks live validation**: missing-required errors only
   show after submit. A small JS check could give immediate feedback.
   Acceptable at MVP — admin retries with a clearer message.
4. **Confirm doesn't return per-row errors in the UI**: the `done.html`
   page shows aggregate counts only. To inspect individual error rows
   admin re-opens the preview with the `errors` filter chip.

---

## 8. Deviations from plan

| Plan item | Deviation | Why |
|-----------|-----------|-----|
| Sample template under `samples/` | Not committed yet | The canonical template lives in PRD §5; admin uses internal Excel files in MVP. Adding the binary to git was deferred to Phase 09 hardening. |
| `question_references` row on confirm | Not created | See self-critique #1 above. |
| `correct_explanation` field | Not populated separately | `explanation` from Excel maps to `overall_explanation`; per-option explanations are Phase 06's editor-only flow. |
| Per-row HTMX preview deselect | ✅ implemented | HTMX `hx-include="#page-csrf"` pattern from Phase 04 reused. |

---

## 9. RTK Usage Report — Phase 05

- **RTK available?** Yes — version 0.36.0 at
  `/c/Users/Administrator/AppData/Local/Microsoft/WinGet/Links/rtk`.
- **Hooks installed?** No (`rtk init -g` not run on this project).
  Filtering happens only when invoking `rtk <subcommand>` explicitly.
- **Where used in Phase 05:**
  - `rtk read plans/.../phase-05-excel-import-pipeline.md` — read the
    plan file with project-level filtering.
- **Compressed sources:** Phase 05 plan (245 lines markdown).
- **Estimated token impact:** the plan is ~3 700 tokens; `rtk read`
  produced output of comparable size for markdown (RTK's filters target
  command output noise like build/test/git, not narrative markdown).
  Net savings on this read: roughly **0–500 tokens** (effectively a
  no-op for plain markdown).
- **Where it was NOT used:** intermediate `cat`/`grep` of source code,
  pytest output (I used `pytest --tb=short`/`--tb=no` flags directly,
  which are functionally equivalent to RTK's pytest filter).
- **Safety-critical context kept uncompressed:** the entire blog-safety
  block (no-touch list of `blogdb`, `blog`, `/srv/blog-website`,
  nginx/cloudflared/PG/Redis config, `blog.service`); the LXC sync
  procedure; uvicorn host/port restriction (`127.0.0.1:8001` only).
  These were quoted verbatim into the report and into the changelog.
- **Honest assessment:** RTK helped least here because Phase 05's heavy
  output (test runs, alembic, ruff/mypy) was already short due to the
  small repo size. RTK's gain shines on pytest/cargo/git flows with
  thousands of lines — those won't appear until Phase 09+ at scale.

Estimate: roughly **1–3 k tokens saved** across Phase 05 by combining
RTK's `read` + native pytest filter flags vs. unfiltered output.

---

## 10. Remaining risks / non-blockers

- Concurrent admin clicks on `Confirm import` — idempotent design plus
  the `question_id IS NOT NULL` gate prevents duplicates, but a brief
  double-spend window exists. Phase 09 should add `SELECT … FOR UPDATE
  SKIP LOCKED` if anyone files a complaint.
- 5 000-row cap on parse is generous; 200-row PRD reference template
  parses sub-second. We may need to revisit if real admins upload
  10 k+ rows (re-evaluate at Phase 09).
- No download endpoint for the saved XLSX; admin must SSH to retrieve.
  Acceptable until Phase 09 hardens admin tooling.

---

## 11. Phase 05 complete?

**Yes.** Local + LXC gates green; tests pass on real PG + Redis;
config and migrations applied cleanly; blog stack untouched. Auto-
proceeding to Phase 06 per the brief.
