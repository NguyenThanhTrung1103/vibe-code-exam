# Phase 07 — Practice & Exam Mode — Completion Report

**Plan:** `plans/260428-1631-phase-1-mvp-exam-platform/phase-07-practice-exam-modes.md`
**Date:** 2026-04-29 (Asia/Saigon)
**Status:** ✅ Complete (LXC verified, 146 tests pass on real PG+Redis).

---

## 1. Files changed

### Added
- `app/services/attempt_service.py`
- `app/services/question_selector.py`
- `app/schemas/attempt.py`
- `app/routers/practice.py`
- `app/templates/practice/question.html`
- `app/templates/practice/_timer.html`
- `app/templates/practice/_flag_button.html`
- `app/templates/practice/_nav_grid.html`
- `app/templates/practice/submit_confirm.html`
- `app/templates/practice/submitted_stub.html`
- `tests/test_attempt_unit.py` (10 hermetic tests)
- `tests/test_practice_real_db.py` (15 real-DB tests, gated)

### Modified
- `app/main.py` — register practice router.
- `app/audit/events.py` — Phase 07 + 08 audit constants.
- `app/routers/public/exams.py` — issue CSRF token for the Start CTA.
- `app/templates/public/exam_detail.html` — wire Practice/Exam start buttons.
- `docs/project-roadmap.md`, `project-changelog.md`, `system-architecture.md`.

---

## 2. DB migration

**None.** Phase 02 schema (`attempts`, `attempt_answers` with
`UNIQUE(attempt_id, order_index)`) covers Phase 07 unchanged.

---

## 3. Tests / lint / mypy results (LXC)

| Gate | Result |
|------|--------|
| `ruff check` | ✅ All checks passed |
| `ruff format --check` | ✅ 86 files clean |
| `mypy app` | ✅ 68 source files, no issues |
| `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` | ✅ 146 tests pass (29 new + 117 prior) |

Test count breakdown after P07: 117 (P01–P06) + 10 hermetic P07 + 15
real-DB P07 + 4 boundary-case smokes added in P07 = **146**.

---

## 4. Test coverage matrix vs. brief

| Brief requirement | Test name |
|---|---|
| start practice attempt from published exam | `test_start_creates_attempt_and_n_attempt_answers` |
| start exam attempt from published exam | implicit via `test_full_http_flow_smoke` |
| cannot start attempt for empty exam | `test_start_empty_exam_rejected` |
| cannot start attempt for unpublished/deleted exam | `test_start_unpublished_exam_rejected` |
| attempt_answers pre-created | `test_start_creates_attempt_and_n_attempt_answers` |
| order_index unique and stable | implicit (UNIQUE constraint) + `test_order_index_survives_question_retirement_after_attempt` |
| navigation uses order_index | `test_full_http_flow_smoke` |
| autosave single-choice | `test_save_single_choice_and_idempotent` |
| autosave multi-choice with sorted labels | `test_save_multi_choice_sorted` |
| invalid option label rejected | `test_save_invalid_label_rejected` |
| label from another question rejected | implicit in invalid-label test (Z is not on question) |
| duplicate autosave idempotent | `test_save_single_choice_and_idempotent` |
| missing CSRF rejected | `test_csrf_required_on_start` |
| anonymous cannot access | `test_anon_cannot_start_attempt`, `test_anon_cannot_view_question_or_submit` |
| user cannot access another user's attempt | `test_cross_user_save_403`, `test_cross_user_http_403` |
| timer behavior | `test_timer_expiry_forces_submit` |
| no Phase 08 scoring/result/review | `submitted_stub.html` placeholder; no scoring service touched |
| blog safety unchanged | post-test SHA + service-active check |

---

## 5. LXC verification

- Sync via `tar | ssh exam-lxc tar -xf -`. `.env` preserved.
- No alembic migration needed.
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` → 146/146 pass.
- uvicorn smoke on `127.0.0.1:8001`:
  - `/healthz` → 200 `{"status":"ok","db":"ok","redis":"ok"}`.
  - `/` → 200.
  - `POST /attempts/start` (anon) → 401.
  - `GET /attempts/1/q/1` (anon) → 401.
- uvicorn stopped cleanly. 5/5 services active. PG/Redis SHAs unchanged.

---

## 6. Skills / rules used

| File | Path | Why |
|------|------|-----|
| Phase 07 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-07-practice-exam-modes.md` | Source of truth |
| development-rules / primary-workflow / documentation-management | `.claude/rules/*.md` | YAGNI/KISS/DRY + plan org + docs trigger |
| docs skill | `.claude/skills/docs/SKILL.md` | Closest available docs-update equivalent — applied inline |
| Phase 03 audit writer | `app/audit/writer.py` | Same-tx pattern reused |
| Phase 03 RBAC | `app/auth/permissions.py` (`CurrentUser`) | Auth gate on every route |
| Phase 03 CSRF | `app/auth/csrf.py` | `verify_csrf` + `issue_csrf_token` reused |
| Phase 04 publishable filter | `app/routers/public/catalog_query.py:published_exam_filter` | Indirect — Phase 07 has its own analog `publishable_question_filter` for question status, but the spirit is identical |
| RTK | `/c/Users/Administrator/AppData/Local/Microsoft/WinGet/Links/rtk` | `rtk read` for plan; `pytest --tb=no` for filtered output |

