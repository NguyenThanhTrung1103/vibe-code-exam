#!/usr/bin/env bash
# Phase 10 — restore helper used in the DR drill.
#
# Usage:
#   ops/backup/restic-restore.sh [snapshot-id-or-latest] [target-dir]
#
# Restores the most recent (or specified) snapshot to a TARGET dir, then
# pg_restore-s it into a separate database (default: exam_platform_db_drill).
# Never restores over the live exam_platform_db.
set -Eeuo pipefail

SNAP="${1:-latest}"
TARGET="${2:-/tmp/exam-restore-$(date -u +%Y%m%d%H%M%S)}"
DRILL_DB="${EXAM_DRILL_DB:-exam_platform_db_drill}"

log() { printf '%s [exam-restore] %s\n' "$(date -u --iso-8601=seconds)" "$*"; }

if [[ "$DRILL_DB" == "exam_platform_db" ]]; then
  log "REFUSE: drill DB cannot equal live DB"
  exit 2
fi
if [[ "$DRILL_DB" == "blogdb" ]]; then
  log "REFUSE: drill DB cannot equal blogdb"
  exit 2
fi

: "${EXAM_DB_HOST:=127.0.0.1}"
: "${EXAM_DB_USER:=exam_platform_user}"
: "${EXAM_DB_PASSWORD:?EXAM_DB_PASSWORD must be set}"

mkdir -p "$TARGET"

if [[ -n "${RESTIC_REPO:-}" ]]; then
  : "${RESTIC_PASSWORD_FILE:=/root/.config/restic-pw}"
  export RESTIC_REPO RESTIC_PASSWORD_FILE
  log "restic restore $SNAP --target $TARGET"
  restic restore "$SNAP" --target "$TARGET" --tag exam-pg
  DUMP="$(find "$TARGET" -name 'exam_*.dump' -type f | sort | tail -n1)"
else
  # Local-only: take the most recent staging dump.
  STAGING="${PG_BACKUP_STAGING:-/var/backups/postgres}"
  DUMP="$(find "$STAGING" -maxdepth 1 -name 'exam_*.dump' -type f | sort | tail -n1)"
fi

if [[ -z "${DUMP:-}" || ! -f "$DUMP" ]]; then
  log "no dump found"
  exit 3
fi

log "restoring $DUMP → $DRILL_DB"
# `exam_platform_user` does NOT have CREATEDB — the operator must
# pre-create the drill database with the postgres superuser before
# invoking this script:
#
#   sudo -u postgres createdb -O exam_platform_user exam_platform_db_drill
#
# (cleanup at the end is symmetric: `sudo -u postgres dropdb`).
EXISTS=$(PGPASSWORD="$EXAM_DB_PASSWORD" psql --host="$EXAM_DB_HOST" --username="$EXAM_DB_USER" \
  --dbname=postgres --quiet -tAc "SELECT 1 FROM pg_database WHERE datname='$DRILL_DB';" || true)
if [[ "$EXISTS" != "1" ]]; then
  log "REFUSE: $DRILL_DB does not exist. Run:"
  log "  sudo -u postgres createdb -O $EXAM_DB_USER $DRILL_DB"
  exit 4
fi
PGPASSWORD="$EXAM_DB_PASSWORD" pg_restore \
  --host="$EXAM_DB_HOST" --username="$EXAM_DB_USER" \
  --dbname="$DRILL_DB" --no-owner --no-privileges --clean --if-exists \
  "$DUMP" || true   # pg_restore reports warnings as exit 1 even on success
log "restore done"

# Smoke probes
PGPASSWORD="$EXAM_DB_PASSWORD" psql --host="$EXAM_DB_HOST" --username="$EXAM_DB_USER" \
  --dbname="$DRILL_DB" --quiet -tAc "SELECT count(*) FROM users;" \
  | awk '{print "users count: "$1}'
PGPASSWORD="$EXAM_DB_PASSWORD" psql --host="$EXAM_DB_HOST" --username="$EXAM_DB_USER" \
  --dbname="$DRILL_DB" --quiet -tAc "SELECT count(*) FROM alembic_version;" \
  | awk '{print "alembic_version rows: "$1}'

log "drill OK; drop with: dropdb -h $EXAM_DB_HOST -U $EXAM_DB_USER $DRILL_DB"
