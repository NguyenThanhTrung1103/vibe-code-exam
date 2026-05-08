# Project Changelog

Reverse-chronological log of significant changes. Updated after each
phase completion. Phase reports under `plans/reports/` are the
authoritative source for the phase-level narrative; this file is the
short-form digest.

## 2026-05-04 (later) — Dev wipe + 4-dump auto-reimport on LXC

**Status:** ✅ Re-imported all 4 sample dumps after a full wipe of the
dev DB on `exam-lxc` (`exam_platform_db`). Dashboard + import-validator
overflow detection deployed at the same time. See
`plans/reports/fullstack-260504-2222-clear-and-reimport-dumps.md`.

**Wipe** — single FK-safe transaction across `attempt_answers →
attempts → community_discussion_sources → question_options →
question_explanations → question_references → question_reports →
evidence_fetch_logs → ai_verification_jobs →
question_duplicate_groups → questions → import_items → imports`.
Pre-wipe 13 imports / 405 items / 261 questions / 57 CDS → 0 / 0 / 0 / 0.

**Reimport totals** — 259 questions across 4 imports (target exam=1
NSE 4 — FortiGate Security, draft):

| File | Format | Imported | Notes |
|---|---|---|---|
| `import_quiz_question_ccna_online.xlsx` | xlsx | 38/40 | 2 content-overflow rows (7 + 8 options exceed A–F schema) |
| `57q_efw.html` | examtopics_html | 57/57 | + 57 CDS (URL, votes, external_question_id) |
| `57q_efw(1).html` | examtopics_html | 0/57 | byte-identical copy → all 57 dedup'd by content_hash |
| `*.pdf` (qblock) | qblock_pdf | 164/166 | 2 dedup hits |

**Verification of edge cases**

- **xlsx errors** — content overflow, not validator regression. Rows 6
  (OSI 7 layers) and 9 (8 subnet masks, `correct_answer="7"`) genuinely
  have more options than the A–F (6-slot) schema allows. Old behavior
  silently truncated — new behavior surfaces an actionable error in
  `import_items.error_message`. Path forward: admin trims the source
  rows, or schema is extended A–H (separate decision).
- **HTML duplicate** — verified byte-identical via SHA-256 (`6454d0e…`),
  all 57 row-level `content_hash`es match within import 144. Dedup is
  doing the right thing; not too aggressive.
- **CDS** — 57/57 questions linked, with `source_url`,
  `external_question_id`, `discussion_count`, `total_votes`, and
  `vote_distribution` JSONB populated. `community_consensus=unknown` /
  `community_answer=NULL` is expected — those are computed by a later
  processing step, not the import.

**Deploy** — tar+scp of 16 files (dashboard router/template, _nav,
header.html, import normalizer/validator, exam/practice/import
routers, related templates) to `/srv/exam-platform`.
`systemctl restart exam-platform-web` → `active`. Tests on deployed
code: `test_admin_dashboard.py` + `test_import_unit.py` (53 tests, all
green).

**Healthz (final)** — `{"status":"ok","db":"ok","redis":"ok"}`. All 7
admin routes (dashboard, imports, exams, questions, filtered questions,
preview-with-error-filter, exam publish POST) reachable; unauth returns
303 → login as expected.

---

## 2026-05-04 — Admin dashboard, primary nav, import/exam UX

**Status:** Dashboard + navigation merged on `master` as `055c172`
(`feat(admin): add dashboard at /admin with primary nav and snapshots`).
Additional import/practice/template edits may exist **only in local
working trees** until committed — see `git status` / `summary.md` § 3a–3b.

**Highlights**

- **`GET /admin`** — Admin home with three action cards (Import dump,
  Manage exams, Review questions), import **alert** strip (errors /
  `failed_questions` in recent imports), **tabs** (Alpine) for compact
  **Recent imports** and **Exams & status** with publish / practice
  preview / public exam links where applicable.
- **Primary admin navigation** — `admin/_nav.html` rendered under the
  site header for any `/admin/*` path; top “Admin” link targets `/admin`.
- **Recent imports page (`/admin/imports`)** — wide table: catalog
  columns (provider, course, exam, slug), **exam** vs **import**
  status, staged **OK / Err / Dup**, highlighted errors, contextual
  actions (publish exam, practice preview, review, public link).
- **Import validation** — `combined_options` overflow beyond A–F
  surfaces an explicit error; clearer numeric `correct_answer`
  out-of-range messaging.
- **Admin practice preview** — `list_questions_for_admin_preview`,
  `start_admin_preview_attempt`, `POST .../practice-preview/start`;
  learners still use published exams only on the public catalog.
- **Attempts UX** — submit redirects to **result**; review template
  shows a fixed **missing explanation** sentence when appropriate.
- **Tests** — `tests/test_admin_dashboard.py` (unauthenticated
  dashboard → login redirect with `Accept: text/html`).

**Docs:** `summary.md` § 3a–3b, § 11, § 17 updated for handoff.

---

## 2026-05-02 — Multi-format admin import (Milestone 1)

**Status:** ✅ Shipped to LXC `192.168.99.97`. 294 / 294 hermetic tests
pass; 3 fixture smokes (XLSX, HTML, PDF) confirmed end-to-end on the
deployed instance with `258` questions, `1066` options, `164` explanations,
and `57` community sources created across imports 137 / 138 / 139 (all
private/draft under `exam_id=1`).

**Highlights**

- Multi-format upload — admin import accepts `.xlsx`, saved `.html`/`.htm`,
  `.pdf`, and `.txt` dumps. XLSX still walks the column-mapping wizard;
  HTML / PDF / TXT skip mapping (the parser-adapter emits canonical
  rows directly) and go straight to preview.
- Parser-adapter layer at `app/services/parsers/`:
  - `xlsx_adapter.py` — wraps the existing `excel_parser.stream_rows` so
    Vietnamese aliases + `combined_options` continue to work unchanged.
  - `examtopics_html_adapter.py` — saved ExamTopics pages. Pulls
    `correct_answer` + per-letter `vote_distribution` from the JSON
    payload inside `.voted-answers-tally script`; absolutizes relative
    `/discussions/...` URLs against the saved page's `<base href>`.
  - `qblock_pdf_adapter.py` + `qblock_text_adapter.py` — `QUESTION N`
    block style with `A./B./C./D.`, `Answer:`, `Explanation:`. PDF path
    delegates to the text parser via `pdfminer.six.high_level.extract_text`.
  - `detector.py` — picks the highest-priority adapter per file via
    extension + first-4-KB magic. The picked adapter's `name` is stored
    on `imports.detected_format` for UI display and downstream policies.
- `app/security/upload_validator.py` — `validate_upload_bytes(...)`
  returns the family (xlsx / html / pdf / txt). `validate_xlsx_bytes`
  kept for legacy callers.
- `app/services/import_validator.py` — multi-letter answer support:
  contiguous A–F runs (`BD`, `ACE`, …) expand to per-letter resolution.
  Lifts 17 PDF rows from `error` → `ok`.
