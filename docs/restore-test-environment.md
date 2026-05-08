# Restore Test Environment

End-to-end recipe to bring up a fresh **test instance** of the exam
platform on a new host using only this Git repository plus the test
dataset shipped under `seed/`.

> **Test environment only.** Production deployments must not use this
> seed file — it carries the contents of the live LXC test DB.

## Prerequisites on the new host

- Ubuntu 22.04 (or any distro with the equivalents)
- Python 3.12
- PostgreSQL 14
- Redis 7
- `git`, `uv` (`pip install uv`)
- Free TCP port 8001 on loopback

## 1. Clone the repo

```bash
git clone http://192.168.99.33/root/Exam.git /srv/exam-platform-dev
cd /srv/exam-platform-dev
git checkout Exam
```

## 2. Create the database role + database

Use a strong password — generate one fresh, do not copy from anywhere
else. The role mirrors the LXC's least-privilege role.

```bash
sudo -u postgres psql <<SQL
CREATE ROLE exam_platform_user LOGIN PASSWORD 'CHANGE_ME_LOCAL_TEST'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 10;
CREATE DATABASE exam_platform_db OWNER exam_platform_user;
SQL
```

## 3. Create `.env` from the example

```bash
cp .env.example .env
$EDITOR .env
```

Fill in at minimum:

```dotenv
DATABASE_URL=postgresql+psycopg://exam_platform_user:CHANGE_ME_LOCAL_TEST@127.0.0.1:5432/exam_platform_db
REDIS_URL=redis://127.0.0.1:6379/0
SECRET_KEY=$(openssl rand -hex 32)        # paste the generated value
ENV=local
DEBUG=false
APP_HOST=127.0.0.1
APP_PORT=8001
UPLOADS_DIR=/srv/exam-platform-dev/uploads
```

`SECRET_KEY` rotation note: any sessions/CSRF tokens issued under the
old key are invalidated. That is fine on a fresh host; existing users
just sign in again.

## 4. Install Python dependencies

```bash
uv sync --extra dev
```

This creates `.venv/` (gitignored) and installs everything pinned in
`uv.lock`.

## 5. Run Alembic migrations

Migrations build the empty schema. The seed migration `0002` adds a
single Fortinet provider stub, but loading `seed/test_dataset.sql`
afterwards is **idempotent** because it carries the same row's primary
key — the `INSERT` would conflict, so we wipe and reseed:

```bash
uv run alembic upgrade head

# Optional belt-and-suspenders — clear seed migration's stub rows so the
# bigger seed file can load without PK collisions. Skip if your DB is
# fresh and 0002 has not run yet.
sudo -u postgres psql exam_platform_db <<SQL
TRUNCATE TABLE
  source_domains,
  import_items, imports,
  question_explanations, question_options, questions,
  topics, exams, courses, product_versions, providers
RESTART IDENTITY CASCADE;
SQL
```

## 6. Load the test dataset

```bash
sudo -u postgres psql exam_platform_db -v ON_ERROR_STOP=1 -f seed/test_dataset.sql
```

Or use the wrapper:

```bash
bash scripts/restore-test-dataset.sh
```

Expected: 1 provider, 1 exam, 259 questions, 1076 options, 164 explanations.

## 7. Create a test admin user

The seed file does **not** include `users` — no real password hashes
ship in the repo. Use the project's existing helper to create a fresh
admin under your control:

```bash
EXAM_ADMIN_PW='CHANGE_ME_TEST_ONLY' \
  uv run python -m scripts.create_admin \
  --email admin@test.local --username admin
```

The script is idempotent and audit-logged. Document this account as
**test-only** in your local notes; rotate the password before any
public exposure.

## 8. (Optional) Restore uploads

This repo does **not** ship uploaded files — the import history table
keeps a back-trace, but the original XLSX files live on the source
host's `/srv/exam-platform/uploads/` only. If you need them on the
new host:

```bash
# On the source host
tar -czf /tmp/uploads.tar.gz -C /srv/exam-platform/uploads .
scp /tmp/uploads.tar.gz user@new-host:/tmp/

# On the new host
mkdir -p /srv/exam-platform-dev/uploads
tar -xzf /tmp/uploads.tar.gz -C /srv/exam-platform-dev/uploads
shred -u /tmp/uploads.tar.gz
```

If you only want the test dataset (which already includes import
metadata), this step is **optional** — questions render fine without
their original source files.

## 9. Start the app

Local dev:

```bash
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Or, if you want the systemd unit + hardening from the runbook:

```bash
sudo cp ops/systemd/exam-platform-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now exam-platform-web.service
```

## 10. Smoke test

```bash
# Health
curl -sS http://127.0.0.1:8001/healthz   # {"status":"ok","db":"ok","redis":"ok"}
curl -sS http://127.0.0.1:8001/readyz    # 200, alembic head match

# Public pages
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8001/          # 200
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8001/practice  # 200
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8001/vendors   # 200

# Admin (browser-style, expect redirect)
curl -sS -H 'Accept: text/html' -o /dev/null -w "HTTP %{http_code} loc=%{redirect_url}\n" \
  http://127.0.0.1:8001/admin
# expected: HTTP 303 loc=http://127.0.0.1:8001/auth/login?next=/admin
```

## 11. End-to-end as a guest (optional)

Start a Learning Mode attempt, autosave an answer, verify the page
re-renders with the solution panel visible:

```bash
exam_id=1   # NSE 4 — FortiGate Security
location=$(curl -sS -i -X POST http://127.0.0.1:8001/practice/${exam_id}/start \
            -d 'mode=practice' | awk '/^location:/ {print $2}' | tr -d '\r')
echo "redirected to: ${location}"
```

Open `http://127.0.0.1:8001${location}` in a browser, pick an answer,
and confirm the green "Correct answer" panel appears immediately.

For Mock Exam Mode use `mode=exam&question_count=20`. Answers must
remain hidden until you submit.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `psql: ERROR: duplicate key value violates unique constraint "providers_pkey"` | The Alembic seed migration `0002` already inserted Fortinet; the seed file's `INSERT` collides | Run the `TRUNCATE … RESTART IDENTITY CASCADE` block in step 5 before re-loading |
| `/practice` empty | Questions present but `Question.status != published` | Apply the auto-publish hot-fix (commit `4e927f8` and later) — already in this branch |
| 500 on `/`, `/vendors`, `/practice` after deploy | `pretty_vendor` Jinja filter not registered globally | Pull commit `43b07ec` or later |
| `/admin` returns 401 from curl but works in browser | Pre-existing behaviour — admin gate sends 303 only when `Accept: text/html` | Use `-H 'Accept: text/html'` |
| `/healthz` reports `db: down` | Postgres role lacks LOGIN, or password mismatch | Re-check `DATABASE_URL` in `.env` |
| `alembic upgrade head` fails on `pg_trgm` index | Postgres `pg_trgm` extension missing | `sudo -u postgres psql exam_platform_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"` |

## What this restore does NOT cover

- Production secrets (rotate fresh on every host)
- `restic` / off-site backup wiring (separate `ops/docs/backup-runbook.md`)
- Nginx / TLS / cloudflared (Phase 12 — see `ops/nginx/exam-platform.conf` template)
- Real user accounts (deliberately excluded — see step 7)
