---
plan_id: 260428-1631-phase-1-mvp-exam-platform
title: Phase 1 MVP — Exam Practice Platform (4–6 weeks)
status: in_progress
created_at: 2026-04-28
scope: Phase 1 MVP only (per PRD §6 and §30.1)
stack: FastAPI + PostgreSQL 14 + Redis + RQ + Jinja2 + HTMX + Alpine.js
deploy: Ubuntu 22.04 LXC, /srv/exam-platform, co-tenant on existing PG14
blockedBy: []
blocks: []
---

# Phase 1 MVP — Exam Practice Platform

> **Source PRD:** [`E:\Vibe Code\Vibe Code\Exam\PRD.md`](../../PRD.md) (§6 MVP Scope, §30.1 Phase 1 roadmap)
> **Goal:** Ship a learner-facing platform where students take Excel-imported practice exams, see scores and per-question explanations as imported, while admin imports privately, audits actions, and publishes manually.
> **Out of scope:** AI verification, evidence cache, AI tutor, weak-topic mode, flashcards, spaced repetition, glossary, near-duplicate detection, instructor accounts, billing, mobile app, HTML/PDF import.

## Exit Criteria (Phase 1) — two gates

### Gate A — Internal Beta (5 users)
- 1 vendor seeded (Fortinet) with **≥100 curated, topic-tagged questions** imported via Excel.
- First 30–50 key questions have full per-option explanations; ≥80% have at least an overall explanation.
- 5 internal beta users complete a full attempt.
- Admin imports 100+ questions in <10 min from a standard template.
- All admin question/exam mutations appear in `audit_logs`.
- 100% of imports default to `private`; explicit publish step required.
- **Manual `pg_dump` + `pg_restore` drill executed** and recorded.
- Excel import error rate <5% on the standard template.
- **Idempotent confirm verified**: re-running confirm on same import produces 0 new questions.

### Gate B — Public Soft-Launch
- ≥200 published questions, 80%+ with overall explanations.
- Top-3 internal-beta issues fixed.
- Practice page p95 <500 ms; result page p95 <800 ms (1k seeded users).
- **Automated off-site backup live** (restic or equivalent) with 7d/4w/6m retention.
- Restore drill repeated within last 30 days.
- Counsel-reviewed legal pages (or documented founder boilerplate acceptance).

## Phase List

| # | Phase | Effort | Depends on | Owner |
|---|-------|--------|------------|-------|
| 01 | [Project scaffolding & local dev env](phase-01-project-scaffolding.md) | 2 d | — | dev |
| 02 | [Database migrations & PG co-tenant setup](phase-02-database-setup.md) | 2–3 d | 01 | dev |
| 03 | [Auth, RBAC, audit log foundation](phase-03-auth-rbac-audit-log.md) | 3–4 d | 02 | dev |
| 04 | [Catalog: provider/course/exam/topic CRUD](phase-04-catalog-management.md) | 3–4 d | 03 | dev |
| 05 | [Excel import pipeline with dedup + sanitization](phase-05-excel-import-pipeline.md) | 5–6 d | 04 | dev |
| 06 | [Question bank CRUD & manual editor](phase-06-question-bank-crud.md) | 2–3 d | 05 | dev |
| 07 | [Practice & exam mode delivery](phase-07-practice-exam-modes.md) | 4–5 d | 06 | dev |
| 08 | [Attempts, scoring, result/review screen](phase-08-attempts-scoring-result.md) | 3–4 d | 07 | dev |
| 09 | [Security hardening & rate limiting](phase-09-security-hardening.md) | 2–3 d | 03 (parallel-OK after 03) | dev |
| 10 | [Backup, observability, DR drill](phase-10-backup-observability.md) | 2 d | 02 (parallel-OK after 02) | dev |
| 11 | [Deployment on LXC with Nginx + systemd](phase-11-deployment-lxc.md) | 2–3 d | 09, 10 | dev |
| 12 | [Beta launch readiness + content seeding](phase-12-beta-launch.md) | 2–3 d | 08, 09, 10, 11 | dev |

**Realistic effort estimate:** 32–42 working days for solo dev, ≈6 weeks. The PRD's "4–6 weeks" is achievable only with focused execution and no scope creep.

## Future Phases (Stub)
See [`roadmap-future-phases.md`](roadmap-future-phases.md) for Phase 2 (AI verification, evidence cache, HTML/PDF import) and Phase 3 (AI tutor, glossary, weak-topic, flashcards, spaced repetition). **Do not plan in detail until Phase 1 ships.**

