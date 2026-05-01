---
phase: 02
title: Database migrations & PostgreSQL co-tenant setup
status: completed
completed_at: 2026-04-29
effort: 2-3 days
priority: high
depends_on: [01]
---

# Phase 02 — Database Migrations & Postgres Co-Tenant Setup

## Context Links
- PRD §7 (full v2 schema), §27 (backup posture), prior conversation on PG14 co-tenancy
- Phase 01 (`app/db.py`) must be in place
- Existing infra: PG14 already serving `blog_db` on `/srv/blog-website`

## Overview
Provision the new database (`exam_platform_db`) and role (`exam_platform_user`) on the existing PG14 cluster. Set up Alembic. Land the full v2 schema in one or two migrations — including tables Phase 1 won't actively use yet (`source_domains`, `ai_verification_jobs`, `evidence_fetch_logs`, `question_duplicate_groups`, `glossary_terms`). Schema-only — no UI, no business logic for them in Phase 1.

Phase 1 actively uses: `users`, `providers`, `product_versions`, `courses`, `exams`, `topics`, `imports`, **`import_items`**, `questions`, `question_options`, `question_explanations`, `question_references`, `attempts`, `attempt_answers`, `question_reports`, `audit_logs`.

## Key Insights
- Schema in PRD §7.2 is the authoritative source; copy it carefully into models. Three additions in this phase beyond PRD §7.2:
  - **`import_items`** — row-level import tracking (added per senior-dev review, see Phase 05).
  - **`questions.source_locator JSONB`** — back-trace from question to import file/sheet/row for debugging, audit, DMCA review.
  - **`attempt_answers.order_index INT NOT NULL`** — frozen presentation order per attempt; survives later question edits/retirement.
- **Schema-only-future-tables policy:** Phase 2/3 tables (`source_domains`, `ai_verification_jobs`, `evidence_fetch_logs`, `question_duplicate_groups`, `glossary_terms`) get DDL in Phase 1 but **no UI, no service logic, no seed UI**. They exist so Phase 2 doesn't pay migration churn. Do NOT let them block Phase 1 delivery.
- Even unused tables get created — having `audit_logs` from day 1 means Phase 03 can write to it without migration churn.
- All enums use Postgres native ENUM via SQLAlchemy `Enum` with `create_type=True`.
- Foreign keys use `ON DELETE RESTRICT` by default; soft-delete via `deleted_at` is preferred over hard delete.
- Seed data: Fortinet provider, FortiOS 7.4 product_version, NSE4 course/exam stub. **`source_domains` minimal seed only** (~5 entries); full trust list deferred to Phase 2.
- PG14 still grants `public` schema to `PUBLIC` by default — must `REVOKE` (per prior conversation).

## Requirements
**Functional**
- Alembic baseline + initial revision applied cleanly to a fresh database.
- All v2 tables created with indexes per PRD §7.3.
- Seed migration loads Fortinet provider + product_version + source_domains.
- Roll forward AND roll back tested locally.

**Non-functional**
- Migration files use kebab-case slug (`alembic revision --autogenerate -m "initial-schema"`).
- No DDL outside Alembic — even tiny changes go through a revision.

## Architecture
SQLAlchemy 2.0 declarative + Alembic autogenerate. Single `app/models/` package, one file per logical area:

```
app/models/
├── __init__.py
├── base.py                 # DeclarativeBase, TimestampMixin, SoftDeleteMixin
├── enums.py                # all ENUMs centralized
├── users.py
├── catalog.py              # provider, product_version, course, exam, topic
├── questions.py            # question, question_option, question_explanation,
│                           # question_duplicate_group
├── evidence.py             # source_domain, question_reference, evidence_fetch_log
├── ai.py                   # ai_verification_job (Phase 2 will populate)
├── imports.py              # import, import_item
├── attempts.py             # attempt, attempt_answer (with order_index)
├── reports.py              # question_report
├── audit.py                # audit_log
└── glossary.py             # glossary_term (Phase 3)
```

### New / changed tables vs PRD §7.2

```sql
-- NEW: import_items (row-level Excel import tracking)
import_items (
  id PK,
  import_id FK → imports(id) ON DELETE CASCADE,
  row_number INT NOT NULL,
  sheet_name VARCHAR(64),
  raw_data JSONB,                      -- raw parsed row (post-extraction, pre-normalize)
  normalized_data JSONB,               -- post-normalize/sanitize snapshot
  status ENUM('parsed','ok','duplicate','warning',
              'error','skipped','imported') NOT NULL DEFAULT 'parsed',
  error_message TEXT,
  warning_message TEXT,
  content_hash CHAR(64),               -- sha256 hex; formula = plan.md (normalize Q + sort normalized options, join with "||")
  question_id FK → questions(id) ON DELETE SET NULL,
  created_at, updated_at,
  UNIQUE (import_id, row_number, sheet_name)
)

-- CHANGED: questions adds source_locator
questions (
  ...,
  source_locator JSONB,                -- {import_id, import_item_id, file_name,
                                       --  sheet_name, row_number}
  ...
)

-- CHANGED: attempt_answers adds order_index
attempt_answers (
  ...,
  order_index INT NOT NULL,            -- 1..N, frozen at attempt start
  ...,
  UNIQUE (attempt_id, order_index)
)
```

## Related Code Files
**Create**
- `app/models/*.py`
- `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/<rev>_initial_schema.py`, `migrations/versions/<rev>_seed_baseline_data.py`
- `scripts/db_setup.sh` (idempotent — creates role + db on existing PG14, run as `postgres` OS user)
- `scripts/seed_dev_data.py` (extra dev fixtures, not committed migrations)
- `tests/test_models_smoke.py`

