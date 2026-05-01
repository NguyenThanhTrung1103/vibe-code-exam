# Phase 12 — Beta Launch Readiness — Completion Report

**Plan:** `plans/260428-1631-phase-1-mvp-exam-platform/phase-12-beta-launch.md`
**Date:** 2026-04-30 14:00 (Asia/Saigon)
**Status:** ✅ Complete (Gate-A scaffolding scope; live content seed
+ Gate-B public soft-launch are operator actions, documented).

---

## 1. Files changed

### Added (10)
- `docs/disclaimer.md`              — independent-platform disclaimer.
- `docs/terms-of-service.md`        — beta-scoped ToS draft.
- `docs/privacy-policy.md`          — beta privacy policy draft.
- `docs/dmca-takedown.md`           — DMCA workflow.
- `docs/beta-feedback-log.md`       — empty table for the beta cycle.
- `docs/readiness-checklist.md`     — Gate A + Gate B status.
- `content/topics-seed.sql`         — idempotent NSE4 topic seed.
- `app/routers/public/legal.py`     — mounts legal pages at `/legal/{slug}`.
- `app/templates/public/legal.html` — render shell.
- `tests/test_legal_pages.py`       — 7 hermetic tests.

### Modified
- `app/main.py` — register `public_legal.router`.
- `app/templates/_layout/footer.html` — legal-page links + beta badge +
  not-affiliated note.
- `docs/project-roadmap.md`, `project-changelog.md`,
  `system-architecture.md`.

### Deferred (operator actions, documented in `readiness-checklist.md`)
- Importing 100+ NSE4 questions (no first-party source content).
- 5 beta users completing real attempts.
- Counsel review of legal pages.
- DNS for `exam.example.com` + Nginx vhost install + Certbot TLS.
- Off-site restic backup configuration.
- 1 k seeded user performance smoke.
- Gating `/auth/register` behind invitations.

---

## 2. DB migration

**None.** Topics seed is SQL data only and runs only after an NSE4 exam
exists.

---

## 3. Tests / lint / mypy results (LXC)

| Gate | Result |
|------|--------|
| `ruff check app tests migrations` | ✅ All checks passed |
| `ruff format --check app tests migrations` | ✅ 110 files clean |
| `mypy app` | ✅ 81 source files, no issues |
| Hermetic `pytest` (Windows) | ✅ 145 / 145 |
| Hermetic `pytest` (LXC) | ✅ 145 / 145 |
| `EXAM_PLATFORM_TEST_REAL_DB=1 pytest` (LXC) | ✅ **227 / 227** |

---

## 4. Final E2E smoke (against the systemd app on 127.0.0.1:8001)

| Surface | Result |
|---------|--------|
| `GET /` | 200 |
| `GET /legal/disclaimer` | 200 (renders `docs/disclaimer.md`) |
| `GET /legal/terms` | 200 |
| `GET /legal/privacy` | 200 |
| `GET /legal/dmca` | 200 |
| `GET /search/exams?q=test` | 200 |
| `GET /healthz` | 200 `{db:ok,redis:ok}` |
| `GET /readyz` | 200 `{… migrations.status=ok, current=a1b2c3d4e5f6}` |
| `GET /auth/login` | 200 (CSRF cookie issued) |
| `GET /auth/register` | 200 (rate-limited 5/h/IP) |
| `POST /attempts/start` (anon) | 401 |
| `POST /admin/imports` (anon) | 401 |
| `POST /questions/1/reports` (anon) | 401 |
| `GET /admin/providers` (anon) | 401 |
| `GET /admin/question-reports` (anon) | 401 |
| `GET /attempts/1/result` (anon) | 401 |
| `GET /attempts/1/review` (anon) | 401 |
| Phase 09 security headers on `/legal/disclaimer` | ✅ all present |
| Footer legal links count on every page | 4 / 4 |

The flow `admin login → catalog → import → student attempt → result →
review` is exercised end-to-end by the 220-test real-DB suite (Phase 03
auth, Phase 04 catalog, Phase 05 import, Phase 06 question CRUD, Phase
07 attempt, Phase 08 scoring/result/review). Running the full test
suite against the same DB the systemd app reads is the strongest
practical Phase 1 smoke; an interactive session with cookies + CSRF
would replicate what the suite already covers.

