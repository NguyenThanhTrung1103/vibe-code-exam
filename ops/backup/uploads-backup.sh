#!/usr/bin/env bash
# Phase 10 — uploads snapshot script.
#
# Snapshots /srv/exam-platform/uploads/ to restic. Idempotent:
# restic-internal dedup keeps the actual storage cost flat.
set -Eeuo pipefail

LOG="/var/log/exam-backup.log"
SRC="${EXAM_UPLOADS_DIR:-/srv/exam-platform/uploads}"

log() { printf '%s [exam-uploads-backup] %s\n' "$(date -u --iso-8601=seconds)" "$*" | tee -a "$LOG"; }
trap 'log "FAIL: line $LINENO exit $?"' ERR

if [[ ! -d "$SRC" ]]; then
  log "skip: $SRC missing"
  exit 0
fi

if [[ -z "${RESTIC_REPO:-}" ]]; then
  log "RESTIC_REPO unset — skipping (uploads stay local at $SRC)"
  exit 0
fi

: "${RESTIC_PASSWORD_FILE:=/root/.config/restic-pw}"
export RESTIC_REPO RESTIC_PASSWORD_FILE
log "restic backup → $SRC"
restic backup --tag exam-uploads "$SRC"
log "OK"
