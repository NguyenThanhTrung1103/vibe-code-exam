---
phase: 10
title: Backup, observability, DR drill
status: pending
effort: 2 days
priority: high
depends_on: [02]
parallel_ok_after: [02]
---

# Phase 10 — Backup, Observability, DR Drill

## Context Links
- PRD §27 (backup & DR), §28 (observability)
- Phase 02 (database) must exist for backups to make sense

## Overview
Provision operational scaffolding sized for MVP, not for Phase 2: documented per-database `pg_dump`, uploads snapshot, **at least one executed restore drill** before public launch, Sentry release tagging, structured logs, `/healthz` and `/readyz`. Restic off-site automation is preferred but **not a blocker for internal beta** — a documented manual backup is acceptable for the first beta cycle. Public soft-launch *does* require automated off-site backups.

## Key Insights
- **Backups are not real until restored.** A `pg_dump` that nobody has read from is wishful thinking. Drill at least once before public launch; monthly thereafter.
- **Phase split (revised per senior-dev review):**
  - **Internal beta (5 users) gate:** documented backup procedure + at least one successful manual `pg_dump` + `pg_restore` drill. Off-site automation may be manual for the first cycle.
  - **Public soft-launch gate:** automated daily off-site backup (restic or equivalent) + tested retention + drill within last 30 days.
- **Co-tenant cluster** — back up exam DB *separately* from blog DB so each restore is independent.
- **Encryption at rest off-site** — `restic` (encrypted+deduped) to object storage. Avoid raw S3 dumps.
- **No Prometheus/Grafana at MVP.** Sentry + structlog stdout + UptimeRobot is enough. Prometheus is **explicitly Phase 2**.
- **Log to stdout in production**, captured by `journald`. Avoid file rotation logic in app code.
- **Healthcheck distinguishes liveness from readiness:** `/healthz` (cheap, used by uptime) vs `/readyz` (deeper, checks DB+Redis; used by deploy).
- **Documentation is part of the deliverable.** Even if automation slips, the runbook must exist on day 1 so the founder knows exactly how to take/restore a backup manually.

## Requirements
**Functional — required before INTERNAL BETA**
- Documented backup runbook (`ops/docs/backup-runbook.md`) covering manual + automated paths.
- At least one successful `pg_dump` + `pg_restore` drill executed and recorded in `dr-drill-log.md`.
- `/healthz` returns app+DB+Redis status.
- `/readyz` deeper check (latest migration applied).
- Sentry receives errors with release tag.
- Structured logs to stdout in JSON; `request_id` propagated.
- Daily `pg_dump --format=custom` to local staging (cron) — off-site upload may be manual for internal beta.

**Functional — required before PUBLIC SOFT-LAUNCH**
- Automated daily off-site copy via restic (or equivalent) to encrypted object storage.
- Retention enforced: 7 daily / 4 weekly / 6 monthly.
- Daily snapshot of `/srv/exam-platform/uploads/` included off-site.
- UptimeRobot probe on `/healthz` every 5 min, alerts via email.
- Restore drill repeated within last 30 days; sign-off in `dr-drill-log.md`.

**Non-functional**
- Daily backup completes in <5 min for 200k row DB.
- Restore from off-site dump completes in <30 min.
- Log volume bounded (no per-request DEBUG in prod).

## Architecture

```
ops/
├── backup/
│   ├── pg-backup.sh                # pg_dump | restic backup
│   ├── uploads-backup.sh
│   └── restic-restore.sh           # used in drills
├── monitoring/
│   ├── healthcheck-readme.md
│   └── uptimerobot-setup.md
├── systemd/                        # Phase 11 will install
│   ├── exam-pg-backup.service
│   └── exam-pg-backup.timer
└── docs/
    ├── backup-runbook.md
    ├── restore-runbook.md
    └── dr-drill-log.md             # signed-off drill records
```

### Backup script outline
```bash
#!/usr/bin/env bash
set -euo pipefail
DATE=$(date +%F)
PGPASSWORD="$EXAM_DB_PASSWORD" pg_dump \
  --host=127.0.0.1 --username=exam_platform_user \
  --format=custom --no-owner --no-privileges \
  --file="/var/backups/postgres/exam_${DATE}.dump" \
  exam_platform_db
restic -r "$RESTIC_REPO" backup \
  --tag exam-pg --tag "${DATE}" \
  /var/backups/postgres/exam_${DATE}.dump
restic -r "$RESTIC_REPO" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
```

### Healthcheck endpoints
```python
# /healthz: cheap. ping DB with SELECT 1 (timeout 1s), redis PING (timeout 1s).
# /readyz: same plus alembic.current() == head.
```

