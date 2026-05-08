# Phase 01 — Enable pg_trgm + index

## Context

- Plan overview: `../plan.md`
- Current dedup: `app/services/import_dedup.py` (exact SHA-256 only)
- Postgres on LXC: 14 (pg_trgm available as contrib)

## Overview

**Priority:** must-do-first (everything downstream depends on it)
**Status:** pending approval

Enable `pg_trgm` extension and add a GIN trigram index on
`questions.question_text` so phase 02's similarity queries are bounded.

## Requirements

**Functional**
- `pg_trgm` extension active in the dev DB
- GIN index on `questions.question_text` using `gin_trgm_ops`
- Index excludes soft-deleted rows (partial index `WHERE deleted_at IS NULL`) — saves space + speed

**Non-functional**
- Migration is reversible: `op.drop_index(...)` + `op.execute("DROP EXTENSION IF EXISTS pg_trgm")`
- Zero downtime: extension creation is non-blocking; `CREATE INDEX CONCURRENTLY` for the index (Alembic supports via `op.create_index(..., postgresql_concurrently=True)` when run outside a transaction)
- No data changes — schema-only

## Implementation steps

1. Generate Alembic revision: `alembic revision -m "enable pg_trgm + question_text trigram index"`
2. Body:
   - `op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")`
   - In an outside-transaction block: `op.create_index("ix_questions_question_text_trgm", "questions", ["question_text"], postgresql_using="gin", postgresql_ops={"question_text": "gin_trgm_ops"}, postgresql_concurrently=True, postgresql_where=text("deleted_at IS NULL"))`
3. Downgrade: drop index, drop extension (only if no other dependent index exists — guard with `pg_extension` lookup).
4. Apply on dev (`alembic upgrade head`), verify with `\dx` and `\di+ ix_questions_question_text_trgm`.
5. Smoke benchmark: `EXPLAIN ANALYZE SELECT id, similarity(question_text, 'Which OSI layer handles routing') FROM questions WHERE question_text % 'Which OSI layer handles routing' AND exam_id=1 ORDER BY similarity DESC LIMIT 5;` — confirm GIN index is used.

## Success criteria

- `\dx` lists `pg_trgm`
- `EXPLAIN` shows `Bitmap Index Scan on ix_questions_question_text_trgm`
- Existing tests still pass (no behavioural change yet)
- Migration reverses cleanly on a scratch DB

## Risks

- **Concurrent index build** can't run inside a migration transaction. Alembic supports this — but the migration must be flagged with `transactional_ddl = False` or use `op.get_bind().execution_options(isolation_level='AUTOCOMMIT')`.
- **Old prod data** (~250 questions) — index build is fast, < 1 second. Non-issue at this scale.

## Next phase

Phase 02 — `find_near_duplicates()` service function using this index.
