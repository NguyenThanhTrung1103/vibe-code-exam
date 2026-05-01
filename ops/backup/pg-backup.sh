#!/usr/bin/env bash
# Phase 10 — exam_platform_db backup script.
#
# Writes a custom-format pg_dump to a local staging dir and (when
# RESTIC_REPO is set) ships it off-site via restic with retention.
# Designed for use by the systemd timer installed in Phase 11.
#
# Required env (sourced from /srv/exam-platform/.env on the LXC):
#   EXAM_DB_HOST=127.0.0.1
#   EXAM_DB_USER=exam_platform_user
#   EXAM_DB_NAME=exam_platform_db
#   EXAM_DB_PASSWORD=...                 # only for pg_dump
# Optional:
#   PG_BACKUP_STAGING=/var/backups/postgres
#   RESTIC_REPO=                         # if empty, skip off-site upload
#   RESTIC_PASSWORD_FILE=/root/.config/restic-pw
#
# Hard rule: this script ONLY targets exam_platform_db. blogdb is never
# referenced. Safe to run on the shared PG14 cluster.
set -Eeuo pipefail

DATE="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
LOG="/var/log/exam-backup.log"
STAGING="${PG_BACKUP_STAGING:-/var/backups/postgres}"
mkdir -p "$STAGING"

log() { printf '%s [exam-pg-backup] %s\n' "$(date -u --iso-8601=seconds)" "$*" | tee -a "$LOG"; }

trap 'log "FAIL: line $LINENO exit $?"' ERR

: "${EXAM_DB_HOST:=127.0.0.1}"
: "${EXAM_DB_USER:=exam_platform_user}"
: "${EXAM_DB_NAME:=exam_platform_db}"
: "${EXAM_DB_PASSWORD:?EXAM_DB_PASSWORD must be set}"

if [[ "$EXAM_DB_NAME" != "exam_platform_db"* ]]; then
  log "REFUSE: EXAM_DB_NAME is not exam_platform_db*"
  exit 2
fi

OUT="$STAGING/exam_${DATE}.dump"
log "starting pg_dump → $OUT"
PGPASSWORD="$EXAM_DB_PASSWORD" pg_dump \
  --host="$EXAM_DB_HOST" \
  --username="$EXAM_DB_USER" \
  --format=custom \
  --no-owner --no-privileges \
  --file="$OUT" \
  "$EXAM_DB_NAME"
log "pg_dump done ($(du -h "$OUT" | cut -f1))"

if [[ -n "${RESTIC_REPO:-}" ]]; then
  : "${RESTIC_PASSWORD_FILE:=/root/.config/restic-pw}"
  export RESTIC_REPO RESTIC_PASSWORD_FILE
  log "restic backup → $RESTIC_REPO"
  restic backup --tag exam-pg --tag "$DATE" "$OUT"
  log "restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6"
  restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
  rm -f "$OUT"
  log "off-site copy complete; local staging removed"
else
  log "RESTIC_REPO unset — staying local-only"
fi

log "OK"
