#!/usr/bin/env bash
# Phase 11 — one-time bootstrap on a fresh LXC.
#
# Idempotent. Re-runnable. Does NOT touch Nginx, cloudflared, or any
# blog files. Does NOT enable certbot. Binds the app on 127.0.0.1:8001.
set -Eeuo pipefail

LOG="/var/log/exam-install.log"
ROOT="/srv/exam-platform"

log() { printf '%s [exam-install] %s\n' "$(date -u --iso-8601=seconds)" "$*" | tee -a "$LOG"; }
trap 'log "FAIL: line $LINENO exit $?"' ERR

if [[ "$EUID" -ne 0 ]]; then
  log "must run as root"
  exit 2
fi

# 1. System user
if ! id exam-platform >/dev/null 2>&1; then
  log "creating exam-platform system user"
  useradd --system --shell /usr/sbin/nologin --home-dir "$ROOT" exam-platform
fi

# 2. Dirs
mkdir -p "$ROOT/app" "$ROOT/ops" "$ROOT/logs" "$ROOT/uploads" /var/backups/postgres
chown exam-platform:exam-platform "$ROOT/app" "$ROOT/logs" "$ROOT/uploads"
chmod 750 "$ROOT"

# 3. Source + venv (delegate to deploy.sh — idempotent)
"$ROOT/ops/deploy/deploy.sh" main || {
  # If deploy.sh isn't present yet (truly fresh LXC), the operator must
  # rsync the source first. Documented in deployment-runbook.md.
  log "deploy.sh missing or failed — copy /srv/exam-platform-dev → /srv/exam-platform first"
  exit 3
}

# 4. systemd units (web + backup timer from Phase 10).
log "installing systemd units"
cp -f "$ROOT/ops/systemd/exam-platform-web.service" /etc/systemd/system/
cp -f "$ROOT/ops/systemd/exam-pg-backup.service"   /etc/systemd/system/
cp -f "$ROOT/ops/systemd/exam-pg-backup.timer"     /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now exam-platform-web.service
systemctl enable --now exam-pg-backup.timer

# 5. Verify.
sleep 2
systemctl is-active exam-platform-web.service
systemctl is-active exam-pg-backup.timer
curl -sS -o /dev/null -w "healthz: %{http_code}\n" http://127.0.0.1:8001/healthz

log "install OK — app on 127.0.0.1:8001 (loopback only)"
log "next: review ops/nginx/exam-platform.conf and Phase 12 readiness checklist before any public exposure"
