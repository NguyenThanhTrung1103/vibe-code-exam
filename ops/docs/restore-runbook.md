# Restore Runbook (Phase 10)

## When to use this
- Production data corruption.
- DR drill (see `dr-drill-log.md` for the schedule).
- Restoring to a side cluster for forensic analysis.

> **Never** restore over `exam_platform_db` while the app is live.
> Always restore into a separate database (`exam_platform_db_drill` or
> `exam_platform_db_restore_test`) and swap when ready.
>
> **Never** restore the exam dump into `blogdb`. The script refuses on
> purpose.

## Prerequisites

```dotenv
EXAM_DB_HOST=127.0.0.1
EXAM_DB_USER=exam_platform_user
EXAM_DB_PASSWORD=<vault>
RESTIC_REPO=...           # required only when restoring from off-site
RESTIC_PASSWORD_FILE=/root/.config/restic-pw
EXAM_DRILL_DB=exam_platform_db_drill   # default
```

## Steps

### 1. Identify the snapshot to restore

If you're restoring from off-site:

```bash
sudo -i
source /srv/exam-platform/.env
restic snapshots --tag exam-pg
# pick a snapshot id, or use `latest`
```

If local-only, the most recent dump under `/var/backups/postgres/` is
selected automatically.

### 2. Pre-create the drill database (ONE-TIME)

`exam_platform_user` does **not** have `CREATEDB` — that's intentional,
so the app can never accidentally create or drop a database. The drill
operator pre-creates the drill DB with the postgres superuser:

```bash
sudo -u postgres createdb -O exam_platform_user exam_platform_db_drill
```

### 3. Run the restore helper

```bash
/srv/exam-platform/ops/backup/restic-restore.sh latest /tmp/exam-restore-$(date +%s)
```

What it does:

1. (Off-site path) `restic restore` the snapshot to the target dir.
2. (Local path) picks the newest `exam_*.dump`.
3. Confirms the drill DB exists; aborts with instructions if not.
4. `pg_restore --dbname=<drill_db> --no-owner --no-privileges --clean --if-exists <dump>`.
5. Smoke probes: counts of `users` and `alembic_version`.

### 3. Verify the restored database

```bash
PGPASSWORD="$EXAM_DB_PASSWORD" psql -h 127.0.0.1 -U exam_platform_user \
  -d exam_platform_db_drill <<'SQL'
\dt
SELECT count(*) FROM users;
SELECT count(*) FROM exams WHERE status = 'published';
SELECT count(*) FROM attempts;
SELECT version_num FROM alembic_version;
SQL
```

The version in `alembic_version` should equal the head from
`migrations/versions/` at the time the dump was taken.

Optionally point the test runner at the drill DB:

```bash
EXAM_PLATFORM_TEST_REAL_DB=1 \
  DATABASE_URL="postgresql+psycopg://exam_platform_user:$EXAM_DB_PASSWORD@127.0.0.1:5432/exam_platform_db_drill" \
  /srv/exam-platform-dev/.venv/bin/python -m pytest tests/test_models_smoke.py -q
```

### 5. Clean up

```bash
sudo -u postgres dropdb --if-exists exam_platform_db_drill
rm -rf /tmp/exam-restore-*
```

## Failure modes

- `pg_restore` returns 1 with **warnings only** — usually fine. The
  helper script swallows this with `|| true` because non-fatal warnings
  about missing roles are common when `--no-owner --no-privileges` is set.
- `pg_restore` returns 1 with **errors** — investigate. Common causes:
  - Drill DB already exists with rows → drop manually.
  - Disk full on the LXC → `df -h /var/lib/postgresql`.
  - Postgres version mismatch (don't restore a `pg_dump` from PG 15
    into PG 14 with custom format and out-of-the-box tooling).

## Safe-cutover playbook (production restore)

If you actually need to restore the LIVE database:

1. Stop the app: `systemctl stop exam-platform-web` (Phase 11 unit).
2. Take a fresh `pg_dump` of the live DB *as a safety net*.
3. Rename live → swap: `psql -d postgres -c "ALTER DATABASE exam_platform_db RENAME TO exam_platform_db_old_$(date +%s);"`.
4. Restore the snapshot → `exam_platform_db`.
5. Smoke test (`/healthz`, `/readyz`, login + start attempt).
6. Restart the app.
7. Keep `exam_platform_db_old_*` around for 7 days, then drop.