## Implementation Steps

1. **Create `app/models/base.py`** with `DeclarativeBase`, `TimestampMixin` (`created_at`, `updated_at`), `SoftDeleteMixin` (`deleted_at`).
2. **Centralize enums in `app/models/enums.py`** matching PRD §7.2 — include all status enums needed across the schema, even if some values are only used in Phase 2 (so we don't migrate the type later).
3. **Author models** following PRD §7.2 table layout. Use `Mapped[]` style for SQLAlchemy 2.0 typing.
4. **Initialize Alembic** — `alembic init migrations`. Configure `env.py` to import `app.models.base.Base.metadata` and read `DATABASE_URL` from `app.config`.
5. **Generate baseline migration**: `alembic revision --autogenerate -m "initial-schema"`. Review output carefully — autogenerate misses some constraints; hand-edit as needed.
6. **Add critical indexes** (PRD §7.3 + new):
   - `(exam_id, status, deleted_at)` on `questions`
   - `(needs_human_review, confidence_level)` on `questions`
   - `(content_hash)` on `questions` (for dedup)
   - `(question_id, is_correct)` on `attempt_answers`
   - `(entity_type, entity_id, created_at DESC)` on `audit_logs`
   - Partial: `(next_verification_due_at) WHERE stale_status<>'fresh'` on `questions`
   - **NEW** `(import_id, status)` on `import_items`
   - **NEW** `(content_hash)` on `import_items` (dedup lookup pre-insert)
   - **NEW** `(attempt_id, order_index)` UNIQUE on `attempt_answers`
7. **Write seed migration (minimal)** — Fortinet provider, FortiOS 7.4 product_version, NSE4 course + exam stub. **Defer full source_domains trust list to Phase 2**; seed only ~5 entries here (Fortinet docs, Microsoft Learn, AWS Docs, kubernetes.io, ietf.org) just to keep FK references valid if any Phase 1 code references them.
8. **Write `scripts/db_setup.sh`** — idempotent role + database creation per prior conversation:
   ```bash
   sudo -u postgres psql <<SQL
   DO \$\$ BEGIN
     IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='exam_platform_user') THEN
       CREATE ROLE exam_platform_user LOGIN PASSWORD :'pw' NOSUPERUSER NOCREATEDB
         NOCREATEROLE NOREPLICATION CONNECTION LIMIT 30;
     END IF;
   END \$\$;
   SELECT 'CREATE DATABASE exam_platform_db OWNER exam_platform_user'
     WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='exam_platform_db')\\gexec
   SQL
   ```
9. **After db creation**, connect to `exam_platform_db` and run:
   ```sql
   REVOKE ALL ON SCHEMA public FROM PUBLIC;
   GRANT ALL ON SCHEMA public TO exam_platform_user;
   ALTER ROLE exam_platform_user IN DATABASE exam_platform_db
     SET statement_timeout = '15s',
         idle_in_transaction_session_timeout = '60s',
         lock_timeout = '5s';
   ```
10. **Run migrations** as `exam_platform_user` (not as `postgres`) to avoid privilege drift between local and prod.
11. **Smoke test in `tests/test_models_smoke.py`** — create one of each entity in a transaction, rollback. Catches FK / type errors early.
12. **Document migration workflow** in `README.md`: how to create, autogenerate, review, apply, rollback.

## Todo List
- [ ] All models in `app/models/` per PRD §7.2 + plan additions
- [ ] **`import_items` table created with FK + unique + indexes**
- [ ] **`questions.source_locator JSONB` column present**
- [ ] **`attempt_answers.order_index INT NOT NULL` + UNIQUE(attempt_id, order_index)**
- [ ] Schema-only future tables created without UI/service stubs
- [ ] Alembic initialized with `env.py` reading `DATABASE_URL` from settings
- [ ] Initial schema migration generates and applies cleanly
- [ ] All §7.3 indexes + new indexes present in migration
- [ ] Seed migration loads provider + product_version + minimal source_domains
- [ ] `scripts/db_setup.sh` creates role + db idempotently on existing PG14
- [ ] `public` schema permissions tightened (REVOKE FROM PUBLIC)
- [ ] Per-role `statement_timeout`, `lock_timeout`, `idle_in_transaction_session_timeout` set
- [ ] `tests/test_models_smoke.py` passes (covers import_item, source_locator, order_index)
- [ ] Roll-back of latest migration tested
- [ ] README documents migration workflow + which tables are schema-only

## Success Criteria
- Fresh PG14 cluster + `bash scripts/db_setup.sh` + `alembic upgrade head` produces a fully provisioned `exam_platform_db`.
- `\dt` lists all PRD §7.2 tables.
- `pg_dump exam_platform_db | wc -l` shows non-trivial schema export (>500 lines).
- Blog DB on the same cluster remains untouched (verified via `\l` + connect test from blog role).

## Risk Assessment
- **Autogenerate misses ENUMs** — must hand-edit migrations for first revision.
- **Future migration conflicts** if multiple devs autogenerate concurrently. Mitigation: trunk-based dev, one migration per PR.
- **Forgetting to REVOKE PUBLIC schema grants** is silent until Phase 2. Add to setup script + verification test.

## Security Considerations
- Role is `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION` — minimum privilege.
- `CONNECTION LIMIT 30` bounds blast radius.
- `statement_timeout 15s` kills runaway queries.
- App password via `.env`, never committed.
- `pg_hba.conf` should already allow only `localhost` (verify; do not change without ops review).
- Migrations run as the app role — keeps prod and dev auth identical.

## Next Steps
Phase 03 — Auth, RBAC, audit log foundation. Models for `users` and `audit_logs` exist after this phase; Phase 03 writes the application logic.
