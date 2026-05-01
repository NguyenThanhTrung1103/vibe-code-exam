# Deployment / Operations Guide

Practical setup + ops reference. Updated after each phase that changes
runtime behaviour, env vars, ops runbooks, or troubleshooting flows.

## Environments

| Env | Purpose | Path | Bound to |
|---|---|---|---|
| **local (Windows dev)** | Author code, run tests | `E:\Vibe Code\Vibe Code\Exam` | `127.0.0.1:8000` (default) |
| **dev (LXC)** | Real PG14 + Redis verification | `/srv/exam-platform-dev` | `127.0.0.1:8001` |
| **prod (LXC)** | Public Soft-Launch (Phase 11) | `/srv/exam-platform` | nginx 80/443 → uvicorn 127.0.0.1:8000 |

## Local development setup (3 commands)

```bash
uv sync --extra dev          # creates .venv + installs all deps
cp .env.example .env         # bootstrap config
uv run uvicorn app.main:app --reload
```

Verify: `curl http://127.0.0.1:8000/healthz`. Without local PG/Redis you'll
see `{"status":"degraded","db":"down","redis":"down"}` (503) — that's
expected. Tests use mocked deps, so `pytest` runs cleanly without backing
services.

### Quality gates (run before push)

```bash
uv run pytest
uv run ruff check app tests migrations
uv run ruff format --check app tests migrations
uv run mypy app
```

### Pre-commit hooks (one-time bootstrap)

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Hooks: ruff (lint+format), mypy, gitleaks, plus standard hygiene.

## LXC dev environment (192.168.99.97)

The LXC runs the blog stack already; we **co-tenant** without disturbing it.

### What lives where

- App source: `/srv/exam-platform-dev/` (root:root, dirs 0750, files 0640).
- App venv: `/srv/exam-platform-dev/.venv/` (managed by `uv`).
- Env file: `/srv/exam-platform-dev/.env` (mode 0600, on-server only).
- DB: `exam_platform_db` on the existing PG14 cluster.
- Role: `exam_platform_user` (NOSUPERUSER, NOCREATEDB, NOCREATEROLE,
  NOREPLICATION, CONNECTION LIMIT 10).
- Redis: `redis-server.service` installed in Phase 02 — bind 127.0.0.1 ::1,
  protected-mode yes, no auth, port 6379.

### Initial provisioning (one-time)

1. **Install `uv`** (if missing):
   ```bash
   python3 -m pip install --user uv
   echo 'export PATH=$HOME/.local/bin:$PATH' >> ~/.bashrc
   ```
2. **Install Redis** (if missing):
   ```bash
   apt-get update -qq && apt-get install -y redis-server
   systemctl enable --now redis-server
   redis-cli -h 127.0.0.1 ping     # → PONG
   ```
3. **Sync source**: `tar -czf … --exclude=… ./` locally → `scp` →
   `tar -xzf … --no-same-owner` on LXC. Standard exclude list:
   `.venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`,
   `node_modules`, `.env`, `.env.*` (keep `.env.example`), `.opencode/`,
   `.opencode.backup/`, `.claude/`, `external/`, `worktrees/`, `plans/`,
   `dist/`, `build/`, `.git/`, `*.log`.
4. **Create DB role + database**: see DB Setup section below.
5. **Install deps**: `cd /srv/exam-platform-dev && uv sync --extra dev`.
6. **Apply migrations**: `uv run alembic upgrade head`.

## Database setup (Phase 02)

### One-time provisioning

`scripts/db_setup.sh` is **idempotent** — safe to re-run.

```bash
cd /srv/exam-platform-dev
set -a; source .env; set +a
EXAM_PLATFORM_DB_PW="$POSTGRES_PASSWORD" bash scripts/db_setup.sh
```

What it does (only inside `exam_platform_db`, never touches `blogdb`):
1. Creates role `exam_platform_user` if absent (LOGIN, NOSUPERUSER,
   NOCREATEDB, NOCREATEROLE, NOREPLICATION, CONNECTION LIMIT 10).
2. Creates database `exam_platform_db` if absent (UTF-8 + C.UTF-8 locale,
   from `template0`, owned by the new role).
3. Inside the new DB only: `REVOKE ALL ON SCHEMA public FROM PUBLIC` and
   `GRANT ALL ON SCHEMA public TO exam_platform_user`.
