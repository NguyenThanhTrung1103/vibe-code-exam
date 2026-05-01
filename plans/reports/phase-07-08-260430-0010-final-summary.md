# Phase 07 + Phase 08 — Combined Final Summary

**Date:** 2026-04-30 00:10 (Asia/Saigon)
**Mode:** unattended back-to-back run; auto-approval used only for the
Phase 07 → Phase 08 transition.
**Phase 09:** NOT started, per the brief.

---

## 1. Phase 07 complete? **Yes.**
## 2. Phase 08 complete? **Yes.**

166/166 tests pass on the LXC against real PostgreSQL + Redis. No core
service was stopped, no kernel/system config touched, no blog
artifact changed.

---

## 3. Files changed by each phase

### Phase 07
**Added (12):**
- `app/services/attempt_service.py`
- `app/services/question_selector.py`
- `app/schemas/attempt.py`
- `app/routers/practice.py`
- `app/templates/practice/{question,_timer,_flag_button,_nav_grid,submit_confirm,submitted_stub}.html`
- `tests/test_attempt_unit.py`
- `tests/test_practice_real_db.py`
- `plans/reports/phase-07-260429-2330-completion.md`

**Modified:**
- `app/main.py` (router wire)
- `app/audit/events.py` (Phase 07 + 08 audit constants — bulk add)
- `app/routers/public/exams.py` (issue CSRF token for Start CTA)
- `app/templates/public/exam_detail.html` (wire Practice / Exam buttons)
- `docs/*.md` (5 files)

### Phase 08
**Added (13):**
- `app/services/scoring_service.py`
- `app/schemas/report.py`
- `app/routers/attempts.py`
- `app/routers/reports.py`
- `app/routers/admin/question_reports.py`
- `app/templates/attempts/{result,review_list,review_question}.html`
- `app/templates/reports/_filed.html`
- `app/templates/admin/question_reports/{list,_row}.html`
- `tests/test_scoring_unit.py`
- `tests/test_scoring_real_db.py`
- `plans/reports/phase-08-260430-0000-completion.md`

**Modified:**
- `app/main.py` (register attempts, reports, admin question_reports routers)
- `app/services/attempt_service.py` (`_submit_idempotent` calls scoring)
- `docs/*.md` (3 files)

---

## 4. DB migrations by each phase

| Phase | Migration | Notes |
|-------|-----------|-------|
| 07 | none | reuses Phase 02 `attempts` + `attempt_answers` |
| 08 | none | reuses Phase 02 `attempts`, `attempt_answers`, `question_reports` |

Heads on `exam_platform_db` after this session: `a1b2c3d4e5f6`
(unchanged from Phase 05).

---

## 5. Tests / lint / mypy results by each phase

LXC, fresh run after both phases:

| Gate | Result |
|------|--------|
| `ruff check app tests migrations` | ✅ All checks passed |
| `ruff format --check app tests migrations` | ✅ all clean |
| `mypy app` | ✅ 73 source files, no issues |
| `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` | ✅ 166 tests pass |

Test count breakdown after P07+P08:
- 117 (P01–P06 baseline)
- 10 hermetic P07 + 15 real-DB P07 = **25 P07 tests**
- 7 hermetic P08 + 13 real-DB P08 + 4 boundary additions = **24 P08 tests**

**Total = 166 / 166 pass on real PostgreSQL + Redis.**

Three test-helper bugs surfaced during the LXC iteration and were
fixed:
1. **P07** `test_order_index_survives_question_retirement_after_attempt`
   — captured `attempt.id` before the session closed.
2. **P08** test isolation — replaced SA-User instance handed across
   sessions with a `_TestUser` dataclass to avoid
   `DetachedInstanceError` when test helpers read `email` after a
   prior commit had expired the model.
3. **P08** test cleanup — explicit per-table delete order to satisfy
   `RESTRICT` FK constraints on `attempt_answers`, `question_reports`.

No production code-paths were altered to make tests pass.

---

## 6. Real-DB verification by each phase

**Phase 07** — boot, `/healthz` 200, anon `POST /attempts/start` 401,
anon `GET /attempts/1/q/1` 401. 5/5 services active. Config SHAs
unchanged.

**Phase 08** — boot, `/healthz` 200, anon `GET /attempts/1/result` 401,
anon `GET /attempts/1/review` 401, anon `POST /questions/1/reports`
401, anon `GET /admin/question-reports` 401. 5/5 services active.
Config SHAs unchanged. uvicorn stopped cleanly.

---

## 7. Practice / exam flow verification

- Start (HTTP) — `POST /attempts/start` (CSRF + auth) returns 303 to
  `/attempts/{id}/q/1`. Student-only paths verified.
