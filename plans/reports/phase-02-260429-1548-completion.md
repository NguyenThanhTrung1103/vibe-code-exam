# Phase 02 — Database Migrations & Postgres Co-Tenant Setup — Completion Report

**Date:** 2026-04-29
**Plan:** `plans/260428-1631-phase-1-mvp-exam-platform/phase-02-database-setup.md`
**Target:** Ubuntu 22.04 LXC at 192.168.99.97, working dir `/srv/exam-platform-dev/`, DB `exam_platform_db` co-tenanted on existing PG14.
**Status:** ✅ Complete — safe to proceed to Phase 03.

---

## 1. Files synced to LXC

Synced via `scp` over the dedicated `exam-lxc` SSH alias (key auth, key bound to this work only):
- `app/db.py` — Base re-exported from `app.models.base`.
- `app/models/__init__.py`, `app/models/base.py`, `app/models/enums.py`,
  `app/models/users.py`, `app/models/catalog.py`, `app/models/questions.py`,
  `app/models/evidence.py`, `app/models/ai.py`, `app/models/imports.py`,
  `app/models/attempts.py`, `app/models/reports.py`, `app/models/audit.py`,
  `app/models/glossary.py`.
- `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`.
- `migrations/versions/0001_c3961a3f2aa0_initial_schema.py` (892 lines, hand-edited).
- `migrations/versions/0002_seed_baseline_data.py` (~140 lines, ON CONFLICT idempotent).
- `tests/test_models_smoke.py` (real-DB transaction + rollback).
- `scripts/db_setup.sh` already present from previous step.

SHA-256 verified identical local↔remote for every file.

## 2. Alembic migration result

```
INFO  [alembic.runtime.migration] Running upgrade  -> c3961a3f2aa0, initial-schema
INFO  [alembic.runtime.migration] Running upgrade c3961a3f2aa0 -> 8f2d3a4b5c6e, seed-baseline-data
```

**Final revision:** `8f2d3a4b5c6e` (seed-baseline-data).
**Tables created:** 21 active + `alembic_version` = 22 total.
**ENUM types created:** 23.

## 3. Downgrade / upgrade round-trip

| Step | Result |
|---|---|
| `alembic downgrade base` | Both migrations rolled back cleanly. `exam_platform_db` left with only `alembic_version` (no version row), 0 ENUM types in `public`. Blog DB untouched (1 table, owner `blog`). |
| `alembic upgrade head` (re-run) | Both migrations re-applied without error. 22 tables, version `8f2d3a4b5c6e`, providers=1, source_domains=5. |

Idempotency proven — round-trip is a true no-op against a clean DB.

## 4. DB schema verification

| Item | Result |
|---|---|
| 21 tables present | ✓ (`ai_verification_jobs`, `attempt_answers`, `attempts`, `audit_logs`, `courses`, `evidence_fetch_logs`, `exams`, `glossary_terms`, `import_items`, `imports`, `product_versions`, `providers`, `question_duplicate_groups`, `question_explanations`, `question_options`, `question_references`, `question_reports`, `questions`, `source_domains`, `topics`, `users`) |
| All tables owned by `exam_platform_user` | ✓ |
| 23 native ENUM types | ✓ (`actor_type`, `ai_verification_status`, `attempt_mode`, `confidence_level`, `detection_method`, `evidence_fetcher`, `exam_publish_status`, `explanation_status`, `fetch_status`, `glossary_status`, `import_item_status`, `import_publish_status`, `import_status`, `question_difficulty`, `question_status`, `question_type`, `report_reason`, `report_status`, `source_type`, `stale_status`, `trust_level`, `user_role`, `visibility`) |
| `questions.source_locator` | `jsonb` ✓ (Phase 02 plan addition) |
| `attempt_answers.order_index` | `integer NOT NULL` ✓ (Phase 02 plan addition) |
| `uq_attempt_answers_attempt_order` | UNIQUE `(attempt_id, order_index)` ✓ |
| `import_items` table | All columns + `uq_import_items_row` UNIQUE `(import_id, row_number, sheet_name)` ✓ |
| `ix_import_items_import_status` | ✓ |
| `ix_import_items_content_hash` | ✓ |
| `ix_attempt_answers_question_correct` | ✓ |
| `ix_questions_exam_status_deleted` | ✓ |
| `ix_questions_review_queue` | ✓ |
| `ix_questions_content_hash` | ✓ |
| `ix_questions_due_partial` | partial — `WHERE stale_status <> 'fresh'::stale_status` ✓ |
| `ix_audit_logs_entity_recent` | ✓ |
| `ix_question_references_source_status` | ✓ |
| FK on-delete policies | `import_items.import_id` CASCADE, `import_items.question_id` SET NULL, all others RESTRICT ✓ |
| Per-role timeouts on the new DB | `statement_timeout=15s, idle_in_transaction_session_timeout=60s, lock_timeout=5s` ✓ |
| `public` schema grants tightened | `nspacl = {postgres=UC/postgres,exam_platform_user=UC/postgres}` (PUBLIC revoked) ✓ |
| `exam_platform_user` role | `f|f|f|f|10` (no super, no createrole/db, no replication, conn limit 10) ✓ |