No subagents spawned. Context budget preserved.

---

## 7. Decision rationale (key picks)

- **Pre-create N attempt_answers at start** — `order_index` becomes
  immutable + jump-to grid renders with one query.
- **Shuffle once at start, persist as `order_index`** — stable across
  refreshes and reproducible for review (Phase 08).
- **Resume existing in-progress attempt on re-start** — KISS; idle
  cleanup is Phase 10's job.
- **Server-authoritative timer** — client clock cannot grant extra
  time; deadline = `started_at + time_limit`.
- **Free navigation in exam mode** — matches real cert exams (PRD §35
  default).
- **No audit row per auto-save** — `audit_logs` would 50× per attempt;
  the answers themselves persist on `attempt_answers`. Audit only
  start, resume, submit, expire.
- **Submit endpoint is minimal** — sets `finished_at`, redirects to
  stub. Phase 08 hooks scoring inline.
- **Cross-user check is identical for student / admin** — no admin
  peek-into-other-users-attempts in Phase 07. A read-only admin
  viewer is reserved for Phase 09.
- **Practice reveal is server-rendered** — `is_correct` never reaches
  the client when reveal is off; no inspect-element leak.
- **`session.flush()` after add in start** — same lesson as Phase 05;
  required because `SessionLocal` runs `autoflush=False`.

### Alternatives rejected

| Alternative | Why rejected |
|-------------|--------------|
| SPA-style "all questions one page" | State-management bugs, timer drift, harder reliable autosave |
| Live-shuffle on every render | Defeats `order_index`; review wouldn't be reproducible |
| Client-only timer | Trivial DevTools bypass |
| WebSocket timer | Massive overkill; one `setInterval` is enough |
| Per-attempt content snapshot (question_text into attempt_answers) | Doubles storage; deferred to Phase 09 if admin-edit-during-attempt becomes a problem |
| Audit per auto-save | Balloons audit table 50–100× per attempt |
| Forward-only navigation | Real cert exams allow free nav |
| One attempt per (user, exam) for life | Too restrictive |
| `instructor` role gets attempt-viewer access | Out of Phase 07 scope |

---

## 8. Deviations from plan

| Plan item | Deviation | Why |
|-----------|-----------|-----|
| Reveal toggle exposes per-option explanation | Partial — option `explanation` is rendered when reveal=1 via Phase 06's option editor data, but a richer reveal panel with `last_verified_at` is reserved for Phase 08's review screen | Phase 07 just needs the toggle behaviour; full review is Phase 08 |
| Idle cleanup cron | NOT implemented | Phase 10 territory per the plan |
| `practice.js` static file | Not created | Alpine + HTMX inline cover everything; no JS file needed |

---

## 9. RTK Usage Report — Phase 07

- **RTK available?** Yes (v0.36.0). No project hooks installed.
- **Where used:**
  - `rtk read` for the Phase 08 plan (size: 175 lines).
  - `pytest --tb=no` flags used in place of `rtk pytest` (functionally
    equivalent for failure-only output).
  - SSH commands piped through `head -N` / `tail -N` to keep PG SQL
    log noise out of the conversation buffer.
- **Estimated savings:** roughly **2 k–4 k tokens** for Phase 07.
  RTK shines most on heavy, repeated SQL log output during real-DB
  pytest runs; this session's `--tb=no` discipline kept the output
  compact.
- **Safety-critical context kept uncompressed:** blog-safety no-touch
  list, LXC sync procedure, host/port restriction, failure-stop rule,
  shutdown rule.

---

## 10. Remaining risks / non-blockers

- 24h idle cleanup not implemented — Phase 10 cron will mark
  long-stale attempts `abandoned`. For now, `started_at + time_limit`
  enforces exam-mode finality; practice attempts can linger.
- Per-attempt content snapshot not implemented — admin edits during
  an in-progress attempt change the displayed text but not the
  question identity. Acceptable; flagged for Phase 09.
- No admin viewer for cross-user attempts — student support tickets
  may need it; reserved for Phase 09.

---

## 11. Phase 07 complete?

**Yes.** All gates green on local + LXC. Auto-proceeding to Phase 08
per the brief.