- New columns:
  - `imports.title` (`varchar(255) NULL`) — admin label, falls back to
    file_name in UI.
  - `imports.detected_format` (`varchar(32) NULL`) — adapter name.
  - `attempts.user_id` made nullable; `attempts.guest_token`
    (`varchar(64) NULL`); `ck_attempts_owner` CHECK; partial index
    `ix_attempts_guest_token`. (Schema landed for Milestone 2 guest
    practice; HTTP layer dormant.)
- Login page now respects `?next=…` post-login; admin pages return a
  303 redirect to `/auth/login?next=<path>` for unauthenticated browser
  navigation (Accept: text/html), instead of a bare 401 JSON.
- Admin "Recent imports" table now shows the detected_format chip.
- `app/auth/guest.py` ships dormant — present in code but no router
  imports it; deferred until Milestone 2.

**Migrations added**

- `0007_c2d3e4f5a6b7_imports_add_title.py`
- `0008_d3e4f5a6b7c8_attempts_guest_token.py`
- `0009_e4f5a6b7c8d9_imports_detected_format.py`

**Tests added**

- `tests/services/test_parser_adapters.py` — adapter contract + golden
  fixture coverage for XLSX (Vietnamese CCNA), HTML (57q ExamTopics),
  PDF (166q PassLeader).
- `tests/test_import_unit.py` — VN combined_options regression +
  zero-staged-rows confirm guard.

**Tests run** — `uv run pytest`: 294 passed / 98 skipped (real-DB gate)
/ 0 failed.

**Deployment** — see `docs/reports/changelog-local.md` for the dated
deploy log (DB backup, alembic before/after, schema verification,
healthcheck). Instance restarted only `exam-platform-web.service`.

**Operator runbook** — `docs/ops/exam-platform-import-runbook.md`.
**Implementation report** — `docs/reports/exam-platform-multiformat-import-implementation.md`.
**Browser QA URLs** — `docs/reports/exam-platform-multiformat-qa-urls.md`.

**Process note** — engineering mistake captured as a permanent rule:
the agent guessed raw `ssh user@host` against `192.168.99.97` instead of
resolving the configured `exam-lxc` alias, and prematurely concluded
"deploy blocked". Documented at `.claude/skills/ssh/SKILL.md` so future
runs check `ssh -G <alias>` first.

## 2026-04-30 — Phase 12 — Beta launch readiness (Gate-A scaffolding)

**Status:** ✅ Complete (Gate-A scaffolding scope; live content seed and
public soft-launch are operator actions). LXC verified, 227 / 227
tests pass on real PG+Redis. End-to-end public + auth-gated surface
served by systemd unit on 127.0.0.1:8001.

**Highlights**
- Legal pages live and rendered through the Phase 09 sanitiser:
  - `docs/disclaimer.md`, `terms-of-service.md`, `privacy-policy.md`,
    `dmca-takedown.md` (sourced as Markdown; bleach allow-list applied).
  - New router `app/routers/public/legal.py` mounts them at
    `/legal/{disclaimer,terms,privacy,dmca}`.
  - `app/templates/public/legal.html` + footer rewrite
    (`app/templates/_layout/footer.html`) — every page now links the
    four legal pages.
- Topic taxonomy seed: `content/topics-seed.sql`. Idempotent
  `INSERT … ON CONFLICT (exam_id, slug) DO UPDATE` for the eight
  Fortinet NSE4 categories. Refuses to seed when no NSE4 exam exists
  or when multiple match.
- Readiness checklist: `docs/readiness-checklist.md` — Gate A items
  ticked; Gate B items list what blocks public soft-launch.
- Beta feedback log: `docs/beta-feedback-log.md` — empty table for
  the operator to fill during the beta cycle.
- Auth/register risk note (in the readiness checklist) — open
  registration is rate-limited to 5/h/IP and not publicly reachable
  while the app is loopback-only; gating it is a Gate-B prereq.
- `app/main.py` registers the `legal` router; `tests/test_legal_pages.py`
  covers the four pages plus the footer wiring.
- No subagents spawned.

**Tests added**
- `tests/test_legal_pages.py` (7 hermetic tests).

**Files**
- Added: `docs/{disclaimer,terms-of-service,privacy-policy,
  dmca-takedown,beta-feedback-log,readiness-checklist}.md`,
  `content/topics-seed.sql`, `app/routers/public/legal.py`,
  `app/templates/public/legal.html`, `tests/test_legal_pages.py`.
- Modified: `app/main.py` (router registration), `app/templates/_layout/footer.html`
  (legal links), docs.

**LXC verification**
- `ruff check / format / mypy`: ✅ all clean (81 source files, 110
  formatted).
- Hermetic `pytest` (LXC): ✅ 145 / 145.
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest` (LXC): ✅ **227 / 227**.
- Final E2E surface (against the systemd-managed app on
  127.0.0.1:8001):
  - `GET /` 200; `GET /legal/{disclaimer,terms,privacy,dmca}` 200;
    `GET /search/exams?q=test` 200; `GET /healthz` 200; `GET /readyz`
    200 (alembic head match); `GET /auth/login` 200; `GET /auth/register`
    200.
  - Anon mutations / admin views: `POST /attempts/start`,
    `POST /admin/imports`, `POST /questions/1/reports`,
    `GET /admin/providers`, `GET /admin/question-reports`,
    `GET /attempts/1/result`, `GET /attempts/1/review` → all 401
    (RBAC enforced).
  - All Phase 09 security headers present on legal pages.
- Blog co-tenancy: 5/5 services active, blog SHA256 unchanged,
  `curl http://127.0.0.1:8000/` → 301 (blog gunicorn unaffected).

**Phase 12 deviations from plan (Gate-B items deferred)**
- 100+ NSE4 questions imported — no first-party content source; topic
  seed is in place, but the actual question import is an operator
  action documented in `docs/readiness-checklist.md`.
- 5 beta users completed full attempts — operator action.
- Off-site restic backup — Phase 10 Gate B; documented.
- Public Nginx vhost + TLS + DNS — Phase 11/12 Gate B; templates
  shipped.
- 1 k seeded user performance smoke — Gate B prereq.

## 2026-04-30 — Phase 11 — LXC deployment (loopback-only)

**Status:** ✅ Complete (loopback scope; public Nginx + TLS gated to
Phase 12 readiness checklist per the brief). LXC verified: systemd
unit running, 220 / 220 tests pass on real PG+Redis, blog stack
untouched.

**Highlights**
- Production layout under `/srv/exam-platform/`:
  - `exam-platform` system user (uid 999, no shell, home dir owned).
  - `app/`, `migrations/`, `ops/`, `uploads/`, `logs/` — owner
    `exam-platform:exam-platform`.
  - `.venv/` — CPython 3.12.13 (relocated from uv's per-user cache to
    `/opt/exam-python-3.12/` so the systemd unit can exec it).
  - `.env` with mode `640 root:exam-platform`.
- systemd units installed in `/etc/systemd/system/`:
  - `exam-platform-web.service` — uvicorn workers=2 binding **127.0.0.1:8001**
    (loopback only). Hardened: `NoNewPrivileges`, `ProtectSystem=strict`,
    `ProtectHome=yes`, `PrivateTmp=yes`, kernel-protection set, RW path
    limited to uploads + logs.
  - `exam-pg-backup.service` + `.timer` (Phase 10 unit, install moved
    here per plan). Scheduled 02:30 UTC daily.
