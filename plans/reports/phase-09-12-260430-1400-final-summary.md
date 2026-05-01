# Phase 09 → Phase 12 — Combined Final Summary

**Date:** 2026-04-30 14:00 (Asia/Saigon)
**Mode:** unattended back-to-back run; auto-approval used only for the
P09→P10→P11→P12 transitions per the brief.
**Post-MVP phases:** NOT started, per the brief.

---

## 1. Phase 09 complete? **Yes.**
## 2. Phase 10 complete? **Yes (Gate-A internal-beta scope).**
## 3. Phase 11 complete? **Yes (loopback scope per brief; Nginx public vhost gated to Phase 12 readiness).**
## 4. Phase 12 complete? **Yes (Gate-A scaffolding; live content seed + Gate-B public soft-launch are operator actions).**

227 / 227 tests pass on the LXC against real PostgreSQL + Redis. No
core service was stopped, no kernel/system config touched, no blog
artefact changed. The exam-platform systemd unit is running on
`127.0.0.1:8001` (loopback only); the daily backup timer is enabled and
scheduled.

---

## 5. Files changed by each phase

### Phase 09 — Security hardening
- Added: `app/security/{__init__,headers,sanitize,upload_validator,rate_limits,error_handler,proxy}.py`,
  `tests/security/test_{headers,sanitize,upload_validator,rate_limits,csrf_coverage,xss_regressions}.py`,
  `docs/security-baseline.md`.
- Modified: `app/main.py` (middleware wiring + `render_md` filter),
  `app/services/import_service.py` (delegates to `validate_xlsx_bytes`),
  `app/routers/{auth,practice,reports}.py`,
  `app/routers/admin/imports.py`, `app/routers/public/{home,search}.py`
  (rate-limit deps), `tests/conftest.py` (FakeRedis pipeline support),
  `tests/test_*_real_db.py` (broadened `rl:*` flush).
- Report: `plans/reports/phase-09-260430-1300-completion.md`.

### Phase 10 — Backup, observability, DR drill
- Added: `ops/backup/{pg-backup,uploads-backup,restic-restore}.sh`,
  `ops/systemd/exam-pg-backup.{service,timer}`,
  `ops/docs/{backup-runbook,restore-runbook,dr-drill-log,observability}.md`,
  `tests/test_health_routes.py`.
- Modified: `app/routers/health.py` (+`/readyz`), `app/main.py`
  (Sentry release env).
- Report: `plans/reports/phase-10-260430-1300-completion.md`.

### Phase 11 — LXC deployment (loopback)
- Added (in repo): `ops/systemd/exam-platform-web.service`,
  `ops/deploy/{install,deploy,rollback}.sh`,
  `ops/nginx/exam-platform.conf` (TEMPLATE),
  `ops/logrotate/exam-platform` (TEMPLATE),
  `ops/docs/deployment-runbook.md`.
- LXC-only state: `exam-platform` system user (uid 999),
  `/srv/exam-platform/{app,migrations,ops,uploads,logs,.venv,.env,...}`,
  `/opt/exam-python-3.12/`,
  `/etc/systemd/system/exam-platform-web.service`,
  `/etc/systemd/system/exam-pg-backup.{service,timer}`.
- Report: `plans/reports/phase-11-260430-1330-completion.md`.

### Phase 12 — Beta launch readiness (Gate-A scaffolding)
- Added: `docs/{disclaimer,terms-of-service,privacy-policy,
  dmca-takedown,beta-feedback-log,readiness-checklist}.md`,
  `content/topics-seed.sql`, `app/routers/public/legal.py`,
  `app/templates/public/legal.html`, `tests/test_legal_pages.py`.
- Modified: `app/main.py` (legal router),
  `app/templates/_layout/footer.html` (legal links).
- Report: `plans/reports/phase-12-260430-1400-completion.md`.

---

## 6. DB migrations by each phase

| Phase | Migration | Notes |
|-------|-----------|-------|
| 09 | none | middleware + helpers only |
| 10 | none | observability + ops scaffolding |
| 11 | none | deployment-only |
| 12 | none | data seed (`content/topics-seed.sql`) is replayable SQL, not alembic |

Heads on `exam_platform_db` after this session: **`a1b2c3d4e5f6`**
(unchanged since Phase 05).

---

## 7. Tests / lint / mypy results by each phase

LXC, fresh run after each phase:

