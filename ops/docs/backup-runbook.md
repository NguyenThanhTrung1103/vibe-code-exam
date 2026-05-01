# Backup Runbook (Phase 10)

## What gets backed up
- **`exam_platform_db`** (PostgreSQL 14, custom-format `pg_dump`).
- **`/srv/exam-platform/uploads/`** (admin-uploaded XLSX files, restic snapshot).

`blogdb` and `/srv/blog-website/` are explicitly **out of scope** for the
exam-platform backup. They have their own backup story owned by the blog.

## Where it lives
| Stage | Location | Encryption | Retention |
|-------|----------|------------|-----------|
| Local staging | `/var/backups/postgres/exam_<UTC-stamp>.dump` | none (local-only) | until the next successful off-site upload purges it |
| Off-site | `restic` repo at `$RESTIC_REPO` | AES-256 (restic native) | 7 daily / 4 weekly / 6 monthly via `restic forget` |

Off-site restic is **required for public soft-launch (Gate B)** and
**optional for internal beta (Gate A)** — the runbook still applies for
Gate A, but the local dump alone can satisfy the gate.

## Manual ad-hoc backup

```bash
sudo -i
source /srv/exam-platform/.env       # provides EXAM_DB_PASSWORD, RESTIC_REPO, RESTIC_PASSWORD_FILE
/srv/exam-platform/ops/backup/pg-backup.sh
```

The script logs to `/var/log/exam-backup.log`. Verify last 20 lines:

```bash
tail -20 /var/log/exam-backup.log
```

Verify the local dump file:

```bash
ls -la /var/backups/postgres/ | tail -5
file /var/backups/postgres/exam_*.dump      # should report "PostgreSQL custom database dump"
```

If `RESTIC_REPO` is set, verify the off-site snapshot landed:

```bash
restic snapshots --tag exam-pg --latest 1
```

## Automated daily backup (Phase 11 installs the timer)

The systemd unit ships in `ops/systemd/`. Phase 11 places them in
`/etc/systemd/system/` and enables the timer:

```bash
systemctl daemon-reload
systemctl enable --now exam-pg-backup.timer
systemctl list-timers | grep exam-pg-backup
```

Check the most recent run:

```bash
systemctl status exam-pg-backup.service
journalctl -u exam-pg-backup.service --since today
```

## Required environment variables

```dotenv
EXAM_DB_HOST=127.0.0.1
EXAM_DB_USER=exam_platform_user
EXAM_DB_NAME=exam_platform_db
EXAM_DB_PASSWORD=<vault>

# Off-site (optional for Gate A; required for Gate B):
RESTIC_REPO=s3:s3.eu-central-1.example.com/exam-platform-backup
RESTIC_PASSWORD_FILE=/root/.config/restic-pw
AWS_ACCESS_KEY_ID=<vault>
AWS_SECRET_ACCESS_KEY=<vault>
```

## Safety guarantees built into the script

- Refuses to dump anything other than `exam_platform_db*` (`if` guard).
- Connects only over `127.0.0.1`.
- Never runs `dropdb`, `truncate`, or any `psql` against the live DB.
- Writes its log via `tee` so a failed `set -e` exit still leaves a trail.

## Recovery time / point objectives (target)

| Metric | Target | Notes |
|--------|--------|-------|
| RPO | ≤ 24 h | daily 02:30 UTC backup |
| RTO | ≤ 30 min | restore drill is timed; see `restore-runbook.md` |

## Failure modes & alerts

- **Script exits non-zero** → systemd records `failed` state; pair with a
  watchdog (UptimeRobot, healthcheck.io) that fires when the daily
  expected ping is missing.
- **Disk fills** → off-site upload step removes the local dump after a
  successful `restic backup`; add `df -h /var/backups/postgres` to
  weekly checks.
- **Restic password loss** → backups become unreadable forever. Store
  the password in **two** independent vaults; add a quarterly drill to
  prove the off-site snapshot can be opened from a fresh host.
