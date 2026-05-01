---
phase: 11
title: Deployment on Ubuntu LXC with Nginx + systemd
status: pending
effort: 2-3 days
priority: high
depends_on: [09, 10]
---

# Phase 11 — Deployment on Ubuntu 22.04 LXC

## Context Links
- PRD §29 (tech stack), §27 (backup posture), prior conversation on PG14 co-tenancy
- Existing: blog at `/srv/blog-website` already on this LXC; PG14 already serving blog DB

## Overview
Deploy the FastAPI app at `/srv/exam-platform/`, run via systemd-managed Gunicorn (uvicorn workers), Nginx reverse proxy on a new subdomain, TLS via Certbot, install Phase 10's backup timer, configure logrotate, harden the LXC perimeter, document the deploy script. Coexists with the blog without disruption.

## Key Insights
- **Coexistence with the blog** is the whole point. New app gets its own systemd unit, its own Gunicorn socket, its own Nginx vhost. PG14 stays shared per the prior co-tenancy decision.
- **Subdomain over path** — `exam.example.com` rather than `example.com/exam`. Cleaner cookies (no path scoping issues), independent TLS, easier Nginx config.
- **Run as a dedicated system user** `exam-platform` (not `root`, not `www-data`). Owns `/srv/exam-platform/`. systemd `User=exam-platform`.
- **Gunicorn over a Unix socket**, not TCP. Nginx → socket avoids port-allocation conflicts and reduces attack surface.
- **No Docker in production** at MVP — adds complexity for no benefit at this scale. Direct systemd is simpler to operate.
- **Deploy is `git pull && reload`** — no Kubernetes, no Ansible at MVP. A bash deploy script is enough.
- **Firewall** — UFW already active on the LXC (likely; verify). Allow 80/443 only from outside.

## Requirements
**Functional**
- App reachable at `https://exam.example.com/`.
- HTTPS-only with HSTS in prod (Phase 09 header gated on ENV=prod).
- Static files served by Nginx directly.
- Healthcheck reachable internally; UptimeRobot probes externally.
- Backup timer + service installed and running.
- Deploy script (zero-downtime within reason) — `git pull → install deps → migrate → reload`.

**Non-functional**
- Cold start <5 s.
- Reload (graceful) under 2 s with no dropped requests.
- Resource budget: 2 CPU, 1 GB RAM allocated to exam-platform Gunicorn workers (3 workers).

## Architecture

```
/srv/exam-platform/
├── app/                              # code (cloned from git)
├── .venv/                            # python venv
├── .env                              # production env (root:exam-platform 640)
├── uploads/imports/                  # admin upload retention
├── current → /srv/exam-platform/releases/<sha>/   # symlink-style deploys (optional)
└── logs/                             # journald owns most logging; this is overflow

/etc/systemd/system/
├── exam-platform-web.service         # Gunicorn web
├── exam-platform-worker.service      # RQ worker (Phase 2 use; idle now)
├── exam-pg-backup.service            # from Phase 10
└── exam-pg-backup.timer

/etc/nginx/sites-available/
└── exam-platform.conf                # vhost

/etc/letsencrypt/                     # Certbot
```

### systemd unit (web) — illustrative
```ini
[Unit]
Description=Exam Platform — Gunicorn
After=network.target postgresql.service

[Service]
Type=notify
User=exam-platform
Group=exam-platform
WorkingDirectory=/srv/exam-platform
EnvironmentFile=/srv/exam-platform/.env
ExecStart=/srv/exam-platform/.venv/bin/gunicorn \
  app.main:app \
  --workers 3 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind unix:/run/exam-platform/web.sock \
  --umask 007 \
  --access-logfile - \
  --error-logfile -
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/srv/exam-platform/uploads /srv/exam-platform/logs /run/exam-platform
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

### Nginx vhost — illustrative
```nginx
server {
    listen 80;
    server_name exam.example.com;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl http2;
    server_name exam.example.com;
    ssl_certificate     /etc/letsencrypt/live/exam.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/exam.example.com/privkey.pem;
    client_max_body_size 30M;

    location /static/ {
        alias /srv/exam-platform/app/static/;
        access_log off;
        expires 7d;
    }

    location / {
        proxy_pass http://unix:/run/exam-platform/web.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;
        proxy_read_timeout 60s;
    }
}
```

### Trusted proxy + app behavior
- Nginx terminates TLS and sets **`X-Forwarded-Proto $scheme`**, **`X-Forwarded-For`** (via `proxy_add_x_forwarded_for`), and **`Host`**. Gunicorn receives requests over the unix socket from **localhost only** — forwarded headers are thus **originally set by Nginx**, not by the end user.
- The FastAPI app (Phase 09) must use **`ProxyHeadersMiddleware`** (or Uvicorn `--forwarded-allow-ips` if applicable) with a **strict allowlist** (e.g. only the unix socket / 127.0.0.1) so **HTTPS detection, secure session cookies, and IP-based rate limits** are correct. Do not accept `X-Forwarded-*` from untrusted direct connections.
- Verify after deploy: `curl -I https://exam.example.com/` shows **HSTS**; login sets **Secure** cookie; rate limit sees **real client IP** from `X-Forwarded-For` chain as configured.

## Related Code Files
**Create**
- `ops/systemd/exam-platform-web.service`
- `ops/systemd/exam-platform-worker.service`
- `ops/nginx/exam-platform.conf`
- `ops/deploy/deploy.sh`        # idempotent deploy
- `ops/deploy/install.sh`       # one-time bootstrap
- `ops/deploy/rollback.sh`
- `ops/logrotate/exam-platform`
- `ops/docs/deployment-runbook.md`