4. Sets per-role-in-this-DB timeouts: `statement_timeout=15s`,
   `idle_in_transaction_session_timeout=60s`, `lock_timeout=5s`.
5. Smoke-pings the new connection from `exam_platform_user`.

### Alembic migration workflow

```bash
# Apply all migrations
uv run alembic upgrade head

# Rollback one revision
uv run alembic downgrade -1

# Full rollback (drops all schema + ENUM types)
uv run alembic downgrade base

# Inspect current head + history
uv run alembic current
uv run alembic history --verbose

# Generate a new migration after model changes (REVIEW before commit)
uv run alembic revision --autogenerate -m "kebab-case-slug"
```

**After autogenerate always review the generated file**:
- Did it emit duplicate `CREATE TYPE` for shared ENUMs? Hand-edit to use
  `postgresql.ENUM(..., create_type=False)` after the first occurrence.
- Did it order tables correctly across circular FKs? Defer one edge to an
  `op.create_foreign_key(...)` after the dependent table exists.
- Does `downgrade()` drop every ENUM type the upgrade created? PG keeps
  ENUM types after table drop — re-upgrade will fail without explicit
  `DROP TYPE`. See `migrations/versions/0001_*.py` for the canonical
  pattern (`_ENUM_TYPE_NAMES` tuple + tail loop).

### Round-trip verification (run before merging schema changes)

```bash
uv run alembic upgrade head
uv run alembic downgrade base   # all schema + types gone
uv run alembic upgrade head     # back to current head
```

If the second `upgrade head` fails, the downgrade is not symmetric — fix it.

### Real-DB smoke test

```bash
EXAM_PLATFORM_TEST_REAL_DB=1 uv run pytest tests/test_models_smoke.py -v
```

The test inserts one row of every active entity inside a transaction, then
**always rolls back** — it must be safe to run against any DB without
leaving artifacts.

## Auth bootstrap (Phase 03)

### Create the first admin

`scripts/create_admin.py` is idempotent — refuses if email or username
already exists.

```bash
# On the LXC, inside /srv/exam-platform-dev/
EXAM_ADMIN_PW='your-strong-password' \
  uv run python -m scripts.create_admin \
  --email admin@example.com --username admin
```

The CLI writes a `system`-actor `user.registered` audit row in the same
transaction as the user insert.

### Rotate `SECRET_KEY` (revoke all sessions)

Sessions and CSRF tokens both derive their HMAC from `SECRET_KEY`.
Rotating it invalidates every existing cookie atomically — useful as the
panic-button after a suspected leak.

```bash
NEW=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$NEW|" /srv/exam-platform-dev/.env
# Restart uvicorn (reload picks up the new env)
```

After rotation, every user must log in again. CSRF cookies issued before
rotation are also invalidated — users on a stale GET form will get a
fresh token on their next page load.

### Re-prompt window for admins

`ADMIN_REPROMPT_HOURS=24` env var defines how long an admin's session
"trusts" their password. After 24 h since `users.last_password_at`, the
session middleware (Phase 09 will wire it) forces a re-entry of password
on the next admin action. Phase 03 only stores the timestamp; the
enforcement gate is added when admin mutation routes land in Phase 04+.

## Auth troubleshooting

### `403 invalid csrf` on every form POST

You probably called `issue_csrf_token` more than once on the same
response in your route handler. The second call mints a new token + sets
a new cookie, breaking the form↔cookie pair. Use the
`_issue_csrf_for_template` helper in `app/routers/auth.py` as a model.

### `429 too many attempts` even though Redis is up

Counters from a previous test or attempt may still be ticking. Flush
just the login keys:

```bash
redis-cli EVAL "for _,k in ipairs(redis.call('keys','rl:login_*')) do redis.call('del',k) end" 0
```

Production should NEVER do this — every counter erase is a free
brute-force opportunity. Dev/test only.

### Login fails closed with `429 rate_limit_unavailable`

Redis is unreachable. By design we **fail closed** — better to lock out
legitimate users for 30 s than to allow unlimited tries. Diagnose Redis
with `redis-cli ping` and `systemctl status redis-server`.

## Catalog (Phase 04) operations

### Applying migration `0004` on the LXC

