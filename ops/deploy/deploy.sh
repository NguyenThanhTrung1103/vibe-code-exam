#!/usr/bin/env bash
# Phase 11 — idempotent deploy script.
#
# Usage:
#   sudo /srv/exam-platform/ops/deploy/deploy.sh [git-ref]
#
# Pulls the requested ref into /srv/exam-platform/app, refreshes the
# venv, runs migrations, restarts the systemd unit. Loopback-only —
# does NOT touch Nginx or cloudflared.
set -Eeuo pipefail

REF="${1:-main}"
ROOT="/srv/exam-platform"
LOG="/var/log/exam-deploy.log"

log() { printf '%s [exam-deploy] %s\n' "$(date -u --iso-8601=seconds)" "$*" | tee -a "$LOG"; }
trap 'log "FAIL: line $LINENO exit $?"' ERR

if [[ "$EUID" -ne 0 ]]; then
  log "must run as root"
  exit 2
fi

# 1. Update source via rsync from /srv/exam-platform-dev (dev push pattern).
#    Replace this block with `git fetch && git checkout` once a real git
#    remote exists on the LXC. Loopback-only path; never reaches GitHub.
log "syncing app/ migrations/ ops/ from /srv/exam-platform-dev"
rsync -a --delete --exclude=__pycache__ --exclude=.pytest_cache \
  --exclude=.ruff_cache --exclude=.mypy_cache \
  /srv/exam-platform-dev/app/ "$ROOT/app/"
rsync -a --delete /srv/exam-platform-dev/migrations/ "$ROOT/migrations/"
rsync -a --delete /srv/exam-platform-dev/ops/ "$ROOT/ops/"
cp -f /srv/exam-platform-dev/alembic.ini "$ROOT/alembic.ini"
cp -f /srv/exam-platform-dev/pyproject.toml "$ROOT/pyproject.toml"
cp -f /srv/exam-platform-dev/uv.lock "$ROOT/uv.lock"
chmod +x "$ROOT/ops/backup/"*.sh "$ROOT/ops/deploy/"*.sh
chown -R exam-platform:exam-platform "$ROOT/app" "$ROOT/migrations" "$ROOT/ops"

# 2. Refresh deps (uv pip is idempotent; quick if no new packages).
log "refreshing venv"
/root/.local/bin/uv pip install --python "$ROOT/.venv/bin/python" -e "$ROOT" >>"$LOG" 2>&1
chown -R exam-platform:exam-platform "$ROOT/.venv"

# 3. Migrations.
log "alembic upgrade head"
( cd "$ROOT" && "$ROOT/.venv/bin/alembic" upgrade head 2>&1 | tee -a "$LOG" ) || {
  log "alembic failed — NOT restarting service"
  exit 3
}

# 4. Stamp release for Sentry.
echo "APP_RELEASE=$(date -u +%Y%m%dT%H%M%SZ)-$REF" >>"$ROOT/.env"

# 5. Restart unit (graceful — Restart=on-failure means the new process
#    starts cleanly).
log "restarting exam-platform-web.service"
systemctl restart exam-platform-web.service
sleep 2

# 6. Smoke probes.
for ep in /healthz /readyz; do
  STATUS=$(curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:8001${ep}" || echo "000")
  log "probe ${ep}: HTTP ${STATUS}"
  [[ "$STATUS" == "200" ]] || { log "probe failed — investigate"; exit 4; }
done

log "deploy OK ($REF)"