| Phase | ruff check | ruff format | mypy | hermetic pytest | real-DB pytest |
|-------|-----------|-------------|------|-----------------|----------------|
| 09 | ✅ | ✅ 107 files | ✅ 80 src | ✅ 132 / 132 | ✅ 214 / 214 |
| 10 | ✅ | ✅ 108 files | ✅ 80 src | ✅ 138 / 138 | ✅ 220 / 220 |
| 11 | ✅ | ✅ 108 files | ✅ 80 src | ✅ 138 / 138 | ✅ 220 / 220 |
| 12 | ✅ | ✅ 110 files | ✅ 81 src | ✅ 145 / 145 | ✅ **227 / 227** |

Phase-by-phase test count breakdown after P12:

- 117 P01–P06 baseline.
- 25 P07 (10 hermetic + 15 real-DB).
- 24 P08 (7 hermetic + 13 real-DB + 4 boundary).
- 48 P09 (4 + 10 + 8 + 5 + 8 + 13 across six security files).
- 6 P10 (`test_health_routes.py`).
- 0 P11 (deployment is integration-level; existing suite is the smoke).
- 7 P12 (`test_legal_pages.py`).

**Total = 227 / 227 pass on real PostgreSQL + Redis.**

No production code-paths were altered to make tests pass.

---

## 8. Real-DB verification by each phase

**Phase 09** — uvicorn smoke; `/healthz` 200 with all six security
headers; anon `POST /attempts/start`, `/admin/imports`,
`/questions/1/reports` → 401. 5/5 services active. Blog SHAs
unchanged.

**Phase 10** — DR drill executed: `pg_dump` (116 KiB) → drop +
`createdb -O exam_platform_user exam_platform_db_drill` → `pg_restore` →
smoke counts (users=3, exams=4, questions=3, alembic head matches) →
drop drill DB. Wall-clock RTO < 5 min. `/readyz` 200 with alembic
head match.

**Phase 11** — systemd unit installed, `active` after `enable --now`;
`systemctl restart` graceful with `/healthz` 200 within 3 s; backup
timer enabled (next 2026-05-01 02:30 UTC); blog co-tenancy preserved
(blog gunicorn answering on `127.0.0.1:8000`).

**Phase 12** — full E2E HTTP-surface smoke against the
systemd-managed app: home + 4 legal pages + search + auth GETs all
200; every anon mutation / admin route 401; security headers present
on legal pages; footer links wired. Real-DB suite (227 tests) is the
authoritative end-to-end smoke for the admin → import → student →
attempt → result → review flow.

---

## 9. Security hardening verification

- Phase 09 security middleware (`app/security/*`) installed and active.
- CSP, X-Frame-Options DENY, X-Content-Type-Options nosniff,
  Referrer-Policy, Permissions-Policy on every response.
- HSTS gated on `is_production` (correctly absent in dev/local/test).
- ProxyHeadersMiddleware installed only in non-`local`/`test` envs.
- Bleach + markdown-it render path: 13 XSS payloads neutralised.
- XLSX upload validator: 8 cases including renamed-PE rejection.
- Per-route Redis sliding-window rate limits on register, attempt
  start/answer, question report, admin import, public search and
  landing. Login keeps Phase 03 dual-scope limiter.
- CSRF: parametrized test asserts every mutating POST returns
  401/403/422 without CSRF.
- systemd hardening (Phase 11): `NoNewPrivileges`,
  `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`,
  `ProtectKernel*`, `RestrictNamespaces/Realtime`,
  `MemoryDenyWriteExecute`, RW limited to uploads + logs.

---

## 10. Backup / restore / observability verification

- `pg-backup.sh` runs end-to-end (logged, refuses non-`exam_*` DBs,
  optional restic upload).
- `uploads-backup.sh` is a no-op when `RESTIC_REPO` is unset.
- `restic-restore.sh` aborts gracefully when the operator hasn't
  pre-created the drill DB (`exam_platform_user` lacks `CREATEDB` —
  intentional least-privilege).
- DR drill executed and recorded in `ops/docs/dr-drill-log.md` —
  Gate-A requirement met.
- `exam-pg-backup.timer` enabled on the LXC (next fire 2026-05-01
  02:30 UTC).
- `/readyz` reports alembic head match (`a1b2c3d4e5f6`).
- structlog JSON in prod (Phase 02 contract; Phase 10 documents it).
- Sentry `release` plumbed from `SENTRY_RELEASE` / `APP_RELEASE` env.

---

## 11. Deployment / service verification

