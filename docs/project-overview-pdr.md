# Project Overview — PDR

## What we're building

An **exam practice platform** where learners take Excel-imported practice exams,
see scores and per-question explanations as imported. Admins import question
banks privately, audit every action, and publish manually.

> Source PRD: [`PRD.md`](../PRD.md). This file is the operating summary.

## Phase 1 MVP scope (4–6 weeks, locked)

- Vendor: Fortinet seeded; first product version FortiOS 7.4; first exam stub NSE4.
- ≥100 curated, topic-tagged questions imported via Excel by Internal-Beta gate.
- Server-rendered HTML (Jinja + HTMX + Alpine.js). No SPA in Phase 1.
- Private-by-default imports; explicit publish step required.
- Manual `pg_dump` + `pg_restore` drill before Internal Beta;
  automated off-site backup (restic-equivalent) before Public Soft-Launch.
- Co-tenant on existing Ubuntu LXC's PostgreSQL 14 cluster — separate
  database (`exam_platform_db`) and role (`exam_platform_user`).

## Out of scope (Phase 1)

- AI verification, evidence cache, AI tutor, weak-topic mode, flashcards,
  spaced repetition, glossary, near-duplicate detection.
- Instructor accounts, billing, mobile app, HTML/PDF import.

These tables exist as **schema-only stubs** in Phase 02 so Phase 2/3 don't pay
migration churn (`source_domains`, `ai_verification_jobs`, `evidence_fetch_logs`,
`question_duplicate_groups`, `glossary_terms`).

## Two exit gates

### Gate A — Internal Beta (5 users)
- 1 vendor seeded (Fortinet), ≥100 curated topic-tagged questions.
- 5 internal beta users complete a full attempt.
- Admin imports 100+ questions in <10 min.
- All admin question/exam mutations appear in `audit_logs`.
- 100% of imports default to `private`.
- Manual `pg_dump` + `pg_restore` drill executed and recorded.
- Excel import error rate <5% on the canonical template.
- Idempotent confirm verified (re-running confirm → 0 new questions).

### Gate B — Public Soft-Launch
- ≥200 published questions, ≥80% with overall explanations.
- Top-3 internal-beta issues fixed.
- Practice page p95 <500 ms; result page p95 <800 ms (1k seeded users).
- Automated off-site backup live with 7d/4w/6m retention.
- Restore drill repeated within last 30 days.
- Counsel-reviewed legal pages or documented founder boilerplate acceptance.

## Tech stack (locked for Phase 1)

| Layer | Choice |
|---|---|
| Web framework | FastAPI |
| ORM / migrations | SQLAlchemy 2.0 + Alembic |
| Database | PostgreSQL 14 (co-tenant on existing cluster) |
| Cache / queue | Redis 7 + RQ (queue scaffolded; no jobs in Phase 1) |
| Templates | Jinja2 + HTMX + Alpine.js (vendored locally — no CDN) |
| Auth | Cookie sessions (itsdangerous) + Argon2id (passlib) |
| Server | uvicorn behind Nginx (Phase 11) |
| Logging | structlog (console-dev, JSON-prod) |
| Tooling | uv (deps + lockfile), ruff (lint+format), mypy, pytest |
| Deploy target | Ubuntu 22.04 LXC at `/srv/exam-platform` (prod), `/srv/exam-platform-dev` (dev) |

## Cross-cutting principles

1. **Never overwrite source data.** `given_answer` and `ai_verified_answer` always coexist.
2. **Soft delete + supersession** — preserve attempt history.
3. **Every admin mutation goes through `audit_log_writer.write()` in the same DB transaction** as the change. (Phase 03 introduces the helper.)
4. **DB-backed import staging** — Excel rows persisted to `import_items` immediately; preview survives reload; confirm is idempotent.
5. **`source_locator JSONB` on every question** — back-trace to import_id + import_item_id + file/sheet/row.
6. **`order_index INT NOT NULL` on `attempt_answers`** — frozen presentation order per attempt; never re-orders past attempts.
7. **`content_hash` exact-dedup only** — sha256 of normalized question + sorted normalized options. Near-duplicate dedup is Phase 3.
8. **Sanitization on import + render** — `bleach` + `markdown-it-py` defense applies even though no AI verifier yet.
9. **Private-by-default everywhere.** Public listing pages only show `publish_status='published'`.

## Phase status (live)

See [`project-roadmap.md`](project-roadmap.md) for current phase tracking.