```bash
ssh devuser@192.168.99.97
cd /srv/exam-platform-dev
source .venv/bin/activate
alembic upgrade head            # applies 0004 (composite UNIQUE constraints)
```

The migration is constraint-only and safe to round-trip:

```bash
alembic downgrade 4a7e1c2b9d8f  # back to 0003
alembic upgrade head             # re-apply 0004
```

Verify the constraints exist:

```bash
psql -h 127.0.0.1 -U exam_platform_user -d exam_platform_db -c "
SELECT conname, contype, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conname IN (
  'uq_courses_provider_slug',
  'uq_exams_course_slug',
  'uq_topics_exam_slug',
  'uq_product_versions_provider_name_version'
);"
```

Confirm seed data still valid (`fortinet`, `nse4`, FortiOS 7.4 row):

```bash
psql -h 127.0.0.1 -U exam_platform_user -d exam_platform_db \
  -c "SELECT slug FROM providers; SELECT slug FROM courses; SELECT slug FROM exams;"
```

### Catalog admin smoke test

After bootstrapping an admin (Phase 03 CLI), exercise the catalog flow:

```bash
# Boot uvicorn on 127.0.0.1:8001 (loopback only)
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001 &

# Anonymous → 401
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/admin/providers

# Anonymous public home / vendors → 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/vendors

# Public detail of unpublished/missing → 404
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/exams/nope/nope
```

### Catalog troubleshooting

**Symptom:** admin POST returns `400` with body `provider slug 'x' already in use`.

Fine — that's the friendly duplicate-slug response. Pick a different slug
or edit the existing provider/course/exam/topic.

**Symptom:** admin POST returns `403 invalid csrf`.

The form's `csrf_token` doesn't match the `exam_csrf` cookie. Cause:
either the page was opened in one browser session and submitted in
another, or the form was tampered with. Refresh the admin list page to
mint a fresh token.

**Symptom:** public exam page shows "Coming soon — No questions
available yet" even though questions look loaded.

Phase 04 only counts questions where `status = 'published'` AND
`deleted_at IS NULL`. Phase 05's importer ships them as `imported`/
`needs_review`/`verified_*`. Promotion to `published` happens in the
question-bank workflow (Phase 06). For dev/testing, an admin can bump
status directly via SQL — but in production, never bypass the workflow.

**Symptom:** vendor page returns `404` on a provider that exists.

Public vendor detail requires at least one published, non-deleted exam
under the provider. Otherwise the page 404s to avoid empty ghost UI.
Either publish an exam or hide the link in your admin docs.

## Question bank (Phase 06) operations

`/admin/questions` is the editor. Filters: `exam_id`, `topic_id`,
`status`, `difficulty`, `q` (ILIKE), `page`. Bulk-assign topic via
the bottom-of-list form. No new migration needed — existing
`questions` / `question_options` / `question_explanations` tables
from Phase 02 cover the surface.

Imported questions (Phase 05) are editable through the same Phase 06
routes. After review, admin sets `status` to `verified_low/medium/high`
or `published` from the editor.

### Public visibility rule (after Phase 06)

A question is visible publicly when **all** of:
1. `Question.status == 'published'`
2. `Question.retired_at IS NULL`
3. `Question.deleted_at IS NULL`
4. Parent exam: `publish_status='published'`
5. Parent exam: `deleted_at IS NULL`

