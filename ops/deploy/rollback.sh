#!/usr/bin/env bash
# Phase 11 — rollback helper.
#
# Reverts /srv/exam-platform/app to a previous git ref or snapshot. By
# default it expects the operator to have a known-good source path
# (default: /srv/exam-platform-dev) — Phase 12 may add a release-symlink
# strategy. Until then this is a "stop-the-bleeding" script.
set -Eeuo pipefail

PREV="${1:-/srv/exam-platform-dev}"   # path containing the known-good app/
ROOT="/srv/exam-platform"
LOG="/var/log/exam-deploy.log"

log() { printf '%s [exam-rollback] %s\n' "$(date -u --iso-8601=seconds)" "$*" | tee -a "$LOG"; }
trap 'log "FAIL: line $LINENO exit $?"' ERR

if [[ "$EUID" -ne 0 ]]; then
  log "must run as root"
  exit 2
fi

if [[ ! -d "$PREV/app" ]]; then
  log "rollback source $PREV/app not found"
  exit 3
fi

log "stopping service"
systemctl stop exam-platform-web.service || true

log "rsync $PREV/app → $ROOT/app"
rsync -a --delete --exclude=__pycache__ "$PREV/app/" "$ROOT/app/"
rsync -a --delete "$PREV/migrations/"   "$ROOT/migrations/"
chown -R exam-platform:exam-platform "$ROOT/app" "$ROOT/migrations"

# Optional: downgrade migrations if the rollback target had an earlier head.
# Operator decides — auto-downgrade is risky. Document only.
log "WARNING: alembic downgrade is NOT auto-run; review migrations/versions/ manually"

log "starting service"
systemctl start exam-platform-web.service
sleep 2

curl -sS -o /dev/null -w "healthz: %{http_code}\n" http://127.0.0.1:8001/healthz | tee -a "$LOG"
log "rollback OK"