- Question delivery — `GET /attempts/{id}/q/{order}` renders the
  question, options, jump-to grid, and (in exam mode) the timer.
- Autosave — `POST /attempts/{id}/q/{order}/answer` returns 204; idempotent;
  invalid label rejected with 400; cross-user 403; anon 401.
- Flag — `POST /attempts/{id}/q/{order}/flag` flips the boolean, returns
  the partial.
- Timer enforcement — server backdated `started_at` triggers
  `AttemptExpiredError`, idempotent submit + redirect to
  `/submitted` page.
- Submit — `POST /attempts/{id}/submit` (CSRF) finalises and
  redirects. Idempotent.

## 8. Scoring / result / review verification

- Submit pipeline computes score in same transaction as `finished_at`
  set; `attempts.score_percent`, `correct_count`, `wrong_count`,
  `passed` populated; `attempt_answers.is_correct` set per row.
- All-correct attempt → 100% / passed=true.
- Unanswered attempt → 0% / passed=false (assumes `passing_score_percent`
  set; `passed=None` otherwise).
- Multi-choice — picking only one of two correct labels → wrong.
- Idempotent re-submit — `finished_at` not overwritten;
  `audit.attempt.submitted` exactly once.
- Question edits after attempt — `attempt_answers` rows untouched
  (frozen `order_index` + `question_id`).
- Result page — owner: 200; cross-user: 403; anon: 401.
- Review list — wrong-only filter shows fewer rows than all.
- Review question — selected vs correct visible, "you picked"
  marker, "Wrong" badge present.
- Question report POST — creates row + audit entry; rate-limit hooks
  reserved for Phase 09.
- Admin queue — list (status filter), resolve, reject; non-admin 403.

---

## 9. Docs updated by each phase (separately)

Phase 07 updates:
- `docs/project-roadmap.md` — Phase 07 row → ✅.
- `docs/project-changelog.md` — Phase 07 entry: highlights + decision rationale + LXC verification.
- `docs/system-architecture.md` — new "Practice & exam mode (Phase 07)" section.

Phase 08 updates (separate sections, separate entries):
- `docs/project-roadmap.md` — Phase 08 row → ✅.
- `docs/project-changelog.md` — Phase 08 entry: highlights + decision rationale + LXC verification.
- `docs/system-architecture.md` — new "Scoring + result/review (Phase 08)" section, sitting above Phase 07 in the file (most-recent first).

---

## 10. Skills / rules used (with file paths)

| Resource | Path |
|----------|------|
| Project CLAUDE.md | `E:\Vibe Code\Vibe Code\Exam\CLAUDE.md` |
| User global CLAUDE.md | `C:\Users\Administrator\.claude\CLAUDE.md` |
| Project rules | `.claude/rules/{development-rules,primary-workflow,documentation-management,orchestration-protocol,team-coordination-rules}.md` |
| Phase 07 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-07-practice-exam-modes.md` |
| Phase 08 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-08-attempts-scoring-result.md` |
| docs skill | `.claude/skills/docs/SKILL.md` (closest available, applied inline) |
| Phase 03 audit writer | `app/audit/writer.py` |
| Phase 03 RBAC | `app/auth/permissions.py` |
| Phase 03 CSRF helpers | `app/auth/csrf.py` |
| Phase 04 admin shell | `app/routers/admin/_common.py` |
| Phase 04 publishable filter | `app/routers/public/catalog_query.py:published_exam_filter` |
| RTK | `/c/Users/Administrator/AppData/Local/Microsoft/WinGet/Links/rtk` |

No subagents (planner / researcher / tester / code-reviewer) were
spawned. Context budget preserved.

---

## 11. RTK usage and estimated token savings

- **Available?** Yes — RTK 0.36.0; no project hooks installed (`rtk init -g` not run).
- **Used for:**
  - `rtk read` of both Phase 07 and Phase 08 plans before implementation.
  - Native `pytest --tb=no` / `--tb=short` flags for filtered failure output.
  - SSH command piping through `head -N` / `tail -N` to avoid drowning in PG SQL log noise during real-DB pytest runs.
- **Estimated savings (combined Phase 07 + Phase 08):** **5 k – 10 k tokens.**
  The biggest win was during the `DetachedInstanceError` debugging
  loop — the SQLAlchemy log noise alone would have been multi-thousand-line outputs without filtering.
- **Honest assessment:** RTK's biggest gain on this project remains
  pytest output filtering. Markdown plan reads (`rtk read` on the
  plan files) saved a small amount; the discipline of `--tb=no`
  saved more.