## Key Architectural Decisions (locked for Phase 1)
1. **One Postgres cluster** — co-tenant on existing PG14. Separate database `exam_platform_db`, separate role `exam_platform_user`. (See prior conversation + Phase 02.)
2. **Server-rendered HTML** via Jinja + HTMX + Alpine. No SPA in Phase 1.
3. **Private-by-default imports.** Public listing pages only show `publish_status='published'`.
4. **Schema includes Phase 2/3 tables** (`source_domains`, `ai_verification_jobs`, `evidence_fetch_logs`, `question_duplicate_groups`, `glossary_terms`) **as schema-only stubs** — DDL only, no UI/service code, so Phase 2 doesn't pay migration churn. Tables Phase 1 actively uses: `users`, catalog (`providers`, `product_versions`, `courses`, `exams`, `topics`), `imports`, **`import_items`**, `questions` (with `source_locator`), `question_options`, `question_explanations`, `question_references`, `attempts`, `attempt_answers` (with `order_index`), `question_reports`, `audit_logs`.
5. **DB-backed import staging** — Excel rows persisted to `import_items` immediately; preview is queryable, survives reload, and confirm is idempotent (re-running creates 0 new questions). Per-row state machine: `parsed → ok / duplicate / warning / error / skipped → imported`.
6. **`source_locator` JSONB on every question** — back-traces to import_id + import_item_id + file/sheet/row. Enables debugging, audit, DMCA review.
7. **`order_index` on `attempt_answers`** — at attempt start the server **shuffles the exam's question snapshot once**, then persists order as `order_index` 1..N. **`order_index` is the source of truth** for that attempt; no deterministic-by-`attempt_id` requirement. Later admin edits or retirement do not reorder past attempts.
8. **`content_hash` (exact dedup only)** — canonical formula, same everywhere (import, DB, Phase 05/06):
   - Normalize `question_text` and each non-empty option string (same normalizer as import).
   - Sort normalized option strings lexicographically so A/B/C/D order does not change the hash.
   - `sha256(normalized_question + "|" + "||".join(sorted_normalized_options))` (hex digest stored on `questions` / `import_items`).
   - Used **only** for exact-duplicate detection. **Near-duplicate / semantic dedup → Phase 3**, out of scope for Phase 1.
9. **Audit log helper from day 1.** Every admin mutation goes through `audit_log_writer` in the **same transaction** as the data change (see Phase 03 — service methods may be named `create_*` / `update_*`, not a single generic `mutate()`). No exceptions.
10. **Sanitization on import + render path** even though no AI verifier yet — defense applies to rendering imported HTML/Markdown.
11. **No worker queue at MVP** — RQ + Redis scaffolded but no jobs use it yet (used in Phase 2 for AI verification). Spawn worker process is optional for Phase 1.
12. **Backup phasing** — manual drill before internal beta is mandatory; automated off-site + retention required before public soft-launch (not before internal beta).

## Cross-Cutting Risks
- **Scope creep into Phase 2** (AI features) is the #1 risk. Owner must enforce "no AI in Phase 1" rule.
- **Excel template drift** — admin's real Excel files will not match the canonical template. Mapping UI is mandatory.
- **PG14 EOL Nov 2026.** Plan PG16/17 cluster upgrade for Phase 2 (out of this plan).
- **HTMX learning curve** if dev team is React-first. Budget 1 day for HTMX onboarding inside Phase 01.

## Conventions
- File naming: kebab-case for Python modules.
- Commits: Conventional Commits (`feat:`, `fix:`, `chore:`, `refactor:`, `test:`, `docs:`).
- Branch: feature branches off `main`, squash-merge.
- Migrations: Alembic, one revision per logical change, never edit historical revisions.
- Tests: pytest, ≥70% coverage on `app/services/` and `app/import/` by Phase 12.

## Definition of Done (each phase)

A phase is **done** only when all that apply are true:

- Code for the phase is implemented and merged.
- Automated tests pass (`pytest` / phase-specific tests).
- Alembic migrations applied on a clean DB if the phase introduces or changes schema.
- `README.md` or ops docs updated when behavior, env vars, or runbooks change.
- Security-sensitive routes have RBAC, CSRF, and rate limits **when this phase owns those routes** (full matrix completed in Phase 09).
- Admin mutations in scope include **`audit_log_writer.write()` in the same DB transaction** when applicable.
- At least one **manual verification** command or checklist step recorded (e.g. curl `/healthz`, smoke UI path).
- No **undocumented** known blockers left for the next phase (if any, list in phase file or PR).

## How to Use This Plan
1. Work phases sequentially unless marked parallel-OK.
2. Each phase has a Todo checklist — tick items as completed.
3. Update phase frontmatter `status` field as work progresses.
4. After each phase, update `## Plan List` table in this file with completion date.
5. When Phase 12 exit criteria are met, archive this plan and start Phase 2 planning.