Phase 07/08 join builders MUST encode this filter explicitly (same
pattern as Phase 04's `published_exam_filter()` helper).

### Question CRUD troubleshooting

| Symptom | Resolution |
|---------|------------|
| `at least two non-empty options required` | Fill option B (and onwards) |
| `belongs to exam X` on bulk-assign | Topic does not live under the question's exam |
| Editor 404 on a soft-retired question | Use `/restore` to make it active first |
| `correct label "Z" has no matching option` | Pick a label that appears in the options list (A–E) |

## Excel import (Phase 05) operations

### Uploads directory

The pipeline writes uploaded XLSX files to
`<UPLOADS_DIR>/imports/<import_id>.xlsx` with mode 600. Default
`UPLOADS_DIR=/srv/exam-platform/uploads`. Create it once on the LXC:

```bash
mkdir -p /srv/exam-platform/uploads/imports
chmod 700 /srv/exam-platform /srv/exam-platform/uploads /srv/exam-platform/uploads/imports
chown -R root:root /srv/exam-platform
```

The directory MUST be outside any path served by `app/static` or nginx.

### Migration `0005`

```bash
ssh exam-lxc
cd /srv/exam-platform-dev && source .venv/bin/activate
alembic upgrade head     # applies 0005 (imports.target_exam_id +
                          # column_mapping JSONB + file_path)
```

Round-trip-safe:

```bash
alembic downgrade 2c8e9a1b3d4f
alembic upgrade head
```

### Configuration

`app/config.py` adds:

```
UPLOADS_DIR=/srv/exam-platform/uploads
IMPORT_MAX_BYTES=26214400      # 25 MB
IMPORT_MAX_ROWS=5000
```

Add these to `.env` if you want to override the defaults.

### Import troubleshooting

**Symptom:** Admin sees `400 mapping missing required fields: [...]`.

Required canonical fields are `question_text`, `option_a`, `option_b`,
`correct_answer`. The mapping form must point Excel headers at all four
or save will reject.

**Symptom:** Admin sees `400 file is not a valid .xlsx (bad magic bytes)`.

The uploaded file is not a real XLSX (zip header check). Ensure admin
exports as `.xlsx` not `.xls` / `.csv` / `.ods`.

**Symptom:** `Confirm import` button does nothing visible.

Check `import_items.status` distribution
(`SELECT status, COUNT(*) FROM import_items WHERE import_id=:i GROUP BY status;`).
Confirm only processes `status='ok'` items. If everything is in
`duplicate` / `error` / `skipped`, confirm legitimately produces zero
new questions.

**Symptom:** Imported questions don't appear on the public page.

By design — imported questions are private/draft (`Question.status='imported'`).
Admin must publish the parent exam (Phase 04) AND the questions
(Phase 06) before they become visible publicly.

## Healthcheck

```bash
curl http://127.0.0.1:8001/healthz   # LXC dev
curl http://127.0.0.1:8000/healthz   # local
```

Returns `200 {"status":"ok","db":"ok","redis":"ok"}` when all green,
`503 {"status":"degraded","db":"...","redis":"..."}` when any backing
dependency is down.

## Running uvicorn

```bash
# Local dev (auto-reload)
uv run uvicorn app.main:app --reload

# LXC dev (loopback only — never bind 0.0.0.0)
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001

# Production (Phase 11) — behind nginx with ProxyHeadersMiddleware
# uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Never bind `0.0.0.0`** on the LXC — that exposes the dev app on the
LAN. Always 127.0.0.1.

## Blog-stack safety rules

The LXC is co-tenant. We never touch the blog stack:
- ❌ Do not touch `blogdb`, `blog` role, `/srv/blog-website`, `blog.service`.
- ❌ Do not edit `pg_hba.conf`, `postgresql.conf`, `nginx`, `cloudflared`.
- ❌ Do not bind to ports 80, 443, 8000, 5432-on-public, or 6379-on-public.
- ✅ Verify before/after: SHA-256 of those config files; `systemctl is-active`
  for blog/postgresql/nginx/cloudflared/redis-server.

The `db_setup.sh` script has a hard-stop guard: refuses to run if
`EXAM_PLATFORM_DB_NAME=blogdb` or `EXAM_PLATFORM_DB_USER=blog`.

## Troubleshooting

### `/healthz` hangs or returns 503

- Is PG up? `pg_isready -h 127.0.0.1 -p 5432`.
- Is Redis up? `redis-cli -h 127.0.0.1 ping` → expect `PONG`.
- Check `/etc/redis/redis.conf` `bind 127.0.0.1 ::1` and
  `protected-mode yes`. Should match the SHA we record before each phase.

### Alembic upgrade fails with `type "X" already exists`

The previous downgrade missed a `DROP TYPE`. Drop the orphan type as
postgres superuser:

```sql
DROP TYPE IF EXISTS "<name>";
```

…then add it to `_ENUM_TYPE_NAMES` in the migration so the next downgrade
removes it.

### Alembic upgrade fails with `column reference is ambiguous`

A seed `INSERT INTO … SELECT … WHERE …` referenced the same parameter in
two different contexts and Postgres couldn't deduce the type. Use either
`ON CONFLICT (col) DO NOTHING` or `CAST(:param AS type)`. Don't use the
`'value'::type` cast inside SQLAlchemy `text()` — it conflicts with the
`:param` syntax.

### `could not change directory to /root` warnings

Cosmetic. `sudo -u postgres psql ...` warns when `postgres` can't `chdir`
to root's home. Doesn't affect any SQL operation. Ignore.

### `psycopg` connection takes ~10 s to fail in dev

When PG isn't running locally, psycopg on Windows retries IPv6→IPv4. We
set `connect_timeout=3` in `app/db.py` to bound this. With real PG up,
`/healthz` is sub-50 ms.

### Tarball extract fails with "Cannot change ownership"

Windows-built tar contains Windows UIDs the LXC can't apply. Always extract
with `--no-same-owner`. Files extract fine; only chown is skipped (which
we don't want anyway — the LXC reset perms with `chmod` after).

## Backup posture

| Phase | Posture |
|---|---|
| Phase 1 — pre-Internal-Beta | Manual `pg_dump exam_platform_db` + `pg_restore` drill, recorded. |
| Phase 1 — pre-Public-Soft-Launch | Automated off-site backup (restic-equivalent) with 7d/4w/6m retention. Restore drill within last 30 days. |

Phase 10 (Backup, observability, DR drill) owns implementation. Until then,
ad-hoc `pg_dump` is the safety net.

## Pinned versions (Phase 02)

| Tool | Local | LXC | Notes |
|---|---|---|---|
| Python | 3.12.10 | 3.14.4 | `pyproject.toml` requires `>=3.12`. Both currently pass all gates. |
| uv | 0.11.8 | 0.11.8 | Matches. |
| PostgreSQL | n/a (no local PG) | 14.22 | `pg_hba.conf` `host all all 127.0.0.1/32 scram-sha-256` already permits the new role. |
| Redis | n/a | 6.0.16-1ubuntu1.1 | Ubuntu jammy security pocket. |
| Alembic | from `uv.lock` | from `uv.lock` | |

## Decision rationale (deployment-side)

**Why install Redis on the LXC instead of skipping it?**
The `/healthz` contract requires `redis: ok` for status 200, and Phase 2
will run RQ jobs. Skipping now would mean editing `/healthz` to be
DB-only — extra code that gets reverted later. Installing Redis once,
loopback-only, is cleaner than carrying a temporary feature flag.

**Why bind Redis to 127.0.0.1 only and skip AUTH?**
Loopback-only on a single-tenant LXC where root is the only user means
network exposure is zero. Adding `requirepass` would force every client
to plumb a secret with no security gain over the loopback isolation. If
the LXC ever stops being single-tenant, we add AUTH then.

**Why `CONNECTION LIMIT 10` on the dev role?**
Dev is one-developer + one app process. `10` covers reload bursts, smoke
tests, and an interactive psql session. Smaller than the plan's `30`
because dev should fail loud on connection leaks; a tighter limit
surfaces leaks earlier.

**Why `C.UTF-8` instead of `en_US.UTF-8`?**
The LXC didn't have `en_US.UTF-8` generated. Using `C.UTF-8` (universally
present on glibc) avoided an `apt`-adjacent system change (`locale-gen`).
For Phase 1 content we don't depend on language-natural sort order;
`C.UTF-8` is Unicode-safe and binary-deterministic. Trade-off: `Á` sorts
after `Z`. Acceptable for an exam platform whose user-facing UI controls
its own ordering.

**Why run migrations against real PG/Redis on the LXC, not just mocked tests?**
Mocks confirm code paths but not the *interaction* with PG14's actual
parser/planner. We caught two real seed-migration bugs (`::cast` vs `:param`
syntax, parameter-type inference) only because we ran against a real DB.
A mock would have happily accepted the broken SQL.

**Why per-role `statement_timeout=15s`?**
A runaway query in dev should fail fast — either the query is wrong, or
the data is unexpected. 15 s is well above any real query's ceiling and
cuts pathological cases off before they wedge connections.

**Why update docs after every phase rather than at the end?**
Stale docs compound. After Phase 12, recovering Phase-02 nuance is hours
of digging through reports. Per phase: 10 min of doc edits, with the
context fresh. Also forces the implementer to articulate the rationale,
which usually surfaces gaps in the design.