## 5. Seed data verification

| Table | Rows | Sample |
|---|---|---|
| `providers` | 1 | `fortinet` |
| `product_versions` | 1 | FortiOS 7.4 |
| `courses` | 1 | `fortinet-nse4` |
| `exams` | 1 | `fortinet-nse4-fgt-security` (NSE4_FGT-7.4, private/draft) |
| `source_domains` | 5 | `docs.aws.amazon.com`, `docs.fortinet.com`, `ietf.org`, `kubernetes.io`, `learn.microsoft.com` (all `official_vendor`/`high` except `ietf.org` = `rfc_standard`/`high`) |

Idempotency: seed migration uses `ON CONFLICT DO NOTHING` (slug/domain UNIQUE) and `WHERE NOT EXISTS` for tables without natural unique keys — re-running creates 0 new rows.

## 6. Real-DB smoke test result

```
EXAM_PLATFORM_TEST_REAL_DB=1 uv run pytest -v
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.0.3, pluggy-1.6.0
collected 6 items

tests/test_config.py ..                                                  [ 33%]
tests/test_health.py ...                                                 [ 83%]
tests/test_models_smoke.py .                                             [100%]
========================= 6 passed, 1 warning in 0.10s =========================
```

Smoke test inserted **one row of every Phase 1 active entity** (User, Provider, ProductVersion, Course, Exam, Topic, Import, ImportItem, Question, QuestionOption, QuestionExplanation, SourceDomain, Attempt, AttemptAnswer, QuestionReport, AuditLog) inside a transaction, exercised:
- Round-trip JSONB on `questions.source_locator` (read back `import_item_id`).
- `uq_attempt_answers_attempt_order` UNIQUE — duplicate insert → IntegrityError caught.
…then **rolled the transaction back**. Post-test counts: providers=1, source_domains=5 (seeds), users=0, attempts=0, questions=0 — confirms zero leak.

The single warning (`SAWarning: transaction already deassociated from connection`) is cosmetic — the test calls `s.rollback()` after catching the IntegrityError, then the fixture's outer `transaction.rollback()` is a no-op. No data leak. Will tighten with savepoints in a future polish pass; non-blocking.

## 7. ruff / format / mypy / pytest results

| Gate | LXC result |
|---|---|
| `uv run ruff check app tests migrations` | All checks passed |
| `uv run ruff format --check app tests migrations` | 29 files already formatted |
| `uv run mypy app` | Success: no issues found in 23 source files |
| `EXAM_PLATFORM_TEST_REAL_DB=1 uv run pytest` | 6 passed |

## 8. `/healthz` against real PG + Redis

```
$ curl http://127.0.0.1:8001/healthz
HTTP 200
{"status":"ok","db":"ok","redis":"ok"}
```

- App started via `uv run uvicorn app.main:app --host 127.0.0.1 --port 8001`.
- Bound to **127.0.0.1:8001 only** (verified by `ss -ltnp`); no LAN/public exposure.
- Static assets: `base.css` 200/1472 B, `htmx.min.js` 200/48101 B, `alpine.min.js` 200/44659 B.
- App stopped after verification.

## 9. Blog-safety verification (pre vs post)

| Surface | Pre | Post | Verdict |
|---|---|---|---|
| `/etc/postgresql/14/main/postgresql.conf` SHA | `e6a345c5…` | `e6a345c5…` | ✓ unchanged |
| `/etc/postgresql/14/main/pg_hba.conf` SHA | `548d74c9…` | `548d74c9…` | ✓ unchanged |
| `/etc/redis/redis.conf` SHA | `f9f998aa…` | `f9f998aa…` | ✓ unchanged |
| `/etc/nginx/nginx.conf` SHA | `4869cddc…` | `4869cddc…` | ✓ unchanged |
| `blog.service` | active | active | ✓ |
| `postgresql` | active | active | ✓ |
| `nginx` | active | active | ✓ |
| `cloudflared` | active | active | ✓ |
| `redis-server` | active | active | ✓ |
| `blogdb` owner | `blog` | `blog` | ✓ |
| `blog` role attributes | `f\|f\|f\|f` | `f\|f\|f\|f` | ✓ |
| `blogdb` table count | 1 | 1 | ✓ |
| `/srv/blog-website` | unchanged | unchanged | ✓ (mtime + size identical) |
| `/srv/Exam` | unchanged | unchanged | ✓ |