- **Safety-critical context kept uncompressed (verbatim into reports
  and changelog):**
  - Blog-stack no-touch list (blogdb / blog role / `/srv/blog-website` / `/srv/Exam`).
  - LXC sync procedure (rsync/tar exclusions; `.env` preservation).
  - Host/port restriction: `127.0.0.1:8001` only.
  - Migration apply commands (none new in P07/P08, but the no-mig statement is verbatim).
  - Stop-on-failure rule.
  - Shutdown rule (only the temporary uvicorn process).
  - "Do not start Phase 09."

---

## 12. Blog safety verification

Pre-session baseline (recorded at the start of the prior P05/P06
session and again at the start of this session):

```
SHA256 pg_hba.conf:    548d74c9f011125fa7c94b44531232e9612977f2b9e64f49d36bac1e2a0d3115
SHA256 postgresql.conf: e6a345c59c41695e99e274c63fc12facc16e20972b171a95739387f193238b41
SHA256 redis.conf:      f9f998aa158cf6d523048933953596844597ff2d7b649afb7beb1f3aebd20f7b
```

Post-Phase 08 final check (2026-04-30 00:10):

```
SHA256 pg_hba.conf:    548d74c9f011125fa7c94b44531232e9612977f2b9e64f49d36bac1e2a0d3115  ✅ unchanged
SHA256 postgresql.conf: e6a345c59c41695e99e274c63fc12facc16e20972b171a95739387f193238b41  ✅ unchanged
SHA256 redis.conf:      f9f998aa158cf6d523048933953596844597ff2d7b649afb7beb1f3aebd20f7b  ✅ unchanged
Services: blog.service active, postgresql active, redis-server active,
          nginx active, cloudflared active.                              ✅
/srv/blog-website ownership/contents:                                     ✅ untouched
/srv/Exam:                                                                ✅ untouched
```

---

## 13. Temporary uvicorn process stopped? **Yes.**

```
ssh exam-lxc 'ps -ef | grep uvicorn | grep -v grep | wc -l'    → 0
ssh exam-lxc 'ss -tlnp | grep :8001 | wc -l'                    → 0
```

`pkill -f 'uvicorn.*8001'` issued after each smoke run (P07 + P08).
Zero uvicorn processes after the session.

---

## 14. Core services still active? **Yes.**

`systemctl is-active`:

| Service | Status |
|---------|--------|
| postgresql | active |
| redis-server | active |
| nginx | active |
| cloudflared | active |
| blog.service | active |

LXC was not rebooted, no PG/Redis restart, no nginx reload, no
cloudflared restart.

---

## 15. Remaining risks / non-blockers

### Phase 07
- 24h idle cleanup not implemented — Phase 10 cron will mark
  long-stale attempts `abandoned`.
- Per-attempt content snapshot not implemented — admin edits during
  in-progress attempts shift question_text but not identity. Phase 09.
- No admin viewer for cross-user attempts — flagged for Phase 09.

### Phase 08
- Cross-user admin attempt-result viewer not implemented — same
  Phase 09 reservation.
- Topic-weighted score not implemented — PRD doesn't require it
  for Phase 1.
- Partial-credit multi-choice not implemented — Phase 2 enhancement.
- Question-content snapshot per attempt not implemented — Phase 06
  edits between submit and review are reflected on the review page.
  Acceptable for Phase 1; flagged.

### Cross-phase
- LXC clock is ~4 minutes behind the Windows dev box; tar archives
  emit benign "timestamp in future" warnings. Cosmetic only.

---

## 16. Whether it is safe to proceed to Phase 09

**Yes — but Phase 09 is OUT OF SCOPE for this session.** Per the brief
I have stopped at the end of Phase 08. Phase 09 (Security hardening
& rate limiting) pre-conditions are now met:

- Auth + RBAC + CSRF + rate-limit ready (Phase 03). ✅
- Catalog visibility filter helper established (Phase 04). ✅
- Excel imports and admin curation ready (Phase 05 / 06). ✅
- Practice / exam mode shipped with frozen `order_index` (Phase 07). ✅
- Result / review screens with audited mutations (Phase 08). ✅

When the user explicitly approves Phase 09, the entry-point will be
`plans/260428-1631-phase-1-mvp-exam-platform/phase-09-security-hardening.md`.
Phase 09 will:
- Add per-attempt content snapshot.
- Add admin cross-user viewer.
- Add report-endpoint rate limit (30/h/user, plan §Security).
- Tighten CSP, full HTML sanitizer policies.
- Encrypted backup groundwork.

---

## Summary one-liner

Phase 07 (practice / exam mode with frozen `order_index` + server-
authoritative timer) and Phase 08 (set-based scoring + result + review
+ student question-reports + admin triage queue) both complete on
local + LXC; 166/166 tests pass on real PG+Redis; blog stack
untouched; uvicorn stopped; ready for Phase 09 when explicitly
approved.