---

## 5. Auth/register risk check

Open registration (`POST /auth/register`) remains enabled but:
- Rate-limited to **5 requests / hour / IP** (Phase 09).
- Defaults new accounts to `student` role (admin promotion required for
  any admin route).
- App is **loopback-only** (Phase 11) — no public reachability.
- Documented as a Gate-B blocker in `docs/readiness-checklist.md`.

Mitigation before public soft-launch: gate behind invite tokens or
admin-issued accounts.

---

## 6. Backup status

| Item | Status |
|------|--------|
| `pg-backup.sh` deployed | ✅ `/srv/exam-platform/ops/backup/pg-backup.sh` |
| `exam-pg-backup.timer` enabled | ✅ active, next 2026-05-01 02:30 UTC |
| Manual drill executed | ✅ `ops/docs/dr-drill-log.md` 2026-04-30 entry |
| Off-site restic | ⏸ Gate B — `RESTIC_REPO` not configured |
| Restore runbook | ✅ `ops/docs/restore-runbook.md` |
| RTO / RPO | RTO < 5 min (drill); RPO ≤ 24 h (daily timer) |

---

## 7. Healthcheck status

- `/healthz` 200, average response < 50 ms (uvicorn loopback).
- `/readyz` 200, alembic head `a1b2c3d4e5f6` matches script directory.
- systemd: `exam-platform-web.service` and `exam-pg-backup.timer` both
  `active`.

---

## 8. Blog safety verification

```
SHA256 pg_hba.conf:    548d74c9...  ✅ unchanged
SHA256 postgresql.conf: e6a345c5...  ✅ unchanged
SHA256 redis.conf:      f9f998aa...  ✅ unchanged
systemctl is-active postgresql redis-server nginx cloudflared blog.service:
  active active active active active                                    ✅
curl http://127.0.0.1:8000/ → 301                                       ✅ blog gunicorn unaffected
/srv/blog-website                                                        ✅ untouched
```

---

## 9. Skills / rules used

