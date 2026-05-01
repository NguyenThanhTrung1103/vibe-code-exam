#!/usr/bin/env bash
# scripts/db-setup.sh
# Provisions the exam-platform role + database on an existing PG14 cluster.
# Idempotent: safe to re-run. Run as a sudoer (uses `sudo -u postgres psql`).
#
# Required env: EXAM_PLATFORM_DB_PW   (password for exam_platform_user)
# Optional env: EXAM_PLATFORM_DB_NAME (default: exam_platform_db)
#               EXAM_PLATFORM_DB_USER (default: exam_platform_user)
#
# Touches ONLY:
#   - role exam_platform_user (create if absent)
#   - database exam_platform_db (create if absent, owned by the new role)
#   - inside that DB: REVOKE PUBLIC on schema public, GRANT to the new role
#   - per-role timeouts via ALTER ROLE ... IN DATABASE ...
# Never alters template0/template1, postgres, blog, blogdb, or any global setting.

set -euo pipefail

DB_NAME="${EXAM_PLATFORM_DB_NAME:-exam_platform_db}"
DB_USER="${EXAM_PLATFORM_DB_USER:-exam_platform_user}"

if [[ -z "${EXAM_PLATFORM_DB_PW:-}" ]]; then
  echo "ERROR: EXAM_PLATFORM_DB_PW is not set." >&2
  exit 1
fi

# Hard-stop guard: refuse to run against protected names.
if [[ "$DB_NAME" == "blogdb" || "$DB_USER" == "blog" || "$DB_USER" == "postgres" ]]; then
  echo "ERROR: refusing to operate on protected names." >&2
  exit 2
fi

echo "[db_setup] target role=$DB_USER db=$DB_NAME"

# 1) Create role if absent; never alter an existing role's privileges.
#    Uses SELECT format(...) \gexec so psql variable substitution applies; this
#    is the same pattern used for the database create below. (psql vars do NOT
#    substitute inside DO $$ ... $$ dollar-quoted blocks.)
sudo -u postgres psql -v ON_ERROR_STOP=1 \
  -v db_user="$DB_USER" -v db_pw="$EXAM_PLATFORM_DB_PW" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 10',
  :'db_user', :'db_pw'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user')
\gexec
SQL

# 2) Create DB if absent. Owner = the new role. UTF-8 + C.UTF-8 (locale always
#    available on glibc; no locale-gen system change required), TEMPLATE template0.
sudo -u postgres psql -v ON_ERROR_STOP=1 \
  -v db_name="$DB_NAME" -v db_user="$DB_USER" <<'SQL'
SELECT format(
  $fmt$CREATE DATABASE %I OWNER %I ENCODING 'UTF8' LC_COLLATE 'C.UTF-8' LC_CTYPE 'C.UTF-8' TEMPLATE template0$fmt$,
  :'db_name', :'db_user'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name')
\gexec
SQL

# 3) Tighten public-schema grants inside the new DB.
sudo -u postgres psql -v ON_ERROR_STOP=1 \
  -d "$DB_NAME" -v db_user="$DB_USER" <<'SQL'
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT  ALL ON SCHEMA public TO :"db_user";
SQL

# 4) Per-role-in-this-DB safety timeouts.
sudo -u postgres psql -v ON_ERROR_STOP=1 \
  -v db_name="$DB_NAME" -v db_user="$DB_USER" <<'SQL'
ALTER ROLE :"db_user" IN DATABASE :"db_name" SET statement_timeout = '15s';
ALTER ROLE :"db_user" IN DATABASE :"db_name" SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE :"db_user" IN DATABASE :"db_name" SET lock_timeout = '5s';
SQL

# 5) Sanity-check connection as the app role over loopback.
PGPASSWORD="$EXAM_PLATFORM_DB_PW" psql -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" \
  -v ON_ERROR_STOP=1 -c "SELECT current_user, current_database(), version();"

echo "[db_setup] done."