**No collateral impact on the blog stack.**

## 10. Phase 02 complete?

**Yes.** Every Todo from `phase-02-database-setup.md` is satisfied:

- [x] All models in `app/models/` per PRD §7.2 + plan additions
- [x] `import_items` table created with FK + unique + indexes
- [x] `questions.source_locator JSONB` column present
- [x] `attempt_answers.order_index INT NOT NULL` + UNIQUE(attempt_id, order_index)
- [x] Schema-only future tables created without UI/service stubs
- [x] Alembic initialized with `env.py` reading `DATABASE_URL` from settings
- [x] Initial schema migration generates and applies cleanly
- [x] All §7.3 indexes + new indexes present in migration
- [x] Seed migration loads provider + product_version + minimal source_domains
- [x] `scripts/db_setup.sh` creates role + db idempotently on existing PG14
- [x] `public` schema permissions tightened (REVOKE FROM PUBLIC, GRANT to app role only)
- [x] Per-role `statement_timeout`, `lock_timeout`, `idle_in_transaction_session_timeout` set
- [x] `tests/test_models_smoke.py` passes (covers `import_item`, `source_locator`, `order_index`)
- [x] Roll-back of latest migration tested + re-upgrade verified
- [x] Migration workflow documented (in plan + report; will mirror into README in Phase 03 docs pass if scope allows)

Plus the success-criteria from the plan:

- [x] Fresh PG14 cluster + role + DB script + `alembic upgrade head` produces a fully provisioned `exam_platform_db`. ✓
- [x] `\dt` lists all PRD §7.2 tables. ✓
- [x] Blog DB on the same cluster remains untouched (verified via `\l`, `\du`, table-count diff). ✓

## 11. Safe to proceed to Phase 03?

**Yes.** Phase 03 (Auth, RBAC, audit log foundation) depends on:
- `users` table (exists, with `role` enum and unique email/username) ✓
- `audit_logs` table (exists, `actor_id` nullable, JSONB old/new_value, `request_id` UUID, indexed by entity_type+id+created_at DESC) ✓
- A working DB connection plumbing (proven by `/healthz` `db:ok`) ✓
- Sessions framework (FastAPI middleware + `SECRET_KEY` env) — already present from Phase 01 ✓

No blockers identified. The `audit_log_writer` helper that Phase 03 introduces will write through the same SQLAlchemy session — schema is already there.

---

## Deviations from the Phase 02 plan

| Deviation | Reason | Acceptable? |
|---|---|---|
| **Used `C.UTF-8`** instead of `en_US.UTF-8` for the new DB. | `en_US.UTF-8` not generated on the LXC; user explicitly approved `C.UTF-8` to avoid a system-level locale-gen change. | Yes — Unicode-safe, no functional difference for Phase 1 content. |
| **`CONNECTION LIMIT = 10`** on `exam_platform_user` instead of plan's 30. | User explicitly chose 10 for the dev LXC. | Yes — dev right-sizes blast radius further. |
| **Seed migration uses `ON CONFLICT DO NOTHING`** for tables with UNIQUE keys instead of plan's pattern of guard SELECTs. | First attempt with guarded SELECTs hit a Postgres parameter type-inference error. ON CONFLICT is simpler, more idiomatic, equally idempotent. | Yes — better. |
| **Did not seed `topics`** (Phase 02 plan only requires provider + product_version + minimal source_domains; topics seeding mentioned in NSE4 stub area but optional). | YAGNI — topics will be created by the import pipeline (Phase 05) or the catalog editor (Phase 04). | Yes. |
| **`pg_hba.conf` not edited.** | Existing rule `host all all 127.0.0.1/32 scram-sha-256` already covers our role. | Yes — exactly per the plan's "verify, don't edit" stance. |
| **Generated migration filename has `0001_` / `0002_` prefix instead of Alembic's default timestamp prefix.** | User approved this for chronological readability. | Yes. |
| **Python 3.14** in the LXC venv. | `uv sync` chose the highest available Python (uv-managed). Local dev is 3.12; the project specifies `>=3.12`. | Yes — both pass tests. Document pinning in a future hardening pass. |

## Issues fixed during Phase 02

