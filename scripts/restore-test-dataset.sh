#!/usr/bin/env bash
# Idempotent restore of the test dataset shipped under seed/test_dataset.sql.
#
# Steps:
#   1. Run alembic upgrade head (creates schema, runs seed migration 0002).
#   2. TRUNCATE the seeded tables so seed/test_dataset.sql can load without
#      primary-key collisions.
#   3. psql -f seed/test_dataset.sql.
#   4. Print row counts.
#
# Usage:
#   bash scripts/restore-test-dataset.sh                  # reads $DATABASE_URL or $DB_NAME
#   DB_NAME=mytest bash scripts/restore-test-dataset.sh   # override DB
#
# Requires:
#   - psql on PATH
#   - .venv with alembic (or uv installed)
#   - seed/test_dataset.sql present (gitignored from prod, shipped on test repo)
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SEED="${ROOT}/seed/test_dataset.sql"
DB_NAME="${DB_NAME:-exam_platform_db}"

if [[ ! -f "$SEED" ]]; then
  echo "ERROR: ${SEED} not found. Re-export from a live test DB first." >&2
  exit 2
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "ERROR: psql not on PATH. Install postgresql-client first." >&2
  exit 2
fi

echo "[restore] target DB: ${DB_NAME}"
echo "[restore] seed file: ${SEED} ($(wc -c <"$SEED") bytes)"

# 1. Migrations — alembic is idempotent; safe to run on every restore.
if [[ -x "${ROOT}/.venv/bin/alembic" ]]; then
  ALEMBIC="${ROOT}/.venv/bin/alembic"
elif command -v uv >/dev/null 2>&1; then
  ALEMBIC="uv run alembic"
else
  echo "ERROR: neither .venv/bin/alembic nor uv found." >&2
  exit 2
fi

echo "[restore] alembic upgrade head"
( cd "$ROOT" && $ALEMBIC upgrade head )

# 2. Wipe pre-seeded rows so column-insert PKs don't collide.
#    CASCADE because attempts/audit_logs reference these — they will be
#    cleared too, which is correct for a test-environment restore.
echo "[restore] truncating seeded tables (CASCADE)"
sudo -u postgres psql -v ON_ERROR_STOP=1 "${DB_NAME}" <<SQL
TRUNCATE TABLE
  source_domains,
  import_items, imports,
  question_explanations, question_options, questions,
  topics, exams, courses, product_versions, providers
RESTART IDENTITY CASCADE;
SQL

# 3. Load data.
echo "[restore] loading ${SEED}"
sudo -u postgres psql -v ON_ERROR_STOP=1 "${DB_NAME}" -f "$SEED"

# 4. Verify.
echo "[restore] row counts after load:"
sudo -u postgres psql -t -A -F'|' "${DB_NAME}" <<'SQL'
SELECT 'providers',            COUNT(*) FROM providers
UNION ALL SELECT 'product_versions',     COUNT(*) FROM product_versions
UNION ALL SELECT 'courses',              COUNT(*) FROM courses
UNION ALL SELECT 'exams',                COUNT(*) FROM exams
UNION ALL SELECT 'topics',               COUNT(*) FROM topics
UNION ALL SELECT 'questions',            COUNT(*) FROM questions
UNION ALL SELECT 'question_options',     COUNT(*) FROM question_options
UNION ALL SELECT 'question_explanations',COUNT(*) FROM question_explanations
UNION ALL SELECT 'imports',              COUNT(*) FROM imports
UNION ALL SELECT 'import_items',         COUNT(*) FROM import_items
UNION ALL SELECT 'source_domains',       COUNT(*) FROM source_domains;
SQL

echo "[restore] done. Create a test admin: see docs/restore-test-environment.md step 7."