## Related Code Files
**Create**
- `ops/backup/pg-backup.sh`, `uploads-backup.sh`, `restic-restore.sh`
- `ops/systemd/exam-pg-backup.service`, `exam-pg-backup.timer`
- `ops/docs/backup-runbook.md`, `restore-runbook.md`, `dr-drill-log.md`
- `app/routers/health.py` (extend with `/readyz`)
- `tests/test_health_routes.py`

**Modify**
- `app/logging.py` — confirm structlog JSON in prod, ensure `request_id` field present.
- `app/main.py` — Sentry init reads `RELEASE` from env (set by deploy script).

## Implementation Steps

1. **Backup script** — write `pg-backup.sh` with:
   - `pg_dump --format=custom --no-owner --no-privileges` to local staging.
   - `restic backup` to remote repo with tags.
   - `restic forget` enforces retention.
   - Logs to `/var/log/exam-backup.log`.
2. **Uploads backup** — `restic backup /srv/exam-platform/uploads/` daily.
3. **Systemd timer** — `*-backup.timer` runs at 02:30 daily; service runs script. Defer install to Phase 11.
4. **Backup runbook** — written doc: how to take ad-hoc backup, where files live, how to verify.
5. **Restore runbook** — step-by-step: `restic restore latest --target /tmp/restore` → `pg_restore --dbname=exam_platform_db_restore_test ...` → smoke test.
6. **`/readyz` endpoint** — returns 200 if DB+Redis up + migrations are at head.
7. **Sentry release tagging** — `SENTRY_RELEASE=$(git rev-parse HEAD)` set in deploy script (Phase 11). App reads on startup.
8. **Structlog config sanity** — JSON renderer in prod, `request_id` always present, log levels per env.
9. **UptimeRobot setup doc** — instructions for probing `/healthz` every 5 min from external network. Email alert.
10. **DR drill** (must execute before launch):
    - Take a backup.
    - Spin up a fresh DB on a side cluster (or namespaced DB on same cluster: `exam_platform_db_drill`).
    - Restore.
    - Run `pytest tests/smoke/` against restored DB.
    - Record outcome + timestamps in `dr-drill-log.md`.
11. **Cleanup test DB** post-drill.

## Todo List
**Required for internal beta gate**
- [ ] Backup runbook written (manual + automated paths)
- [ ] Restore runbook written
- [ ] At least one manual `pg_dump` + `pg_restore` drill executed and signed off
- [ ] `/healthz` and `/readyz` distinct
- [ ] Sentry release tagging plumbed
- [ ] Structlog JSON output verified in prod-like env
- [ ] Daily local `pg_dump` cron in place (off-site can be manual)

**Required before public soft-launch**
- [ ] `pg-backup.sh` writes encrypted off-site backup automatically
- [ ] `uploads-backup.sh` snapshots uploads folder off-site
- [ ] Systemd timer firing daily (deployed in Phase 11)
- [ ] UptimeRobot probe set up on `/healthz`
- [ ] Retention 7d/4w/6m enforced via `restic forget`
- [ ] Drill repeated within last 30 days; <30 min RTO, <24h RPO

**Phase 2 — explicitly NOT in MVP**
- Prometheus / Grafana
- WAL archiving for PITR
- Encrypted-at-rest backup of full cluster (current restic encryption sufficient for MVP)

## Success Criteria
- Daily backup runs unattended for 3 days; restic snapshots present off-site.
- `restic snapshots` shows `exam-pg` and `exam-uploads` tags daily.
- Restore drill produces a working `exam_platform_db_restore_test` containing all data within RTO target.
- `/healthz` returns 200 in <50 ms; `/readyz` returns 200 in <200 ms.
- Sentry receives a deliberately-thrown test error with `release` tag visible.
- UptimeRobot probe shows green for 24h prior to launch.

## Risk Assessment
- **Restic password loss** = backups unreadable forever. Mitigate: store password in two separate password managers + ops runbook.
- **Off-site provider outage** during disaster = both prod and backup down. Mitigate: monthly check that latest snapshot is restorable from a different network.
- **Backup script silently failing** without alerting. Mitigate: wrap in `|| (echo failure | mail -s ALERT ops)` or simpler: emit metric, alert on absence.
- **Disk fill from local backup staging** — purge after `restic backup` succeeds.

## Security Considerations
- Backup files encrypted at rest (restic AES-256).
- Off-site credentials in environment-only, not in script source.
- `pg_dump` connection over `127.0.0.1`; no network exposure.
- Restore drill DB cleaned up after — sensitive data not lingering.
- Backup script runs as a dedicated `exam-backup` system user with read-only DB role. (Optional polish; otherwise reuse `exam_platform_user`.)

## Next Steps
Phase 11 — Deployment installs systemd units, Nginx, TLS. Phase 12 — Beta launch checklist verifies all of Phase 10 in production.
