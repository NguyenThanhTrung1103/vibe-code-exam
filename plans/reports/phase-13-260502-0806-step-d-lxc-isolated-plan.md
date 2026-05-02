---
title: Phase 13 Step D — LXC-isolated PostgreSQL smoke plan (approved)
date: 2026-05-02 08:06 (Asia/Saigon)
plan: ../260430-2233-cdea-phase-13-16a/phase-13-discussion-url-parser.md
prior_report: phase-13-260502-0753-completion.md
host: win32 (Windows dev box)
target: LXC 192.168.99.97 — PostgreSQL 14 — root@ SSH
isolation: dedicated DB exam_phase13_smoke + role exam_phase13_smoke_user (no public exposure)
status: APPROVED, executing 2026-05-02 08:14+
---

# Step D — LXC-Isolated PostgreSQL Smoke Plan

> Goal: prove migration `0006_b1c2d3e4f5a6_phase13_community_sources.py` upgrades, downgrades, and re-upgrades cleanly against a real PostgreSQL 14 instance — without ever touching `exam_platform_db`, `blogdb`, or any sibling service.

## Approach

Two-phase execution against the LXC PG cluster:
- **Admin shell on LXC** (`sudo -u postgres psql` via `root@192.168.99.97`) — creates the smoke role + DB; later DROPs them. This is the only place we use superuser.
- **SSH tunnel from Windows + Alembic from Windows** — `ssh -N -L 55432:127.0.0.1:5432 root@192.168.99.97`. From PowerShell, `DATABASE_URL` points at `127.0.0.1:55432/exam_phase13_smoke` so Alembic can never accidentally hit a non-tunneled host.

## Smoke artefact names + isolation

| Object | Name | Notes |
|---|---|---|
| Database | `exam_phase13_smoke` | Owned by `exam_phase13_smoke_user`; dropped at end |
| Role | `exam_phase13_smoke_user` | LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS, CONNECTION LIMIT 4 |
| Password | 32-char random | Generated locally on Windows; lives only in `$env:STEP_D_PG_PW`; never echoed to chat unredacted |

## Pre-flight (read-only)

- `systemctl is-active postgresql redis-server nginx cloudflared blog.service` — must all be `active` before and after.
- `\l` and `\du` to confirm `exam_phase13_smoke{,_user}` do NOT pre-exist.
- `systemctl cat exam-platform-web.service` + `systemctl show ... -p Environment -p EnvironmentFiles` to confirm the real exam app's `DATABASE_URL` points at `exam_platform_db` (we only grep `DATABASE_URL` from any referenced env file; no full secret dumps).

## DATABASE_URL guard chain (5 regex + 1 server-side)

Aborts before Alembic if any single check fails:
1. URL contains `exam_phase13_smoke`
2. URL does NOT contain `exam_platform_db`
3. URL does NOT contain `blogdb`
4. URL contains `127.0.0.1:55432`
5. URL does NOT contain `@192.168.…` or `@localhost`
6. `SELECT current_database(), current_user` returns `('exam_phase13_smoke', 'exam_phase13_smoke_user')`

## Alembic chain

1. `uv run alembic current` → expect empty (fresh DB).
2. `uv run alembic upgrade head` → expect `0001 → 0006` applied.
3. `uv run alembic current` → expect `b1c2d3e4f5a6 (head)`.
4. Schema verification (table, column, 4 enums, 6 indexes, constraints, JSONB types).
5. `uv run alembic downgrade -1` → back to `a1b2c3d4e5f6`.
6. Verify Phase 13 objects gone.
7. `uv run alembic upgrade head` → re-applied cleanly.

## Real-DB-gated import smoke

Author `tests/services/test_import_service_community_real_db.py` gated by `EXAM_PLATFORM_TEST_REAL_DB=1`. Tests:
- Alembic-applied schema accepts a CDS row insert via the upsert helper.
- Confirm-import flow over a 3-row XLSX → 1 CDS row + 1 audit row per row.
- JSONB round-trip preserves `vote_distribution`.
- Idempotent re-import → 0 new rows.
- httpx never imported into the import service path (negative test).

## Cleanup

1. Close tunnel.
2. `pg_terminate_backend` for any stragglers in `exam_phase13_smoke`.
3. `DROP DATABASE exam_phase13_smoke`.
4. `DROP ROLE exam_phase13_smoke_user`.
5. Verify both gone via `pg_database` / `pg_roles`.
6. Confirm `\l` still shows `exam_platform_db` and `blogdb`.
7. `systemctl is-active` matrix matches pre-flight.
8. Evict `$env:STEP_D_PG_PW`, `$env:DATABASE_URL`, `$env:PGPASSWORD`.

## Hard stop rules

- Any guard regex fails OR `current_database()/current_user` mismatch → STOP before Alembic.
- Sibling service goes inactive → STOP and escalate.
- Alembic upgrade raises mid-chain → STOP without auto-downgrade.

## Final report deliverables

Update `phase-13-260502-0753-completion.md` to flip the §10 / §11 / §12 "DEFERRED" rows to either ✅ or a documented failure. New 17-point Step D report inline in chat.

## Skills / rules used

See preamble in chat — `databases/SKILL.md`, the four `.claude/rules/*.md`, and root + project `CLAUDE.md`. No project-specific Alembic/LXC skill exists; closest applicable rule set is `databases/`.

## RTK usage

Hook not installed → passthrough only → 0% savings during this Step D. Will not install during this session per your instruction. Safety-critical outputs (DATABASE_URL guards, current_database, errors) kept verbatim.
