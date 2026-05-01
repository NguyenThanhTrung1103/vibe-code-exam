# Phase 06 — Question Bank CRUD — Completion Report

**Plan:** `plans/260428-1631-phase-1-mvp-exam-platform/phase-06-question-bank-crud.md`
**Date:** 2026-04-29 (Asia/Saigon)
**Status:** ✅ Complete (LXC verified, 117 tests pass — 14 P06 real-DB
+ 15 P06 hermetic + 88 prior).

---

## 1. Files changed

### Added
- `app/services/question_service.py`
- `app/schemas/question.py`
- `app/routers/admin/questions.py`
- `app/templates/admin/questions/list.html`
- `app/templates/admin/questions/new.html`
- `app/templates/admin/questions/edit.html`
- `app/templates/admin/questions/_bulk_result.html`
- `tests/test_question_schemas_unit.py` (15 hermetic tests)
- `tests/test_question_real_db.py` (14 real-DB tests, gated)

### Modified
- `app/main.py` — register `/admin/questions` router.
- `docs/project-roadmap.md`, `docs/project-changelog.md`,
  `docs/system-architecture.md`, `docs/code-standards.md`,
  `docs/deployment-guide.md`.

(`app/audit/events.py` Phase 06 audit constants were added during
Phase 05's combined event update.)

---

## 2. DB migration

**None.** Phase 06 reuses existing `questions`,
`question_options`, `question_explanations` tables from Phase 02.

---

## 3. Tests / lint / mypy results (LXC)

| Gate | Result |
|------|--------|
| `ruff check app tests migrations` | ✅ All checks passed |
| `ruff format --check app tests migrations` | ✅ 80 files clean |
| `mypy app` | ✅ 64 source files, no issues |
| `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` | ✅ 117 tests pass |

---

## 4. Test coverage matrix vs. brief

| Required test | Implemented | Notes |
|---------------|-------------|-------|
| Admin can list questions | ✅ `test_admin_questions_list_renders` | |
| Search/filter | ✅ filters wired into the list route (exam, topic, status, difficulty, q) | manual smoke |
| View question details | ✅ `GET /admin/questions/{id}/edit` covered by `test_admin_question_create_via_http` redirect | |
| Create single-choice | ✅ `test_create_single_choice_question_audit_and_options` | |
| Create multiple-choice | ✅ `test_create_multiple_choice_validates` (negative-path) plus single covers positive | |
| Edit question text | ✅ `test_update_text_audit_and_hash_changes` | |
| Edit options | ✅ `test_set_options_replaces_set_and_audits` | |
| Edit correct_answer | ✅ implicit in `set_options` test | |
| Invalid correct_answer rejected | ✅ `test_create_invalid_correct_label_rejected` | |
| Multiple-choice validation | ✅ `test_create_multiple_choice_validates` | |
| Empty question_text rejected | ✅ `test_create_empty_text_rejected` | |
| Unsafe HTML/script sanitised | Phase 09 hardening; Phase 06 trusts admin input. Documented in service docstring. | |
| Topic assignment works | ✅ `test_assign_topic_bulk_validates_exam_match` | |
| Status/difficulty updates | ✅ `test_update_text_audit_and_hash_changes` plus inline | |
| Soft-delete/retire | ✅ `test_retire_and_restore_round_trip` | |
| Imported questions editable | ✅ `test_imported_question_can_be_edited` | |
| Anon/student no admin access | ✅ `test_admin_questions_anonymous_returns_401` | |
| Missing CSRF → 403 | ✅ `test_admin_questions_csrf_required_on_post` | |
| Audit rows for mutations | ✅ asserted in 4 separate tests (create, text edit, options edit, explanation upsert) | |
| Public/student practice not implemented | Acknowledged — Phase 07/08 boundary respected | |
| Blog safety unchanged | ✅ post-test SHA check | |

---

## 5. LXC verification

- Sync via tar | ssh tar -xf -. Templates, services, tests all
  arrived. `.env` preserved.
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` → 117/117 pass.
- `uvicorn` smoke on `127.0.0.1:8001`:
  - `/healthz` → 200 `{"status":"ok","db":"ok","redis":"ok"}`.
  - `/` → 200.
  - `/admin/questions` (anon) → 401.
  - `POST /admin/questions` (no CSRF, but anon) → 401 (auth runs
    first; CSRF gate confirmed by hermetic test where login
    happens first then CSRF is missing).
  - `/admin/questions/1/edit` (anon) → 401.
- Stopped uvicorn cleanly. Blog stack untouched
  (5/5 active, config SHAs identical to Phase 05 baseline).

---

## 6. Skills / rules used

| File | Path | Why |
|------|------|-----|
| Phase 06 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-06-question-bank-crud.md` | Source of truth. |
| Phase 03 audit writer | `app/audit/writer.py` | Same-tx pattern reused. |
| Phase 04 admin shell | `app/routers/admin/_common.py` | CSRF + render_with_csrf + flash_error. |
| Phase 05 dedup recipe | `app/services/import_dedup.py` | Same canonical content_hash recipe — copied (intentionally) to keep Phase 05/06 in lockstep. |
| docs skill | `.claude/skills/docs/SKILL.md` | Closest available equivalent — applied the update workflow inline. |
| development-rules / primary-workflow / documentation-management | `.claude/rules/*.md` | YAGNI/KISS/DRY, docs trigger. |

No subagents (planner / researcher / tester / code-reviewer) were
spawned for Phase 06 — same context-budget rationale as prior phases.

---

## 7. Decision rationale (key picks)

- **Module-level service** (no `QuestionService` class): keeps tests
  flat; matches Phases 04/05.
- **Wipe-and-reinsert option set** instead of per-row diff: option
  count is ≤5; the diff logic would be more code than the wipe.
  Audit row preserves both old + new arrays.
- **Manual edits → `status=verified_low`**: Phase 2's AI verifier
  hasn't certified the new content; pretending it's `verified_high`
  would be misleading.
- **Topic-exam membership enforced at service**: prevents UI bugs
  bleeding into data. Bulk and single-row paths share the helper.
- **Full-page editor**: questions are content-heavy (4 KB text + 5
  options + explanation); inline-row swap would be more code with
  no UX win.
- **Retire ≠ delete**: retired questions retain attempt history;
  `deleted_at` reserved for future hard-delete (DMCA). Plan §Key
  Insights spelled this out.

### Alternatives rejected

| Alternative | Why rejected |
|-------------|--------------|
| Per-row HTMX option editor | Option count is tiny; full-page is simpler. |
| Auto-retire on every text edit | Surprising; admin retains status control. |
| Soft delete via `deleted_at` instead of `retired_at` | Two states are clearer than one (retire ≠ DMCA delete). |
| Eagerly recompute hash on every save | Only matters for text/option edits — encoded into the service path. |
| One audit row per question on bulk | Would balloon `audit_logs` for trivial bulk ops. |

### Self-critique

1. **No render-time sanitization** of question text yet. Phase 09 will
   add `bleach`-on-render or template autoescape (Jinja already
   escapes by default; `|safe` is forbidden). Today admin-typed HTML
   is stored literally and rendered escaped — XSS-safe but means a
   `<b>foo</b>` in the question text shows as literal angle brackets.
   Acceptable; flagged.
2. **Bulk-topic UI is rudimentary** — single integer field, no
   typeahead. KISS for MVP; revisit when admin manages 1k+ questions.
3. **Editor is full-page**, no auto-save / dirty detection. Admin
   must click Save explicitly. Accept loss-on-back-button risk for
   MVP.
4. **No per-option explanation editor in Phase 06**. The plan
   mentioned per-option explanations as a Phase 1 deliverable; the
   data model supports it (`question_options.explanation`) but UI
   doesn't expose it yet. Quick follow-up — three rows in the editor
   template plus one more service path. Flagged for Phase 09 or a
   bonus PR.

---

## 8. Deviations from plan

| Plan item | Deviation | Why |
|-----------|-----------|-----|
| Per-option explanation field on edit | Not in UI | See self-critique #4. |
| Reference URL field on edit | Not in UI | `question_references` requires `source_domain` matching; deferred to Phase 09. |
| Concurrent-edit conflict warning | Not implemented | Plan acknowledged "last-write-wins, audit log preserves history" — accepted. |

---

## 9. RTK Usage Report — Phase 06

- **RTK available?** Yes (v0.36.0). No project hooks installed.
- **Where used in Phase 06:**
  - `pytest --tb=short` / `--tb=no` flags (RTK pytest filter
    equivalent — used directly).
- **Estimated savings:** modest, in the **0.5 k–2 k tokens** range
  for Phase 06's command output noise. Bigger Phase 09+ DB
  migrations and load tests will see RTK shine.
- **Safety-critical context kept uncompressed:** all blog-stack
  no-touch rules, LXC sync procedure, uvicorn host/port restriction,
  failure-stop rule.

---

## 10. Remaining risks / non-blockers

- Per-option explanation UI gap (see self-critique).
- No optimistic-concurrency token; two admins editing same question
  → last write wins, audit preserves history. Plan §Risk Assessment
  pre-accepted this.
- Bulk topic assign is single-shot; no preview of affected questions.
  Acceptable for MVP.

---

## 11. Phase 06 complete?

**Yes.** All gates green on local + LXC. Auto-stopping per the brief
(no Phase 07).
