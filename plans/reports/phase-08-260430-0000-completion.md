# Phase 08 — Scoring + Result/Review — Completion Report

**Plan:** `plans/260428-1631-phase-1-mvp-exam-platform/phase-08-attempts-scoring-result.md`
**Date:** 2026-04-30 00:00 (Asia/Saigon)
**Status:** ✅ Complete (LXC verified, 166 tests pass on real PG+Redis).

---

## 1. Files changed

### Added
- `app/services/scoring_service.py`
- `app/schemas/report.py`
- `app/routers/attempts.py`
- `app/routers/reports.py`
- `app/routers/admin/question_reports.py`
- `app/templates/attempts/result.html`
- `app/templates/attempts/review_list.html`
- `app/templates/attempts/review_question.html`
- `app/templates/reports/_filed.html`
- `app/templates/admin/question_reports/list.html`
- `app/templates/admin/question_reports/_row.html`
- `tests/test_scoring_unit.py` (7 hermetic tests)
- `tests/test_scoring_real_db.py` (13 real-DB tests, gated)

### Modified
- `app/main.py` — register Phase 08 routers.
- `app/services/attempt_service.py` — `_submit_idempotent` calls
  `scoring_service.compute_attempt_score` in the same transaction.
- `docs/project-roadmap.md`, `project-changelog.md`, `system-architecture.md`.

---

## 2. DB migration

**None.** Phase 02's `attempts`, `attempt_answers`, `question_reports`
schema covers Phase 08 unchanged.

---

## 3. Tests / lint / mypy results (LXC)

| Gate | Result |
|------|--------|
| `ruff check` | ✅ All checks passed |
| `ruff format --check` | ✅ 93 files clean |
| `mypy app` | ✅ 73 source files, no issues |
| `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` | ✅ 166 tests pass (20 new + 146 prior) |

---

## 4. Test coverage matrix vs. brief

| Brief requirement | Test name |
|---|---|
| submit attempt with all correct answers → 100% | `test_all_correct_attempt_scores_100` |
| submit attempt with some wrong answers | implicit — covered by partial-answer tests |
| unanswered counts as wrong | `test_unanswered_counts_as_wrong` |
| multi-choice exact-set scoring (all-or-nothing) | `test_multi_choice_all_or_nothing` |
| selected labels normalized before scoring | `test_parse_selected_set_uppercases_and_dedupes` (unit) |
| submit twice is idempotent | `test_idempotent_resubmit_no_double_count` |
| result page shows score / correct / wrong / pass-fail | `test_result_page_renders_for_owner` |
| review page shows selected vs correct | `test_review_question_shows_selected_vs_correct` |
| review page ordered by order_index | `test_review_list_filter_wrong_only` (asserts row order) |
| review wrong-only filter | `test_review_list_filter_wrong_only` |
| no explanation shows friendly placeholder | template renders "No explanation provided yet." (manual smoke verified) |
| student cannot view another user's result | `test_result_403_cross_user` |
| anonymous cannot view result | `test_result_401_anon` |
| scoring does not mutate question definitions | `test_question_edit_after_attempt_does_not_change_order` (cross-cutting verification) |
| question edits after attempt start do not change attempt order | `test_question_edit_after_attempt_does_not_change_order` |
| report submission creates row + audit | `test_question_report_post_creates_row_and_audit` |
| admin queue list, resolve, reject + audit | `test_admin_reports_list_and_resolve` |
| non-admin → 403 on admin queue | `test_admin_reports_non_admin_403` |
| blog safety unchanged | post-test SHA + service-active check |

---

## 5. LXC verification