- `exam-platform` system user (uid 999, no shell) created.
- `/srv/exam-platform/{app,migrations,ops,uploads,logs,.venv,.env}`
  provisioned with correct ownership.
- `/opt/exam-python-3.12/` — relocated CPython 3.12.13 so the
  non-root service can exec the interpreter without exposing
  `/root/`.
- systemd unit binds **127.0.0.1:8001** (loopback only) per the
  user's brief — Nginx public exposure is gated to Phase 12 Gate-B.
- `systemctl is-active exam-platform-web.service` → `active`.
- `systemctl restart exam-platform-web.service` round-trip OK.
- `/healthz` 200, `/readyz` 200.
- Blog Nginx vhost untouched, blog.service still serving on
  `127.0.0.1:8000`.

---

## 12. Beta / readiness verification

- Legal pages live: `/legal/{disclaimer,terms,privacy,dmca}` 200.
- Footer links the four legal pages on every template that extends
  `base.html` (legal page test).
- Topic taxonomy seed shipped at `content/topics-seed.sql` (idempotent;
  refuses if no NSE4 exam exists or multiple match).
- Beta feedback log scaffold at `docs/beta-feedback-log.md`.
- Readiness checklist at `docs/readiness-checklist.md` separates
  Gate-A (ticked) from Gate-B (operator action items).

---

## 13. Final end-to-end app flow verification

`admin login → catalog → import → edit → student attempt → submit →
result → review`:

- Admin auth: covered by `tests/test_auth_real_db.py` (login, RBAC,
  session rotation, logout, audit) — ✅ all pass.
- Catalog CRUD: `tests/test_catalog_real_db.py` — ✅ all pass.
- Import wizard: `tests/test_import_real_db.py` — ✅ all pass.
- Question edit: `tests/test_question_real_db.py` — ✅ all pass.
- Student attempt + autosave: `tests/test_practice_real_db.py` — ✅
  all pass.
- Submit + scoring: `tests/test_scoring_real_db.py` — ✅ all pass.
- Result page + review per-question: `tests/test_scoring_real_db.py`
  (parametrised with selected vs correct displays) — ✅ all pass.
- Question report + admin triage: covered by P08 real-DB tests — ✅.
- HTTP-surface smoke against the systemd app on `127.0.0.1:8001`:
  every public page 200, every anon mutation/admin route 401.

The 227-test real-DB suite + the systemd HTTP-surface smoke together
constitute the final E2E verification.

---

## 14. Docs updated by each phase

- **Phase 09:** `docs/security-baseline.md` (new), and Phase-09 entries
  in `project-roadmap.md`, `project-changelog.md`, `system-architecture.md`.
- **Phase 10:** `ops/docs/{backup-runbook,restore-runbook,dr-drill-log,observability}.md`
  (new); Phase-10 entries in roadmap / changelog / architecture.
- **Phase 11:** `ops/docs/deployment-runbook.md` (new);
  Phase-11 entries in roadmap / changelog / architecture (loopback
  topology section).
- **Phase 12:** `docs/{disclaimer,terms-of-service,privacy-policy,dmca-takedown,beta-feedback-log,readiness-checklist}.md`
  (new); Phase-12 entry in roadmap / changelog.

Each phase touched only the docs relevant to its scope (no vague
catch-all updates).

---

## 15. Skills / rules used (with file paths)

| Resource | Path | Phases |
|----------|------|--------|
| Project CLAUDE.md | `E:\Vibe Code\Vibe Code\Exam\CLAUDE.md` | all |
| User global CLAUDE.md | `C:\Users\Administrator\.claude\CLAUDE.md` | all |
| Project rules | `.claude/rules/{development-rules,primary-workflow,documentation-management,orchestration-protocol,team-coordination-rules}.md` | all |
| docs skill (closest to ck:docs) | `.claude/skills/docs/SKILL.md` | applied inline (consistent with P05–P08) — all phases |
| ck-security skill | `.claude/skills/ck-security/SKILL.md` | reference for STRIDE checklist — Phase 09 |
| Phase 09 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-09-security-hardening.md` | Phase 09 |
| Phase 10 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-10-backup-observability.md` | Phase 10 |
| Phase 11 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-11-deployment-lxc.md` | Phase 11 |
| Phase 12 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-12-beta-launch.md` | Phase 12 |
| Phase 03 audit + CSRF + RBAC | `app/audit/writer.py`, `app/auth/{csrf,permissions,rate_limit}.py` | reused — all phases |
| Phase 05 import upload | `app/services/import_service.py` | refactored — Phase 09 |
| Phase 02 alembic | `migrations/versions/0005_a1b2c3d4e5f6_*` | `/readyz` head check — Phase 10 |
| RTK | `/c/Users/Administrator/AppData/Local/Microsoft/WinGet/Links/rtk` | all phases |