## Implementation Steps

1. **Create system user**: `sudo useradd --system --home /srv/exam-platform --shell /usr/sbin/nologin exam-platform`.
2. **Install OS deps**: `python3.12 python3.12-venv build-essential libpq-dev nginx certbot python3-certbot-nginx ufw restic`.
3. **Provision directories**: `/srv/exam-platform/`, `/run/exam-platform/` (tmpfiles), `/var/backups/postgres/`, owner `exam-platform:exam-platform`.
4. **Provision DB** (one-time) — run `scripts/db_setup.sh` from Phase 02 on the existing PG14 cluster.
5. **Clone repo + venv** — `git clone … /srv/exam-platform/app && cd app && python3.12 -m venv ../.venv && ../.venv/bin/pip install -r requirements.lock`.
6. **Place `.env`** — populated production secrets (DB password, SECRET_KEY, SENTRY_DSN, RESTIC_REPO, RESTIC_PASSWORD, off-site creds). Permissions `640 root:exam-platform`.
7. **Run migrations**: `cd /srv/exam-platform/app && ../.venv/bin/alembic upgrade head`.
8. **Install systemd units** — `exam-platform-web.service`, `exam-platform-worker.service` (worker idle in Phase 1), backup units from Phase 10. `daemon-reload` + `enable --now`.
9. **Install Nginx vhost** — `/etc/nginx/sites-available/exam-platform.conf`, symlink to `sites-enabled`, `nginx -t && systemctl reload nginx`.
10. **TLS** — `certbot --nginx -d exam.example.com`. Auto-renew via certbot's systemd timer.
11. **Configure UFW** — confirm 22 (admin SSH or Tailscale), 80, 443 open; deny inbound everything else.
12. **Logrotate** — `/etc/logrotate.d/exam-platform` for backup logs (journald handles app).
13. **Tmpfiles** — `/etc/tmpfiles.d/exam-platform.conf`: `d /run/exam-platform 0750 exam-platform exam-platform -`.
14. **Deploy script** (`deploy.sh`):
    ```bash
    set -euo pipefail
    cd /srv/exam-platform/app
    sudo -u exam-platform git fetch --all
    sudo -u exam-platform git checkout "$1"   # tag or sha
    sudo -u exam-platform ../.venv/bin/pip install -r requirements.lock
    sudo -u exam-platform ../.venv/bin/alembic upgrade head
    sudo systemctl reload exam-platform-web.service
    ```
15. **Rollback script** — checkout previous SHA, downgrade migrations only if reversible.
16. **Smoke after deploy** — curl `/readyz`, `/healthz`, `/`. Document expected responses.
17. **Run Phase 10 DR drill** in production once everything is up; sign off.
18. **Document everything** in `deployment-runbook.md` (include known-good URLs, common failures, log locations).

## Todo List
- [ ] `exam-platform` system user + dirs created
- [ ] OS dependencies installed
- [ ] PG14 co-tenant DB + role provisioned (one-time)
- [ ] App deployed to /srv/exam-platform/app
- [ ] Production `.env` placed with correct permissions
- [ ] Alembic migrations applied
- [ ] systemd web service running, restarts on failure
- [ ] systemd worker service installed (idle in Phase 1)
- [ ] Backup timer + service installed and firing daily
- [ ] Nginx vhost live, TLS issued by Certbot, auto-renew confirmed
- [ ] UFW: 22/80/443 only inbound
- [ ] Logrotate configured for backup log
- [ ] `deploy.sh` and `rollback.sh` work and documented
- [ ] DR drill from Phase 10 executed in production
- [ ] Smoke tests pass post-deploy
- [ ] Deployment runbook written

## Success Criteria
- Browser hitting `https://exam.example.com/` returns the home page over HTTPS with HSTS header.
- `systemctl status exam-platform-web` shows running, no restarts in last 24h.
- `systemctl list-timers` shows backup timer scheduled.
- Blog at its existing domain is unaffected (regression check).
- Re-running `deploy.sh` is idempotent (no errors).
- TLS certificate renewable (`certbot renew --dry-run` passes).
- Restore drill in production succeeds within RTO target.

## Risk Assessment
- **Touching shared PG14 cluster** during deployment risks blog impact. Mitigation: only run `db_setup.sh` once, never on subsequent deploys; `alembic upgrade head` only touches exam DB.
- **Nginx misconfig** could break blog vhost. Mitigation: separate `sites-available/` files; test with `nginx -t` before reload.
- **Memory pressure** if Gunicorn workers swell. Mitigation: 3 workers * ~150MB each fits in 1GB; monitor with `systemd-cgtop` early.
- **Forgotten secrets** in `.env` can crash startup. Mitigation: `pydantic-settings` raises on startup with clear messages.

## Security Considerations
- App runs as **non-root, non-www-data** user; cannot read blog's files.
- systemd hardening: `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp=yes`, restricted `ReadWritePaths`.
- `.env` permissions `640 root:exam-platform`.
- Postgres bound to `127.0.0.1`; LXC firewall blocks external 5432.
- HTTPS forced; HSTS on; HTTP redirects to HTTPS.
- `client_max_body_size 30M` matches Phase 05 upload cap (allow some headroom).
- Trusted proxy header config: `X-Forwarded-For` only honored from Nginx via `ProxyHeaders`.
- Recommend `fail2ban` for SSH (separate config).
- Admin can SSH via Tailscale only (recommended) — public SSH is the largest residual risk if password auth left enabled.

## Next Steps
Phase 12 — Seed content, run beta, exit-gate the production-readiness checklist.