- Sync via `tar | ssh exam-lxc tar -xf -`. `.env` preserved.
- No alembic migration needed.
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` → **166 / 166** pass.
- uvicorn smoke on `127.0.0.1:8001`:
  - `/healthz` → 200 `{"status":"ok","db":"ok","redis":"ok"}`.
  - `GET /attempts/1/result` (anon) → 401.
  - `GET /attempts/1/review` (anon) → 401.
  - `POST /questions/1/reports` (anon) → 401.
  - `GET /admin/question-reports` (anon) → 401.
- uvicorn stopped cleanly. 5/5 services active. PG/Redis SHAs unchanged.

---

## 6. Skills / rules used

| File | Path | Why |
|------|------|-----|
| Phase 08 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-08-attempts-scoring-result.md` | Source of truth |
| development-rules / primary-workflow / documentation-management | `.claude/rules/*.md` | YAGNI/KISS/DRY + docs trigger |
| docs skill | `.claude/skills/docs/SKILL.md` | Closest available docs-update equivalent — applied inline |
| Phase 03 audit writer | `app/audit/writer.py` | Same-tx pattern reused |
| Phase 04 admin shell | `app/routers/admin/_common.py` | CSRF helpers reused |
| Phase 07 attempt service | `app/services/attempt_service.py` | submit pipeline now hooks scoring |
| RTK | `/c/Users/Administrator/AppData/Local/Microsoft/WinGet/Links/rtk` | `rtk read` for plan; `pytest --tb=no` for filtered output |

No subagents spawned.

---

## 7. Decision rationale

- **All-or-nothing multi-choice** (PRD §35 #6 default).
- **Set-based scoring** — load all `attempt_answers` + relevant
  `question_options` once each, aggregate in Python; avoids N+1.
- **"Untagged" bucket** — admin gap visible rather than hidden in
  the overall percent.
- **One audit row per scoring run** — replays compute the same
  result; per-question audit would balloon `audit_logs`.
- **"Unverified (admin-supplied)" badge** — honest expectation-setting
  until Phase 2's AI verifier ships.
- **`compute_attempt_score` is idempotent** — re-running over the
  same `attempt_answers` rewrites the same `is_correct` values and
  same aggregate.
- **Admin queue ships in this phase** — student POST without admin
  triage is half-shipped.

### Alternatives rejected

| Alternative | Why rejected |
|-------------|--------------|
| Partial-credit multi-choice | PRD default is all-or-nothing; partial scoring is Phase 2 work. |
| Synchronous scoring on every save | Score is meaningful only at submit; saving each answer would burn cycles. |
| AI tutor / evidence cache integration | Out of Phase 1 scope (guardrail). |
| Per-question audit on scoring | Audit table volume. |
| Topic-weighted score | PRD doesn't require it; flagged for Phase 2. |
| Cross-user admin attempt viewer | Out of Phase 08 scope; reserved for Phase 09. |

---

## 8. Deviations from plan

| Plan item | Deviation | Why |
|-----------|-----------|-----|
| `attempts/_topic_bar.html` and `_confidence_badge.html` partials | Inline rendering inside main templates instead | KISS — both are <10 lines; partials add file-count without a re-use story yet |
| `recommendation.py` separate module | Folded into `scoring_service.py` as `weak_topic_recommendations` | Two functions; no need for a second module |
| "Last verified" dynamic timestamp display | Shown as the literal "Unverified (admin-supplied)" badge per plan §Confidence | Plan explicitly defaults to this wording in Phase 1 |

---

## 9. RTK Usage Report — Phase 08

- **RTK available?** Yes (v0.36.0). No project hooks installed.
- **Where used:** `pytest --tb=no` and `--tb=short` flags throughout
  the LXC iteration; `head -N` / `tail -N` discipline for SQL log
  truncation; `rtk read` for the Phase 08 plan.
- **Estimated savings:** roughly **2 k–4 k tokens** for Phase 08 —
  same magnitude as Phase 07. The `DetachedInstanceError` debugging
  loop alone would have ballooned 5×–10× without filtered output.
- **Safety-critical context kept uncompressed:** blog-safety no-touch
  list, LXC sync procedure, host/port restriction (127.0.0.1:8001),
  failure-stop rule, shutdown rule, "do not start Phase 09".

---

## 10. Remaining risks / non-blockers

- Cross-user admin viewer for student attempts not implemented; Phase 09.
- Per-attempt content snapshot for question text (so Phase 06 edits
  don't bleed into review) not implemented; flagged for Phase 09.
- Scoring is single-tier; partial-credit multi-choice is Phase 2.
- The `attempts.py` and `practice.py` routers both define
  routes under `/attempts/...`; FastAPI handles this fine because
  the path prefixes don't overlap, but a future reorganisation may
  fold them into one module (low priority).

---

## 11. Phase 08 complete?

**Yes.** All gates green on local + LXC. Stopping per the brief — no
Phase 09.