| File | Path | Why |
|------|------|-----|
| Phase 12 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-12-beta-launch.md` | Source of truth |
| development-rules / primary-workflow / documentation-management / orchestration-protocol / team-coordination-rules | `.claude/rules/*.md` | YAGNI/KISS/DRY + plan org + docs trigger |
| docs skill | `.claude/skills/docs/SKILL.md` | Closest to ck:docs — applied inline |
| Phase 09 sanitiser | `app/security/sanitize.py` | Renders Markdown legal pages safely |
| Phase 02 catalog | `app/models/catalog.py` (`Topic`) | Topics seed targets the existing schema |
| Phase 11 systemd | `/etc/systemd/system/exam-platform-web.service` | Final E2E smoke runs against the systemd app |
| RTK | `/c/Users/Administrator/AppData/Local/Microsoft/WinGet/Links/rtk` | `rtk read` of P12 plan; pytest filters |

No subagents spawned.

---

## 10. Decision rationale

- **Legal pages rendered from Markdown via the sanitiser** — content
  updates are git commits, not deploys; the sanitiser guarantees no
  XSS vector even if a contributor writes raw HTML by accident.
- **Topics-seed SQL keyed on (exam_id, slug)** — idempotent, replayable,
  no schema change.
- **Beta-feedback log starts empty** — fixture rows would lie.
- **Readiness checklist treated as a living doc** — Gate-A items
  ticked, Gate-B items kept in the same file so the operator has one
  place to look.
- **Final E2E smoke is HTTP-surface + suite** — interactive admin →
  attempt → review walk-throughs would require staging the LXC
  cookies; the existing 220-test real-DB suite already covers every
  router exhaustively, on the same DB the systemd app reads, against
  the production layout.
- **Open registration kept** — rate-limited and behind a loopback;
  gating is the operator's call before public exposure.

### Alternatives rejected

| Alternative | Why rejected |
|-------------|--------------|
| Author 100 placeholder NSE4 questions | Plan §27 / Disclaimer say content is "admin-supplied"; fake fixtures would mislead beta testers and contaminate the audit log. |
| Auto-disable `/auth/register` now | Would break Phase 03 real-DB test fixtures; documented gate is sufficient for loopback-only Phase 1. |
| Generate legal pages with code | Markdown-as-source is simpler and reviewable. |
| Run UptimeRobot probe in this session | Requires founder credentials + DNS — outside agent scope. |

---

## 11. Phase 12 RTK Usage Report

- **RTK available?** Yes (v0.36.0).
- **When + where used:**
  - `rtk read` of `phase-12-beta-launch.md` (162 lines).
  - `pytest --tb=line / --tb=short` for filtered output.
  - SSH `head/tail` discipline on database row counts.
- **Estimated savings (Phase 12):** ≈ **2 k – 3 k tokens.** Smaller than
  earlier phases because Phase 12 is largely docs + glue; less log noise.
- **Safety-critical context kept uncompressed:**
  - "Loopback-only — no public exposure in this run."
  - "Do not touch blogdb / `/srv/blog-website` / blog.service."
  - "Auth/register stays open behind rate limit + loopback for Phase 1."
  - LXC sync paths (`/srv/exam-platform-dev` → `/srv/exam-platform`).
  - Stop-on-failure / no post-MVP rules.

---

## 12. Remaining risks / non-blockers

- **Empty content** — DB has 4 dev exams, 0 published, 0 topics seeded
  (NSE4 exam doesn't yet exist). Topic seed is ready; founder action
  required to import real questions.
- **Legal pages are drafts** — counsel review is a Gate-B prereq.
- **Open `/auth/register`** — deferred to Gate B for invitation gating.
- **No real beta users yet** — operator action.
- **No public exposure** — Phase 11 / 12 Gate-B prereqs (Nginx vhost,
  TLS, DNS, off-site backup, UptimeRobot, performance smoke) all
  remain outstanding by design.

---

## 13. Phase 12 complete?

**Yes (Gate-A scaffolding scope per brief).** All Phase 12 quality
gates green; operator-only Gate-B items documented in
`docs/readiness-checklist.md`. Stopping per the brief — no post-MVP
phase started.

**Status:** DONE

---

## 14. What the app can do now

- Public landing + catalog + search.
- `/legal/{disclaimer,terms,privacy,dmca}` served from Markdown.
- Auth: register (rate-limited), login (rate-limited), logout, /me.
- Admin: provider/course/exam/topic/question CRUD, audit log,
  Excel import wizard (upload→map→preview→confirm), question report
  triage queue.
- Student: practice + exam mode, autosave, flag, navigate, submit.
- Scoring: set-equality, idempotent submit.
- Result page + review per-question (selected vs correct).
- File a question report.
- Healthz + Readyz with alembic head check.
- All security headers (CSP, X-Frame, X-CTO, Referrer, Permissions,
  HSTS-in-prod), CSRF, per-route rate limits, sanitised Markdown
  render, hardened upload validation.
- systemd-managed web service binding 127.0.0.1:8001 with kernel-level
  hardening; daily backup timer scheduled; full restore drill
  documented and tested.

---

## 15. Whether it is safe to plan post-MVP AI verification later

**Yes — safe to plan, not safe to start automatically.** The MVP
foundation is ready: per-question audit hooks (Phase 03), per-question
explanations field (Phase 06), question reports + admin triage queue
(Phase 08), confidence badge ("Unverified — admin-supplied"; Phase 12).
Post-MVP AI verification can be added without schema redesign by:

1. Adding a `verifications` table keyed on `(question_id, version)`.
2. Adding an evidence cache table.
3. Wiring an offline worker that consumes the audit log of question
   edits and re-verifies asynchronously.
4. Updating the `Confidence` badge to reflect verifier output.

None of that should be auto-approved by an unattended run; the founder
should choose the AI provider and review costs first.

---

## 16. Unresolved questions

1. Does the user want me to clean up `/srv/Exam` (the path the brief
   bars) — extra files were synced there during the Phase 09 path
   mistake? Currently untouched since.
2. Should the Phase 12 / Gate-B items in
   `docs/readiness-checklist.md` get a tracking issue, or stay in the
   doc?
3. Is the user ready to register the real `exam.example.com` domain
   (or pick a real one) before public soft-launch?