- Operator scripts under `ops/deploy/`:
  - `install.sh` — one-time bootstrap (idempotent).
  - `deploy.sh` — rsync-based code refresh, venv update, alembic
    upgrade, smoke probes, Sentry release stamp.
  - `rollback.sh` — revert to a known-good source tree, restart unit.
- **NOT installed** (per the brief): Nginx public vhost, certbot TLS,
  UFW changes, cloudflared changes. Templates live at
  `ops/nginx/exam-platform.conf` and `ops/logrotate/exam-platform`
  with installation gated on Phase 12 readiness.

**Files**
- Added: `ops/systemd/exam-platform-web.service`,
  `ops/deploy/{install,deploy,rollback}.sh`,
  `ops/nginx/exam-platform.conf` (template, not installed),
  `ops/logrotate/exam-platform` (template, not installed),
  `ops/docs/deployment-runbook.md`.
- Modified: `docs/project-roadmap.md`, `project-changelog.md`,
  `system-architecture.md`.
- LXC-only changes (NOT in repo): `/etc/systemd/system/exam-*.{service,timer}`,
  `/srv/exam-platform/{.venv,.env,app,migrations,ops}`,
  `/opt/exam-python-3.12/`.

**Decision rationale**
- *Loopback-only at MVP* — the user brief explicitly defers public
  exposure (Nginx vhost, TLS, DNS) until Phase 12 readiness gates pass.
  Loopback satisfies "blog cohabitation without disruption" trivially
  and avoids any blog-Nginx regression risk.
- *systemd unit binds 127.0.0.1:8001 directly (not unix socket)* — the
  plan's unix-socket+Nginx topology is documented in the vhost
  template; loopback TCP is simpler when there's no proxy in front.
  Phase 12 swap-in is one-line: change `--host` to a unix socket and
  enable the vhost.
- *Python 3.12 relocated to `/opt/exam-python-3.12/`* — uv stores its
  managed Python under `/root/.local/share/uv/`, which `exam-platform`
  cannot exec. Copying (dereferenced) to `/opt` is least-invasive; no
  apt PPA / system Python upgrade needed.
- *No subagents spawned* — context budget preserved.

**Tests added**
- None new in Phase 11; the existing 220 tests are the deployment
  smoke surface. Phase 11 verifies "the same code that's under test
  starts cleanly under systemd as a non-root user".

**LXC verification**
- `ruff check / format / mypy`: ✅ all clean.
- Hermetic `pytest`: ✅ 138 / 138 (LXC).
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest`: ✅ **220 / 220**.
- `systemctl is-active exam-platform-web.service` → `active`.
- `systemctl is-active exam-pg-backup.timer` → `active` (next fire
  2026-05-01 02:30 UTC).
- `systemctl restart exam-platform-web.service` → graceful, `/healthz`
  back to 200 within ~3 s.
- `curl http://127.0.0.1:8001/healthz` → 200 with all Phase 09 headers.
- `curl http://127.0.0.1:8001/readyz` → 200 with alembic head match
  (`a1b2c3d4e5f6`).
- Blog co-tenancy:
  - `curl http://127.0.0.1:8000/` → 301 (blog gunicorn unaffected).
  - 5/5 services active: postgresql, redis-server, nginx,
    cloudflared, blog.service.
  - Blog SHA256 unchanged (pg_hba, postgresql.conf, redis.conf).

## 2026-04-30 — Phase 10 — Backup, observability, DR drill

**Status:** ✅ Complete (Gate-A internal-beta scope; Gate-B off-site
restic deferred. LXC verified, 220 tests pass on real PG+Redis. DR
drill executed and signed off in `ops/docs/dr-drill-log.md`.)

**Highlights**
- New ops scaffolding under `ops/`:
  - `ops/backup/pg-backup.sh` — `pg_dump --format=custom --no-owner
    --no-privileges` of `exam_platform_db` to `/var/backups/postgres/`,
    with optional restic upload + retention (`--keep-daily 7 --keep-weekly 4
    --keep-monthly 6`). Refuses to operate on any DB other than
    `exam_platform_db*`.
  - `ops/backup/uploads-backup.sh` — restic snapshot of
    `/srv/exam-platform/uploads/`. No-op when `RESTIC_REPO` is unset.
  - `ops/backup/restic-restore.sh` — DR restore helper. Refuses to
    target the live DB or `blogdb`. Pre-existence of the drill DB is
    checked because `exam_platform_user` lacks `CREATEDB` (intentional
    least-privilege).
  - `ops/systemd/exam-pg-backup.{service,timer}` — daily 02:30 UTC
    timer. **Files only — Phase 11 installs them.**
  - `ops/docs/{backup-runbook,restore-runbook,dr-drill-log,observability}.md`.
- App changes:
  - `app/routers/health.py` — adds `/readyz` returning 200 only when
    DB + Redis up **and** alembic current revision matches the head.
  - `app/main.py` — Sentry `release` plumbed from `SENTRY_RELEASE` /
    `APP_RELEASE` env. No-op when DSN absent.

**Decision rationale**
- *Internal-beta gate vs. public-launch gate* — Phase 10 ships the
  internal-beta scope: documented runbook, executed manual drill,
  `/healthz` + `/readyz`. Off-site restic + UptimeRobot are deferred
  to Phase 12 readiness checklist.
- *`exam_platform_user` keeps `CREATEDB=false`* — operator pre-creates
  the drill DB with the postgres superuser. App can never spawn a DB.
- *`/readyz` distinct from `/healthz`* — uptime probes hammer
  `/healthz`; deploy/readiness gates hit `/readyz` once after rollout.
  Migration-head check belongs to readiness only.
- *Structlog already JSON-in-prod* — Phase 02 wiring stands; Phase 10
  documents the contract in `ops/docs/observability.md`.
- *No subagents spawned* — context budget preserved.

**Tests added**
- `tests/test_health_routes.py` (6 hermetic tests covering `/healthz`
  ok / degraded and `/readyz` ok / db-down / migration-behind /
  migration-unknown).

**Files**
- Added: `ops/backup/{pg-backup,uploads-backup,restic-restore}.sh`,
  `ops/systemd/exam-pg-backup.{service,timer}`,
  `ops/docs/{backup-runbook,restore-runbook,dr-drill-log,observability}.md`,
  `tests/test_health_routes.py`.
- Modified: `app/routers/health.py` (+ /readyz), `app/main.py`
  (Sentry release env), docs.

**LXC verification**
- `ruff check / format / mypy`: ✅ all clean (80 source files, 108
  formatted).