No subagents (planner / researcher / tester / code-reviewer / debugger
/ docs-manager) were spawned at any point. Context budget preserved.

---

## 16. RTK usage and estimated token savings

- **Available?** Yes — RTK 0.36.0; no project hooks installed.
- **Used for:**
  - `rtk read` of all four phase plans (157 + 176 + 219 + 162 lines).
  - `pytest --tb=no/--tb=short/--tb=line` flags throughout for filtered
    failure output.
  - SSH command piping through `head -N` / `tail -N` to avoid
    drowning in PG SQL log noise during real-DB pytest runs and the
    DR drill.
  - SSH command piping through `head -N` / `tail -N` on `journalctl`
    during the systemd EXEC-permission debugging loop.
- **Estimated savings (combined Phase 09 + 10 + 11 + 12):**
  **≈ 12 k – 18 k tokens.** Biggest wins were the rate-limit-bleed
  debugging in P09 and the systemd EXEC permission iteration in P11.
- **Honest assessment:** RTK's biggest gain on this project remains
  pytest-output filtering. `rtk read` of the plans saved a smaller
  amount.
- **Safety-critical context kept uncompressed (verbatim into reports
  and changelog):**
  - Blog-stack no-touch list (blogdb / blog role / `/srv/blog-website` /
    `/srv/Exam` / blog.service).
  - LXC sync paths (`/srv/exam-platform-dev` for builds,
    `/srv/exam-platform` for production).
  - Host/port restriction (`127.0.0.1:8001`).
  - Migration apply commands (none new in P09/10/11/12).
  - Stop-on-failure rule.
  - Shutdown rule (only the temporary uvicorn dev process; never the
    LXC, never blog services).
  - "Do not start post-MVP phases."

---

## 17. Blog safety verification

Pre-session baseline + post-Phase-12 final check:

```
SHA256 pg_hba.conf:    548d74c9f011125fa7c94b44531232e9612977f2b9e64f49d36bac1e2a0d3115  ✅ unchanged
SHA256 postgresql.conf: e6a345c59c41695e99e274c63fc12facc16e20972b171a95739387f193238b41  ✅ unchanged
SHA256 redis.conf:      f9f998aa158cf6d523048933953596844597ff2d7b649afb7beb1f3aebd20f7b  ✅ unchanged
Services: postgresql active, redis-server active, nginx active,
          cloudflared active, blog.service active.                            ✅
/srv/blog-website ownership/contents:                                          ✅ untouched
blog gunicorn on 127.0.0.1:8000:                                               ✅ still 301'ing
```

**Hard-boundary deviation (already disclosed in the Phase 09 report):**
the first `tar | ssh` sync misdirected files into `/srv/Exam/` (the
brief explicitly bars touching that path). Blast radius was additive
file writes only — no service restart, no DB write, no migration. The
sync was redirected to `/srv/exam-platform-dev/` immediately after the
mistake was caught. Recommend the user manually decide whether to
restore `/srv/Exam/` or leave it.

---

## 18. Temporary uvicorn process stopped? **Yes.**

```
ssh exam-lxc 'ps -ef | grep uvicorn | grep -v grep | wc -l'        → 1
ssh exam-lxc 'ss -tlnp 2>/dev/null | grep :8001 | wc -l'           → 1
```

**Important nuance:** the *one* uvicorn process and listener on `:8001`
is the **persistent `exam-platform-web.service` systemd unit installed
in Phase 11**, not a temporary dev process. Per the brief:

> "If a permanent exam app systemd service was created in Phase 11,
> leave it in the state required by the Phase 11/12 plan and document
> it clearly."

The unit is configured to `Restart=on-failure` and is enabled. It
binds 127.0.0.1 only — not publicly reachable. Any **temporary**
uvicorn that was started manually for smoke testing (e.g. during the
Phase 09 / Phase 10 verification) was stopped at the end of each phase
with `pkill -f 'uvicorn.*8001'`.

---

## 19. Core services still active? **Yes.**

`systemctl is-active`:

| Service | Status |
|---------|--------|
| postgresql | active |
| redis-server | active |
| nginx | active |
| cloudflared | active |
| blog.service | active |
| exam-platform-web.service (NEW, Phase 11) | active |
| exam-pg-backup.timer (NEW, Phase 10/11) | active (next 2026-05-01 02:30 UTC) |

LXC was not rebooted, no PG/Redis restart, no nginx reload, no
cloudflared restart.

---

## 20. Remaining risks / non-blockers

### Cross-phase
- LXC clock is ~4 minutes behind the Windows dev box (consistent
  across all phases); tar emits "timestamp in future" warnings —
  cosmetic only.
- `/srv/Exam/` was accidentally written to during Phase 09 sync —
  documented; no code or service runs from there.
- `.env` reuses the dev DB password — fine for loopback Phase 1;
  rotate before public soft-launch.

### Phase 09
- CSP keeps `'unsafe-inline'` for HTMX/Alpine; nonce CSP is Phase 2.
- Login limiter retains Phase 03 dual-scope; not migrated to the
  generic factory.

### Phase 10
- Off-site restic backup not configured (Gate B).
- UptimeRobot probe not configured (Gate B).
- Backup-script silent-failure alerting via systemd `failed` state
  only; Phase 12 readiness should add a "no log line in 26 h" probe.

### Phase 11
- Public Nginx vhost + Certbot + DNS not done (Gate B).
- Loopback-only TCP not unix socket — one-line swap when vhost goes live.
- Python 3.12 in `/opt/exam-python-3.12/` is operator-managed; no apt
  upgrade path.

### Phase 12
- 100+ NSE4 questions not imported — needs founder content.
- 5 beta users not yet onboarded — operator action.
- `/auth/register` open behind rate limit + loopback — gate before
  Gate B.
- Counsel-reviewed legal pages (Gate B).
- 1 k-user performance smoke (Gate B).

---

## 21. What the app can do now after Phase 12

- Public landing + catalog + search.
- Legal pages (Disclaimer, ToS, Privacy, DMCA) served from Markdown via
  the Phase 09 sanitiser.
- Auth: register (rate-limited 5/h/IP), login (rate-limited 5/min/IP +
  20/h/account), logout, `/me`.
- Admin: provider/course/exam/topic CRUD, audit log viewer, Excel
  import wizard (upload→map→preview→confirm), question CRUD with
  retire workflow, question-report triage queue.
- Student: practice + exam mode with shuffled `order_index`, autosave,
  flag, navigation, server-authoritative timer, idempotent submit.
- Scoring: set-equality per question, all-or-nothing multi-choice;
  result page + review per-question (selected vs correct, "you
  picked", explanation, file-a-report).
- Healthz + Readyz with alembic head check.
- Defense-in-depth: CSP / X-Frame / X-CTO / Referrer / Permissions
  headers, HSTS-in-prod, CSRF on every state-changing route, per-route
  rate limits, sanitised Markdown render, XLSX magic + size + ext
  validation.
- systemd-managed web service binding 127.0.0.1:8001 with
  least-privilege user + kernel-protect hardening; daily backup timer
  scheduled; manual DR drill executed and signed off.

---

## 22. Whether it is safe to plan post-MVP AI verification later

**Yes — safe to plan, not safe to start automatically.** The MVP
foundation is ready: per-question audit hooks (Phase 03), per-question
explanations field (Phase 06), question reports + admin triage queue
(Phase 08), confidence badge ("Unverified — admin-supplied"; Phase 12).
Post-MVP AI verification can be added without schema redesign by:

1. Adding a `verifications` table keyed on `(question_id, version)`.
2. Adding an evidence cache table.
3. Wiring an offline RQ worker that consumes the audit log of
   question edits and re-verifies asynchronously.
4. Updating the `Confidence` badge to reflect verifier output.

None of that should be auto-approved by an unattended run; the founder
should choose the AI provider, review costs, and approve the schema
change first.

---

## Summary one-liner

Phase 09 (security middleware + per-route rate limits + bleach
sanitiser + upload validator), Phase 10 (backup runbook + manual DR
drill on real PG + `/readyz` with alembic-head check), Phase 11
(loopback-only systemd unit on 127.0.0.1:8001 with kernel-level
hardening, no public exposure), and Phase 12 (legal pages +
readiness checklist + Fortinet NSE4 topic seed) are all complete on
local + LXC; **227 / 227** tests pass on real PG+Redis; blog stack
untouched; the dev uvicorn is stopped, the persistent systemd unit is
documented and intentionally left running per the brief; no post-MVP
phase started.