1. **Autogenerate emitted shared-ENUM `create_type=True` twice** for `visibility`, `source_type`, `trust_level` — would fail on apply. Hand-edited migration to create those types up-front and reference them with `create_type=False`.
2. **Circular FK** between `questions` and `question_duplicate_groups` flagged by SA. Resolved by deferring the `question_duplicate_groups.canonical_question_id → questions.id` FK to a post-table-create `op.create_foreign_key`.
3. **Downgrade did not drop ENUM types**, breaking re-upgrade idempotency. Added explicit `DROP TYPE IF EXISTS` for every enum at the tail of `downgrade()`.
4. **First seed attempt failed** with `inconsistent types deduced for parameter` — same parameter used twice in one statement. Switched to `ON CONFLICT DO NOTHING` / `NOT EXISTS in CTE`.
5. **Second seed attempt failed** on `'private'::visibility` — SA's `text()` interprets `::` as escaped `:`. Switched to `CAST('private' AS visibility)`.

## Remaining blockers / risks

- **`SAWarning: transaction already deassociated from connection`** in the smoke test fixture — cosmetic. Test still passes and rolls back cleanly. Tightening to use savepoints is a polish item, not a blocker.
- **No CI workflow yet.** Phase 02 plan doesn't require it; Phase 11 owns deployment.
- **`migrations/versions/__pycache__`** gets created on the LXC during `alembic upgrade`. Already in `.gitignore`. No action.
- **`uv` venv on LXC uses Python 3.14**; local uses 3.12. Both pass all gates. Pinning to 3.12 in `pyproject.toml`'s `requires-python` is already `>=3.12`; if we want to force 3.12 specifically, switch to `~=3.12`. Defer until Phase 11.
- **Documentation of migration workflow in README** — still on the to-do list from Phase 02 plan. Will be folded into Phase 03's docs pass per the user's "avoid scope creep" rule.

## Recommended Phase 03 prompt (for next session)

```
Begin execution with Phase 03 only.

Use the Phase 03 plan file strictly:
plans/260428-1631-phase-1-mvp-exam-platform/phase-03-auth-rbac-audit-log.md

Scope:
- Session-cookie authentication (signed via itsdangerous + SECRET_KEY).
- Argon2 password hashing (passlib already in deps).
- RBAC role guards for admin / instructor / student / system.
- `audit_log_writer.write()` helper that writes in the SAME DB transaction
  as the data change.
- Login / logout / signup HTML routes (server-rendered Jinja, HTMX-friendly
  form posts, CSRF token via signed cookie).
- Apply session middleware (FastAPI `SessionMiddleware`) and CSRF check on
  POST.

Rules:
- Do not implement catalog CRUD, import, practice, scoring, deployment,
  or AI features.
- Do not modify schema — Phase 02 schema is the source of truth.
- All admin mutations must call `audit_log_writer.write()` in the same
  transaction (pattern only; no admin actions exist yet).
- Sessions cookie MUST be `HttpOnly`, `SameSite=Lax`, `Secure=False` in dev.
- Hash passwords with argon2id (`passlib[argon2]`).
- Generate CSRF tokens with itsdangerous; verify on every state-changing
  request.
- Do not relax pg_hba / postgresql.conf / nginx config.
- Phase 03 changes are LXC-validated against real PG + Redis on
  127.0.0.1:8001.

Testing requirement:
1. Pytest covers signup → login → logout → access-after-logout flow.
2. Pytest covers RBAC denial when wrong role hits a guarded endpoint.
3. Pytest covers `audit_log_writer.write()` rollback (audit row rolled back
   when the surrounding transaction rolls back).
4. Run ruff / format / mypy.
5. Live `/healthz` still returns 200 against real PG/Redis.
6. Live login flow works end-to-end on the LXC (curl POST /login →
   `Set-Cookie` → curl GET /me with cookie → 200).
7. Verify audit_logs row appears for an admin action (pick one — e.g. a
   role change — even if it's a synthetic test endpoint).

Deliverables:
- Phase 03 completion report mirroring this Phase 02 report:
  Files synced, route inventory, gates, live checks, blog-safety
  invariants, deviations, blockers/risks, whether Phase 03 is complete,
  whether safe to proceed to Phase 04, and the exact Phase 04 prompt.
```

---

**Quality gate verdict:** Migrations apply ✓ — round-trip clean ✓ — all 9 PRD §7.3 indexes + 3 plan additions present ✓ — smoke test against real DB passes ✓ — `/healthz` 200 against real PG + Redis ✓ — blog DB / role / configs / services untouched ✓ — no Phase 03+ scope leaked ✓. **Phase 02 is DONE.**

**Status:** DONE
**Summary:** Phase 02 schema, migrations, and seed data deployed on real PG14 inside `exam_platform_db` on the LXC; round-trip verified; smoke test green; live `/healthz` against real PG + Redis returns 200; zero impact to existing blog stack.
**Concerns/Blockers:** Minor SAWarning in smoke-test rollback (cosmetic) and Python 3.14 on LXC vs 3.12 local (both pass gates). Neither blocks Phase 03.
