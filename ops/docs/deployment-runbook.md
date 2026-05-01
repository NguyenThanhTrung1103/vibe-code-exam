# Deployment Runbook (Phase 11)

## What Phase 11 ships

| Component | Where | Status after Phase 11 |
|-----------|-------|------------------------|
| `exam-platform` system user (uid 999, no shell) | LXC | created |
| `/srv/exam-platform/{app,migrations,ops,uploads,logs}` | LXC | provisioned |
| `/srv/exam-platform/.venv` (Python 3.12) | LXC | created with all deps |
| `/srv/exam-platform/.env` | LXC | placed `640 root:exam-platform` |
| `exam-platform-web.service` (systemd) | `/etc/systemd/system/` | enabled + running |
| `exam-pg-backup.service` + `.timer` | `/etc/systemd/system/` | enabled + scheduled (02:30 UTC) |
| App listening port | `127.0.0.1:8001` | loopback only |
| Public Nginx vhost / TLS / DNS | NOT installed | Phase 12 gate |

## What Phase 11 explicitly does NOT do

- **No** Nginx vhost installed. Template is at
  `/srv/exam-platform/ops/nginx/exam-platform.conf` for Phase 12 review.
- **No** certbot run. Plan-approved domain `exam.example.com` not real.
- **No** cloudflared change.
- **No** UFW rule change.
- **No** blog touch (`/srv/blog-website`, `blog.service`, `blogdb`,
  blog Nginx routes).
- **No** PostgreSQL config change (`pg_hba.conf` / `postgresql.conf`).
- **No** Redis config change.

## Day-to-day operations

### Status

```bash
systemctl status exam-platform-web.service
systemctl status exam-pg-backup.timer
journalctl -u exam-platform-web.service -n 50 --no-pager
curl -sS http://127.0.0.1:8001/healthz
curl -sS http://127.0.0.1:8001/readyz
```

### Deploy a new version

```bash
# Push the new code to /srv/exam-platform-dev (the dev tree) first via
# tar | ssh from the developer workstation. Then on the LXC:
sudo /srv/exam-platform/ops/deploy/deploy.sh main
```

`deploy.sh`:
1. rsyncs `/srv/exam-platform-dev/{app,migrations,ops}` → `/srv/exam-platform/`.
2. Refreshes `.venv` via `uv pip install -e .`.
3. Runs `alembic upgrade head` (aborts on failure — service is **not** restarted).
4. Stamps `APP_RELEASE` into `.env` for Sentry.
5. `systemctl restart exam-platform-web.service`.
6. Smoke probes `/healthz` and `/readyz`.

### Rollback

```bash
sudo /srv/exam-platform/ops/deploy/rollback.sh /path/to/known-good
```

Migrations are **not** auto-downgraded. The operator must inspect
`migrations/versions/` and decide if a downgrade is safe. Most
forward-only migrations should not be downgraded; the right move for a
breaking change is "fix forward" or restore from the most recent `pg_dump`
into a drill DB and swap.

### Stop / start / restart

```bash
sudo systemctl stop    exam-platform-web.service
sudo systemctl start   exam-platform-web.service
sudo systemctl restart exam-platform-web.service
```

### Logs

* App stdout/stderr → `journalctl -u exam-platform-web.service`.
* Backup script → `/var/log/exam-backup.log` (rotated by
  `/etc/logrotate.d/exam-platform`).
* Deploy/rollback → `/var/log/exam-deploy.log`.
* Install (one-time) → `/var/log/exam-install.log`.

### Environment variables

The app reads `.env` via pydantic-settings. Required keys for the
loopback build:

```dotenv
DATABASE_URL=postgresql+psycopg://exam_platform_user:<pw>@127.0.0.1:5432/exam_platform_db
REDIS_URL=redis://127.0.0.1:6379/0
SECRET_KEY=<random>
SESSION_COOKIE_NAME=exam_session
ENV=local
DEBUG=false
LOG_LEVEL=INFO
APP_HOST=127.0.0.1
APP_PORT=8001
UPLOADS_DIR=/srv/exam-platform/uploads
SENTRY_DSN=          # optional
SENTRY_RELEASE=      # auto-stamped by deploy.sh
```

### Security guarantees

- App runs as **non-root, non-www-data** `exam-platform` user.
- systemd unit hardening: `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome=yes`, `PrivateTmp=yes`, `ProtectKernelTunables/Modules/ControlGroups`,
  `RestrictNamespaces/Realtime`, `MemoryDenyWriteExecute`.
- Read-write paths limited to `/srv/exam-platform/uploads` and
  `/srv/exam-platform/logs`.
- Bind 127.0.0.1 only — not reachable from outside the LXC.

## Smoke checklist (after `deploy.sh` / `install.sh`)

- [ ] `systemctl is-active exam-platform-web.service` → `active`.
- [ ] `systemctl is-active exam-pg-backup.timer` → `active`.
- [ ] `curl http://127.0.0.1:8001/healthz` → 200 `{db:ok,redis:ok}`.
- [ ] `curl http://127.0.0.1:8001/readyz` → 200 with alembic head match.
- [ ] `journalctl -u exam-platform-web.service` shows no `unhandled_exception`.
- [ ] `ls /etc/systemd/system/exam-*` lists the three units.
- [ ] Blog stack still reachable at its existing URL (curl loopback
      to the blog gunicorn on `:8000` — should answer with HTTP 200).
- [ ] `systemctl is-active blog.service postgresql redis-server nginx cloudflared` → 5× active.

## Phase 12 readiness gates (NOT in Phase 11)

To take the app public the operator must:

1. Acquire/configure DNS `exam.example.com` → LXC public IP.
2. Review and install `ops/nginx/exam-platform.conf`.
3. `nginx -t` (must pass — confirms blog vhost unaffected).
4. `certbot --nginx -d exam.example.com` to issue TLS.
5. Update systemd unit's `--host/--port` to a unix socket (or keep
   loopback TCP and have Nginx proxy to it; either works).
6. Verify Phase 09 security headers from outside the LXC.
7. Confirm Phase 10 Gate B (off-site restic + UptimeRobot).