- Hermetic `pytest`: ✅ 138 / 138.
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest`: ✅ **220 / 220**.
- DR drill (recorded in `ops/docs/dr-drill-log.md`):
  - `pg_dump` produced `exam_2026-04-30T12-51-42Z.dump` (116 KiB).
  - `pg_restore` into `exam_platform_db_drill` succeeded.
  - Smoke counts: `users=3`, `exams=4`, `questions=3`,
    `alembic_version=1`. Head: `a1b2c3d4e5f6`.
  - Drill DB dropped post-verification.
  - Wall-clock RTO < 5 min (target ≤ 30 min).
- Uvicorn smoke on `127.0.0.1:8001`:
  - `/healthz` 200 `{"status":"ok","db":"ok","redis":"ok"}`.
  - `/readyz` 200 `{..., "migrations":{"status":"ok",
    "current":"a1b2c3d4e5f6", "head":"a1b2c3d4e5f6"}}`.
  - All Phase 09 security headers still present.
- Blog stack SHA256 + 5/5 services unchanged. Uvicorn stopped cleanly.

## 2026-04-30 — Phase 09 — Security hardening & rate limiting

**Status:** ✅ Complete (LXC verified, 214 tests pass on real PG+Redis).

**Highlights**
- New `app/security/` package:
  - `headers.py` — `SecurityHeadersMiddleware` adds CSP, X-Frame-Options
    DENY, X-Content-Type-Options nosniff, Referrer-Policy, minimal
    Permissions-Policy on every response. HSTS gated on `is_production`.
  - `sanitize.py` — `render_markdown()` (markdown-it `html=False` →
    bleach allow-list → linkify with `rel="noopener noreferrer nofollow"`).
    Registered as Jinja `render_md` filter.
  - `upload_validator.py` — `validate_xlsx_bytes()` enforces ext + magic
    (`PK\x03\x04`) + size cap; replaces inline checks in `import_service`.
  - `rate_limits.py` — generic `RateLimit(name, limit, window_s, scope)`
    Redis-sliding-window dependency factory. Pre-built instances cover
    register, attempt-start, attempt-answer, question-report,
    admin-import, public-search, public-landing per the plan table.
    Fails closed (503) on Redis outage; emits `Retry-After` on 429.
  - `error_handler.py` — production-safe handler swallowing tracebacks
    in `prod`/`staging`; HTTPException + RequestValidationError pass-
    through unchanged.
  - `proxy.py` — installs `ProxyHeadersMiddleware(trusted_hosts=127.0.0.1)`
    only in non-`local`/`test` env so `Secure` cookies + IP-based rate
    limits remain correct behind Phase 11's Nginx.

**Routes wired with rate-limit dependency**
- `POST /auth/register`, `POST /attempts/start`,
  `POST /attempts/{id}/q/{n}/answer`, `POST /questions/{id}/reports`,
  `POST /admin/imports`, `GET /search/exams`, `GET /` (landing).
- `POST /auth/login` keeps the Phase 03 dual-scope IP+identifier limit.

**Decision rationale**
- *MVP `'unsafe-inline'` CSP* — HTMX/Alpine inline events are essential
  Phase 1 ergonomics. Defense-in-depth via bleach + tests; nonce CSP is
  Phase 2.
- *Bleach + markdown-it `html=False`* — escape-then-strip pipeline. Raw
  `<script>` becomes safe text; templates can opt in via
  `{{ x | render_md | safe }}` when admin-authored Markdown is wanted.
- *RateLimit dependency factory* — keep Phase 03's bespoke login limiter
  intact, but add a generic version for everything else. One pattern,
  per-route limits, Redis-backed.
- *Fail-closed on Redis outage* — refusing requests is better than
  silently disabling rate limiting.
- *No subagents spawned* — context budget preserved; consistent with
  P05–P08.

**Tests added**
- `tests/security/test_headers.py` (4)
- `tests/security/test_sanitize.py` (10)
- `tests/security/test_upload_validator.py` (8)
- `tests/security/test_rate_limits.py` (5)
- `tests/security/test_csrf_coverage.py` (8)
- `tests/security/test_xss_regressions.py` (13)

Real-DB conftest fixtures broadened: `rl:login_*` → `rl:*` so all
Phase 09 limit keys are flushed between tests.

**Files**
- Added: `app/security/{__init__,headers,sanitize,upload_validator,rate_limits,error_handler,proxy}.py`,
  `tests/security/*.py`, `docs/security-baseline.md`.
- Modified: `app/main.py` (middleware wiring + `render_md` filter),
  `app/services/import_service.py` (delegate to `validate_xlsx_bytes`),
  `app/routers/auth.py`, `practice.py`, `reports.py`,
  `admin/imports.py`, `public/home.py`, `public/search.py`
  (rate-limit deps), `tests/conftest.py` (FakeRedis pipeline support),
  `tests/test_*_real_db.py` (broadened rate-limit flush).

**LXC verification**
- `ruff check app tests migrations`: ✅
- `ruff format --check app tests migrations`: ✅
- `mypy app`: ✅ 80 source files, no issues
- Hermetic `pytest`: ✅ 132 / 132 (Windows) and 132 / 132 (LXC)
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest`: ✅ 214 / 214
- `uvicorn app.main:app --host 127.0.0.1 --port 8001` smoke:
  - `/healthz` 200 `{"status":"ok","db":"ok","redis":"ok"}`.
  - All security headers present on `/` and `/healthz`.
  - Anon `POST /attempts/start`, `/admin/imports`, `/questions/1/reports`
    → 401.
- Blog stack SHA256 (`pg_hba.conf`, `postgresql.conf`, `redis.conf`)
  unchanged; 5/5 services active. Uvicorn stopped cleanly.

## 2026-04-29 — Phase 08 — Scoring + result/review

**Status:** ✅ Complete (LXC verified, 166 tests pass on real PG+Redis).

**Highlights**
- New `app/services/scoring_service.py`:
  - `compute_attempt_score` — set-equality per question (all-or-nothing
    multi-choice); persists `correct_count`, `wrong_count`,
    `score_percent`, `passed`, `is_correct` per `attempt_answer`.
  - `topic_breakdown` — aggregates by `topic_id`; questions without a
    topic roll into "Untagged".
  - `weak_topic_recommendations` — top-2 topics with ≥3 questions
    AND ≥10 pp below overall score.
- `attempt_service.submit_attempt` (Phase 07) now hooks into scoring
  in the **same transaction**. Idempotent — exits early if
  `finished_at` is already set.
- New routes:
  - `GET /attempts/{id}/result`
  - `GET /attempts/{id}/review` (filter chips: all / wrong / flagged)
  - `GET /attempts/{id}/review/q/{order}`
  - `POST /questions/{id}/reports`
  - `GET /admin/question-reports`
  - `POST /admin/question-reports/{id}/{resolve,reject}`
- 5 new audit events: `attempt.scored`,
  `question_report.{filed,resolved,rejected}`.
- "Confidence" badge wording: **"Unverified (admin-supplied)"** —
  honest expectation-setting per Phase 1 plan.
- All review/report screens enforce
  `attempt.user_id == current_user.id`. Anon → 401; cross-user → 403.

**Decision rationale**
- *All-or-nothing multi-choice* (plan §35 #6 default).
- *Set-based scoring* — two queries, in-Python aggregation; pure / testable.
- *Untagged bucket* — surfaces topic-tagging gaps honestly.
- *Single audit row per scoring run* — replays compute the same result.
- *Admin queue ships in this phase* — student POST without admin
  triage is half-shipped.
- *No AI tutor / evidence cache* — out of Phase 1 scope.

**Files added**
- `app/services/scoring_service.py`
- `app/schemas/report.py`
- `app/routers/attempts.py`, `app/routers/reports.py`,
  `app/routers/admin/question_reports.py`
- `app/templates/attempts/{result,review_list,review_question}.html`
- `app/templates/reports/_filed.html`
- `app/templates/admin/question_reports/{list,_row}.html`
- `tests/test_scoring_unit.py` (7 hermetic)
- `tests/test_scoring_real_db.py` (13 real-DB, gated)
- `plans/reports/phase-08-...-completion.md`

**Files modified**
- `app/main.py` — register attempts, reports, admin
  question_reports routers.
- `app/services/attempt_service.py` — `_submit_idempotent` now calls
  `scoring_service.compute_attempt_score` in the same transaction.

**Quality gates (LXC)**
- `ruff check / format --check` — clean.
- `mypy app` — 73 source files, no issues.
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` — 166 tests pass.

**LXC verification**
- No new migration. Phase 02 schema covers `attempts`,
  `attempt_answers`, `question_reports`.
- Smoke: `/healthz` 200; anon → 401 on every Phase 08 route.
- All 5 core services active; PG/Redis SHAs unchanged.

## 2026-04-29 — Phase 07 — Practice & exam mode

**Status:** ✅ Complete (LXC verified, 146 tests pass on real PG+Redis).

**Highlights**
- Two attempt modes: `practice` (optional inline reveal) and `exam`
  (server-authoritative timer + soft warning + auto-submit on expiry).
- New routes at `/attempts/...`:
  `POST /attempts/start`, `GET /attempts/{id}/q/{order}`,
  `POST /attempts/{id}/q/{order}/answer`,
  `POST /attempts/{id}/q/{order}/flag`,
  `GET /attempts/{id}/submit-confirm`,
  `POST /attempts/{id}/submit`,
  `GET /attempts/{id}/submitted` (Phase 08 replaces the stub).
- `attempt_service.start_attempt(...)` snapshots
  publishable questions, shuffles once, persists `order_index` 1..N
  on pre-created `attempt_answers` rows. Frozen for the lifetime of
  the attempt — admin retirements/edits do NOT mutate the snapshot.
- Resume-in-progress: a second `start` for the same (user, exam)
  returns the existing in-progress attempt instead of a duplicate.
- Selected labels are normalised via
  `_parse_selected_labels` — sorted, unique, upper-case — and
  validated against the question's actual option labels before save.
  Server stores `"A"` for single-choice, `"A,C"` (sorted) for multi.
- Server-authoritative timer: client clock cannot grant extra time;
  every render computes `started_at + time_limit - now()`, expiry
  forces an idempotent submit and redirects to `/submitted`.
- 4 new audit events: `attempt.started`, `attempt.resumed`,
  `attempt.submitted`, `attempt.expired`. Per-answer auto-saves
  intentionally NOT audited (would balloon `audit_logs` ~50× per attempt).
- HTMX auto-save with `change delay:500ms` debounce; flag toggle
  swaps a single-button partial.
- Public `/exams/{provider}/{exam}` page now issues a CSRF token
  and renders Practice / Exam start buttons (anonymous users see a
  "Log in" link instead).

**Decision rationale (key picks)**
- *Pre-create N attempt_answers at start* — `order_index` is
  immutable + jump-to grid renders with one query.
- *Server-authoritative timer* — DevTools-proof, deadline = wall-clock.
- *Resume in-progress* on re-`start` — KISS; idle cleanup is Phase 10.
- *Free navigation in exam mode* — matches real cert exams (PRD §35).
- *No audit row per auto-save* — answers themselves persist on
  `attempt_answers`; audit table stays proportional.
- *Submit endpoint is minimal* — Phase 08 adds scoring on top.

**Files added**
- `app/services/attempt_service.py`
- `app/services/question_selector.py`
- `app/schemas/attempt.py`
- `app/routers/practice.py`
- `app/templates/practice/{question,_timer,_flag_button,_nav_grid,submit_confirm,submitted_stub}.html`
- `tests/test_attempt_unit.py` (10 hermetic)
- `tests/test_practice_real_db.py` (15 real-DB, gated)
- `plans/reports/phase-07-...-completion.md`

**Files modified**
- `app/main.py` — register `practice` router.
- `app/audit/events.py` — Phase 07 + 08 audit constants.
- `app/routers/public/exams.py` — issue CSRF token for the Start CTA.
- `app/templates/public/exam_detail.html` — wire Start Practice / Start Exam.

**Quality gates (LXC)**
- `ruff check / format --check` — clean.
- `mypy app` — 68 source files, no issues.
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` — 146 tests pass.

**LXC verification**
- No new migration. Phase 02 schema covers `attempts`/`attempt_answers`.
- Smoke: `/healthz` 200, anon `/attempts/start` POST 401,
  `/attempts/1/q/1` GET 401. All 5 core services active; PG/Redis
  config SHAs unchanged.

## 2026-04-29 — Phase 06 — Question bank CRUD

**Status:** ✅ Complete (LXC verified, 117 tests pass).

**Highlights**
- New admin module at `/admin/questions` covering list, search, full-page
  editor, and bulk topic assignment.
- Service `app/services/question_service.py` mirrors the catalog write-
  funnel: every mutation calls `write_audit_log()` in the same SA
  session as the SQL change.
- 7 new audit actions: `question.created`, `question.text_edited`,
  `question.option_edited`, `question.explanation_edited`,
  `question.retired`, `question.restored`, `question.topic_assigned`.
- Validation: at least 2 / at most 5 options; consecutive labels
  starting at A; correct labels must reference existing options;
  single-choice → exactly 1 correct; multiple-choice → ≥2 correct;
  empty `question_text` rejected; topic must belong to same exam.
- Soft retire via `Question.retired_at` + `status=retired`. Restore
  flips back to `verified_low` (manual edits earn no automatic high
  confidence).
- Editing recomputes `content_hash` using the SAME canonical recipe as
  Phase 05 dedup — `sha256(normalized_q + "|" + sorted_normalized_opts)`.
- HTMX wizard pattern reused: list page filter form, edit page
  multi-section form (text/type/topic/difficulty/status, then options
  + correct answer, then explanation, then retire/restore).
- Imported questions from Phase 05 (status=imported) are editable via
  the same Phase 06 routes — covered by
  `test_imported_question_can_be_edited`.

**Decision rationale (key picks)**
- *Module-level service functions* (no class) — matches Phases 04 / 05
  pattern; keeps testing flat and avoids ORM-style "service object"
  lifecycle.
- *Full-page editor, not inline-row HTMX swap* — easier to reason about,
  simpler templates, and questions are content-heavy (4 KB text + 5
  options + explanation) so a full re-render is a wash UX-wise.
- *Wipe-and-reinsert for option set* — option count is tiny (≤5), the
  diff logic is more code than the wipe. The audit row records both
  old and new option arrays so history is recoverable.
- *`retire` instead of hard-delete* — preserves attempts/review history
  while hiding the question from new attempts. Plan §Key Insights
  explicitly called this out.
- *Topic must belong to same exam* — bulk-assign + single-edit both
  enforce this at the service layer; UI also filters dropdown by exam.
- *Manual edits → `status=verified_low`* — admin attests they reviewed
  it but the AI verifier (Phase 2) hasn't certified the new content,
  so `verified_high` would be misleading.

**Files added**
- `app/services/question_service.py`
- `app/schemas/question.py`
- `app/routers/admin/questions.py`
- `app/templates/admin/questions/{list,new,edit,_bulk_result}.html`
- `tests/test_question_schemas_unit.py` (15 hermetic tests)
- `tests/test_question_real_db.py` (14 real-DB tests, gated)
- `plans/reports/phase-06-260429-2300-completion.md`

**Files modified**
- `app/main.py` — register `/admin/questions` router.
- `app/audit/events.py` — Phase 06 audit constants (already added in
  Phase 05's audit.events bump).

**Quality gates (LXC)**
- `ruff check / format --check` — clean.
- `mypy app` — 64 source files, no issues.
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` — 117 tests pass.

**LXC verification**
- Boot, `/healthz` 200 (db ok / redis ok), anon 401 on every
  `/admin/questions*` route, missing CSRF returns 403.
- Blog stack untouched: 5/5 services active, config SHAs unchanged.

## 2026-04-29 — Phase 05 — Excel import pipeline

**Status:** ✅ Complete (LXC verified, 88 tests pass).

**Highlights**
- New admin wizard at `/admin/imports` (4 steps: upload → mapping →
  preview → done).
- Streaming openpyxl parser (`read_only=True, data_only=True`); 25 MB
  / 5 000-row caps; 32-column safety bound.
- Per-cell normalization: HTML strip via `bleach`, NFKC, zero-width /
  RTL char removal, whitespace collapse.
- Per-row validation: required fields, length caps, option labels,
  difficulty enum, question type inference from `correct_answer`.
- Exact-duplicate detection with SHA-256 of
  `normalized_question + "|" + "||".join(sorted_options)`. Within-import
  AND cross-exam (against existing `questions.content_hash` for the
  same exam).
- Idempotent confirm step: only items with `status='ok' AND question_id
  IS NULL` get inserted; per-item `begin_nested()` savepoint isolates
  partial failures.
- Imported questions are private/draft (`Question.status='imported'`,
  `confidence_level=unknown`); admin must publish the parent exam
  manually.
- `source_locator` JSONB populated on every imported question with
  `{import_id, import_item_id, file_name, sheet_name, row_number}`.
- Uploaded XLSX files saved to `settings.uploads_dir/imports/{id}.xlsx`
  (mode 600, never exposed via static or any public route).
- Filenames sanitised — path-traversal segments stripped before storage.
- 11 catalog audit events added (`import.uploaded`,
  `import.mapping_saved`, `import.parsed`, `import.row_toggled`,
  `import.confirmed`, `import.partial_failure`, `question.imported`).
- Migration `0005_a1b2c3d4e5f6_imports_target_mapping_filepath` adds
  `imports.target_exam_id`, `column_mapping JSONB`, `file_path`. Round-
  trip verified on LXC.

**Decision rationale (key picks)**
- *DB-backed staging* (one `import_items` row per Excel row from
  the moment of parse) — 1 000-row imports survive browser close /
  server restart / admin returning later. No in-memory list.
- *Synchronous parse + stage* — 5 000 rows from openpyxl finishes in
  <10 s; deferring to RQ adds queue / failure surface we don't need
  yet.
- *bleach with empty allowlist* + NFKC + zero-width strip — the
  three-step normalization catches HTML script tags, lookalike Unicode,
  and bidi-spoofing in one pass.
- *Per-item savepoint inside one big transaction* — partial-failure
  tolerance without leaking half-state. The plan spec'd `SAVEPOINT`;
  SQLAlchemy `session.begin_nested()` issues exactly that.
- *content_hash on options sorted by text*, not by label — the same
  question with re-shuffled answer choices still hashes equal, which
  matches Phase 06's editor where admin can swap option order.
- *Imported as `private/draft`* — never auto-publish. Admin must
  publish the exam manually after Phase 06 review.

**Files added**
- `app/services/{excel_parser,import_normalizer,import_validator,import_dedup,import_service}.py`
- `app/schemas/import_form.py`
- `app/routers/admin/imports.py`
- `app/templates/admin/imports/{upload,mapping,preview,done,_row}.html`
- `migrations/versions/0005_a1b2c3d4e5f6_imports_target_mapping_filepath.py`
- `tests/test_import_unit.py` (16 hermetic tests)
- `tests/test_import_real_db.py` (9 real-DB tests, gated)
- `plans/reports/phase-05-260429-2230-completion.md`

**Files modified**
- `app/main.py` — register imports router.
- `app/audit/events.py` — Phase 05 + 06 audit constants (11 + 7).
- `app/models/imports.py` — new columns: `target_exam_id`,
  `column_mapping`, `file_path`.
- `app/config.py` — `uploads_dir`, `import_max_bytes`,
  `import_max_rows`.

**Quality gates (LXC)**
- `ruff check / format --check` — clean.
- `mypy app` — 61 source files, no issues (one `# type: ignore[import-untyped]`
  on `bleach`).
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` — 88 tests pass.

**LXC verification**
- `alembic upgrade head` applied 0005 cleanly; downgrade/upgrade
  round-trip green.
- `/healthz`, `/`, `/admin/imports` (anon → 401), POST without CSRF
  (→ 401, since auth runs before CSRF), all behaved as expected.
- Blog safety: `blog.service`, `postgresql`, `redis-server`, `nginx`,
  `cloudflared` all active; PG/Redis config SHAs unchanged.

## 2026-04-29 — Phase 04 — Catalog management

**Status:** ✅ Complete.

**Highlights**
- Admin CRUD for `Provider`, `ProductVersion`, `Course`, `Exam`, `Topic`,
  funnelled through `app/services/catalog_service.py`. Every mutation
  writes an `audit_logs` row in the same SQLAlchemy transaction.
- New routes:
  - Admin: `/admin/{providers,product-versions,courses,exams,topics}`
    (HTMX form patterns, CSRF + `RequireAdmin`).
  - Public: `/`, `/vendors`, `/vendors/{slug}`, `/exams/{provider}/{exam}`,
    `/search/exams?q=…`.
- Per-parent slug uniqueness via migration
  `0004_2c8e9a1b3d4f_catalog_per_parent_slug_uniqueness`:
  - `courses` `UNIQUE(provider_id, slug)`
  - `exams` `UNIQUE(course_id, slug)`
  - `topics` `UNIQUE(exam_id, slug)`
  - `product_versions` `UNIQUE(provider_id, product_name, product_version)`
- Slug helper: `app/utils/slug.py` — `python-slugify` wrapper, regex
  `^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$`, max 64 chars.
- Public visibility rule encoded in `app/routers/public/catalog_query.py`:
  `Exam.publish_status='published'` AND `Exam.deleted_at IS NULL` —
  applied explicitly on every public read.
- Friendly duplicate-slug errors via `DuplicateSlugError`, mapped to
  HTTP 400 with the offending slug in the message — never a raw
  `IntegrityError` to the user.
- Search: ILIKE on `provider.name`, `exam.code`, `exam.name`. Limit 20.
  No full-text/cache/ranking yet.
- Exam can be published with zero questions; the public detail page
  shows a "Coming soon — No questions available yet" badge and hides
  the "Start Practice" CTA.
- 11 catalog `AuditAction` values added (`provider.created`,
  `exam.published`, …).
- Tests: 13 hermetic Pydantic-schema unit tests + 26 real-DB tests
  (gated by `EXAM_PLATFORM_TEST_REAL_DB=1`) covering CRUD, audit,
  duplicates, soft-delete, publish/unpublish, public visibility, search,
  RBAC, CSRF.

**Decision rationale (key picks)**
- *Per-parent slug uniqueness* (not global) — vendors reuse generic
  course names ("CCNA", "Associate"); a global registry would force
  vendor prefixes everywhere. Reasoned in
  `docs/system-architecture.md` and the phase plan.
- *Function-based `catalog_service`* — service is a flat module of
  `create_*` / `update_*` / `soft_delete_*` functions. Testable, no
  hidden state, no ORM-style "service object" lifecycle.
- *HTMX partials* — list pages contain create form + row table; create
  POST returns the new row partial appended via `hx-swap="beforeend"`.
  No SPA tooling, no JSON layer.
- *Slug stability on rename* — name change does **not** auto-update
  the slug. URL stability matters; admin must explicitly edit the slug
  to change it.
- *No caching layer* — public reads are already simple SELECTs against
  small tables (~hundreds of rows). Add cache only if perf forces it.
- *ILIKE search* (no FTS) — Phase 04 has no perf complaint to justify
  full-text setup; ILIKE on indexed name/code columns is adequate.
- *Soft-delete only on Exam* — Provider/Course/Topic refuse delete with
  active children; only `Exam` carries `deleted_at`. Querying joins
  filter `Exam.deleted_at IS NULL` *explicitly*, never via global
  SQLAlchemy event hooks (those tend to surprise readers).
- *Publish-with-zero-questions allowed* — admins must be able to stage
  a published shell and import questions later (Phase 05 lands the
  importer). The "Coming soon" badge prevents misleading the learner.
- *No public surface for `product_versions`* — the column exists for
  the Phase 02 AI verifier; learners don't pick a product version, so
  it ships as admin CRUD only.

**Files added**
- `app/services/catalog_service.py` (already in place from prior session,
  hardened in this phase).
- `app/schemas/catalog.py`, `app/utils/slug.py` (already in place,
  validated against guardrails).
- `app/routers/admin/{providers,product_versions,courses,exams,topics}.py`,
  `app/routers/admin/_common.py`.
- `app/routers/public/{__init__,home,vendors,exams,search,catalog_query}.py`.
- `app/templates/admin/catalog/_error.html` and per-entity
  `list.html` + `_row.html` partials.
- `app/templates/public/{home,vendor_list,vendor_detail,exam_detail,_search_results}.html`.
- `migrations/versions/0004_2c8e9a1b3d4f_catalog_per_parent_slug_uniqueness.py`.
- `tests/test_catalog_schemas_unit.py`, `tests/test_catalog_real_db.py`.

**Files modified**
- `app/main.py` — register Phase 04 routers (admin × 5, public × 4).
- `app/audit/events.py` — 11 catalog `AuditAction` constants
  (already present from prior session).
- `app/templates/_layout/header.html` — Vendors link + admin shortcut
  for `current_user.role == admin`.
- `app/static/css/base.css` — catalog table, badges, card grid.

**Deviations**
- ProductVersion ships admin-only; no public surface (per guardrails).
- Soft-delete is per-entity (only `Exam.deleted_at`). Provider/Course/
  Topic enforce "no children before delete" instead of soft-delete to
  avoid a wider migration in Phase 04.

**Quality gates (local Windows dev box)**
- `ruff check app tests migrations` — clean.
- `ruff format --check app tests migrations` — clean.
- `mypy app` — clean (54 source files).
- `pytest -q` — 38 hermetic tests pass; 26 real-DB tests skipped (gated).

**LXC sync — pending**
This local Windows machine cannot exercise the migration against the
real `exam_platform_db` cluster on the LXC. Apply order on the LXC,
gated by user confirmation:
1. Rsync repo to `/srv/exam-platform-dev`.
2. `alembic upgrade head` (applies `0004` only; round-trip-safe).
3. `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` to exercise the new
   integration suite.
4. Boot `uvicorn` on `127.0.0.1:8001`; smoke-test `/`, `/vendors`,
   `/healthz`, and a private admin curl.
5. Confirm `blog.service` active, blog DB / role / configs unchanged.

## 2026-04-29 — Phase 03 — Auth, RBAC, audit log foundation

**Status:** ✅ Complete. Report:
[`plans/reports/phase-03-260429-1613-completion.md`](../plans/reports/phase-03-260429-1613-completion.md).

**Highlights**
- Added Argon2id password hashing (`passlib`).
- Signed session cookies via `itsdangerous` (HttpOnly, SameSite=Lax,
  Secure outside dev, 7-day TTL, sid rotates on login).
- Stateless HMAC CSRF on every state-changing form POST. Single token
  per GET via `_issue_csrf_for_template` helper.
- Redis-backed sliding-window login rate limit (5/min IP, 20/h
  identifier). **Fail-closed** on Redis outage.
- Same-transaction `audit_log_writer.write()` helper + typed
  `AuditAction` enum.
- New routes: `/auth/{register,login,logout,me}`, `/admin/audit{,.json}`.
- Migration `0003_add_users_last_password_at` adds `users.last_password_at TIMESTAMPTZ`.
- Admin bootstrap CLI: `python -m scripts.create_admin`.
- HTML templates for login/register and the admin audit viewer.
- 27 tests added (auth/CSRF/rate-limit unit + 11 integration gated by
  `EXAM_PLATFORM_TEST_REAL_DB=1`); 33/33 pass on real PG+Redis.

**Live LXC verification**
- `/healthz` 200 against real PG+Redis at 127.0.0.1:8001.
- `verify_phase03.py` exercised the full flow end-to-end:
  register → /me → /admin/audit (403 student) → logout → /me (401)
  → login → POST without CSRF (403) → 6× wrong password → 429 with
  `Retry-After`. All assertions held.
- `create_admin` CLI bootstraps an admin in <1 s; the resulting user
  reads `/admin/audit{,.json}` (200 + table HTML).
- Blog DB / role / configs / services unchanged (SHA-256 stable).

**Issues fixed during execution**
- CSRF: original handler called `issue_csrf_token` twice, causing
  cookie↔form mismatch. Refactored into `_issue_csrf_for_template`
  helper that mints one token and attaches it to one response.
- Admin CLI: post-`with`-block print of `user.id` triggered
  `DetachedInstanceError`. Snapshot the id before commit.
- LXC venv `.venv/bin/*` lost their +x bits during the post-extract
  blanket chmod. Restored 0755 on `.venv/bin/*` only.
- Real-DB cleanup fixture used `Column.cast_text()` (doesn't exist on
  JSONB comparator). Switched to `cast(col, String)`.

**Deviations**
- `/auth/register` ships open for internal-beta. Documented as
  "production-not-ready" in `docs/system-architecture.md` and the
  register template; gating to invite-only is a Phase 09 task.
- 24-hour admin re-prompt: column persisted (`users.last_password_at`),
  but the enforcement gate lands when admin mutation routes appear in
  Phase 04+. Phase 03 only stores the timestamp.

**Files added (high level)**
- `app/auth/{__init__,service,session,csrf,rate_limit,permissions}.py`
- `app/audit/{__init__,events,writer}.py`
- `app/routers/auth.py`, `app/routers/admin/{__init__,audit}.py`
- `app/templates/auth/{_layout,login,register}.html`,
  `app/templates/admin/audit_list.html`
- `app/paths.py` (extracted to break circular import)
- `migrations/versions/0003_4a7e1c2b9d8f_add_users_last_password_at.py`
- `scripts/create_admin.py`, `scripts/verify_phase03.py`
- `tests/test_auth_unit.py`, `test_csrf_unit.py`,
  `test_rate_limit_unit.py`, `test_auth_real_db.py`

**Files modified**
- `app/main.py` — mount auth + admin routers; use `app.paths`.
- `app/config.py` — `session_ttl_days`, `admin_reprompt_hours`.
- `app/models/users.py` — add `last_password_at`.
- `.env.example` — surface new settings.

**Backfilled docs (this commit)**
- Filled `docs/system-architecture.md` "Authentication & authorization" section.
- Added `docs/deployment-guide.md` "Auth bootstrap" + "Auth troubleshooting" sections.
- Added `docs/code-standards.md` "Auth / RBAC / audit patterns" section.



## 2026-04-29 — Phase 02 — Database migrations & PG co-tenant setup

**Status:** ✅ Complete. Report:
[`plans/reports/phase-02-260429-1548-completion.md`](../plans/reports/phase-02-260429-1548-completion.md).

**Highlights**
- Provisioned `exam_platform_user` + `exam_platform_db` on the existing
  PG14 cluster (loopback-only); blog DB / role / configs untouched.
- Installed Redis on the LXC (loopback-only, protected-mode, no auth).
- Implemented 13 SQLAlchemy 2.0 model files covering all 21 tables
  (16 active + 5 Phase 2/3 schema-only stubs).
- Authored hand-edited initial migration (`0001_initial_schema.py`,
  892 lines) with 23 native PG ENUM types, 9 critical indexes, deferred
  back-edge FK to break the `questions ↔ question_duplicate_groups`
  cycle, and explicit `DROP TYPE` in downgrade.
- Authored idempotent seed migration (`0002_seed_baseline_data.py`):
  Fortinet provider, FortiOS 7.4, NSE4 stub course+exam, 5
  source_domains.
- Round-trip `upgrade head → downgrade base → upgrade head` verified.
- Real-DB smoke test passes (`EXAM_PLATFORM_TEST_REAL_DB=1`).
- Live `/healthz` returns 200 with `db: ok` and `redis: ok` against
  real PG + Redis on the LXC at `127.0.0.1:8001`.

**Schema additions per Phase 02 plan**
- `import_items` table — row-level Excel import staging.
- `questions.source_locator JSONB` — back-trace to import row.
- `attempt_answers.order_index INT NOT NULL` + `UNIQUE(attempt_id, order_index)`.

**Deviations**
- Locale `C.UTF-8` instead of `en_US.UTF-8` (latter not generated; user
  approved the substitution to avoid system-level locale-gen).
- Role `CONNECTION LIMIT = 10` instead of plan's 30 (dev right-sizing).
- Seed migration uses `ON CONFLICT DO NOTHING` (cleaner than guarded
  SELECTs, equally idempotent).
- Migration files prefixed `0001_` / `0002_` for chronological readability.

**Issues fixed during execution**
- Autogenerate emitted duplicate `CREATE TYPE` for shared ENUMs — fixed
  with explicit pre-creation + `create_type=False`.
- Circular FK `questions ↔ question_duplicate_groups` — deferred one
  edge to ALTER.
- Downgrade leaked ENUM types — added explicit `DROP TYPE` loop.
- Seed `INSERT … WHERE` had Postgres parameter type-inference bug —
  switched to `ON CONFLICT DO NOTHING` / `CAST(:p AS type)`.

**Files changed (high level)**
- New: `app/models/*.py` (13 files), `alembic.ini`, `migrations/env.py`,
  `migrations/script.py.mako`, `migrations/versions/0001_*.py`,
  `migrations/versions/0002_*.py`, `tests/test_models_smoke.py`,
  `scripts/db-setup.sh` (local) / `scripts/db_setup.sh` (LXC).
- Modified: `app/db.py` (Base re-exported from `app.models.base`).

**Backfilled docs (this commit)**
- `docs/project-overview-pdr.md`
- `docs/system-architecture.md`
- `docs/deployment-guide.md`
- `docs/code-standards.md`
- `docs/project-roadmap.md`
- `docs/project-changelog.md`

---

## 2026-04-28 → 2026-04-29 — Phase 01 — Project scaffolding & local dev env

**Status:** ✅ Complete. Report:
[`plans/reports/phase-01-260429-1358-completion.md`](../plans/reports/phase-01-260429-1358-completion.md).

**Highlights**
- Initialized Python 3.12 project with `uv` (lockfile committed).
- Set up FastAPI app factory (`app/main.py`), pydantic-settings config,
  SQLAlchemy 2.0 engine plumbing, structlog with `request_id`
  middleware, vendored HTMX 1.9.12 + Alpine 3.14.1.
- Implemented `/healthz` with DB + Redis pings (200 if healthy, 503 if
  any down).
- Authored `docker-compose.yml` (db + redis + app + mailhog) and
  `Dockerfile` (Python 3.12-slim + uv prod install + `HEALTHCHECK`).
- Pre-commit config: ruff (lint+format), mypy, gitleaks.
- 5 unit tests pass with mocked DB/Redis (healthy + degraded paths).
- README documents 3-command quickstart + HTMX patterns.

**Issues fixed during execution**
- Hatchling build needed `README.md` to exist before `uv sync` — created
  README early, expanded later.
- `/healthz` initially hung when no DB/Redis was running — added
  `connect_timeout=3` (psycopg) and `socket_connect_timeout=2` (Redis).

**Files added**
- `pyproject.toml`, `uv.lock`, `.env.example`, `.editorconfig`,
  `.dockerignore`, `.pre-commit-config.yaml`.
- `Dockerfile`, `docker-compose.yml`.
- `README.md`.
- `app/__init__.py`, `app/config.py`, `app/db.py`, `app/redis_client.py`,
  `app/deps.py`, `app/logging.py`, `app/middleware.py`, `app/main.py`,
  `app/routers/__init__.py`, `app/routers/health.py`.
- `app/templates/base.html` + `_layout/{header,footer}.html` + `index.html`.
- `app/static/css/base.css`, `app/static/js/htmx.min.js`,
  `app/static/js/alpine.min.js`.
- `tests/__init__.py`, `tests/conftest.py`, `tests/test_health.py`,
  `tests/test_config.py`.

**Deviations**
- ruff-format is the active formatter; Black kept as a backup dev dep,
  not in pre-commit.
- Empty package directories (`app/services/`, `app/models/`,
  `app/schemas/`, `app/workers/`, `app/utils/`) were created without
  `__init__.py` placeholders — populated in Phase 02 (`app/models/`)
  or later phases.
