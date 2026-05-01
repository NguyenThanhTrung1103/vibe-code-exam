---
plan_id: 260430-2233-cdea-phase-13-16a
title: CDEA Sprint-1 — Phase 13 Discussion URL Parser + Phase 16a Admin Community Tab (read-only)
status: pending_implementation_approval
created_at: 2026-04-30
scope: MVP-cut Sprint-1 only. Phase 14/15/16b/17 NOT in this plan.
stack: FastAPI + PG14 + SQLAlchemy 2.0 + Alembic + Jinja2 + HTMX + bs4/lxml + Pydantic
deploy: existing Phase 1 LXC (single-host); no new infrastructure
parent_design_doc: ../NewPRD.md
red_team_review: ../reports/redteam-260430-2211-cdea-newprd.md
blockedBy: []
blocks: []
roadmap_position: Phase 1.5 (community signal); Phase 2/3 unchanged
---

# CDEA Sprint-1 Plan

> **Goal:** Ship Phase 13 (parser) + Phase 16a (read-only admin tab + ignore action) → measure admin engagement on real Beta-A → trigger Sprint-2 (Phase 14 fetcher) only on demand signal.

## Source documents
- Design doc v2: [`../NewPRD.md`](../NewPRD.md)
- Red-team review: [`../reports/redteam-260430-2211-cdea-newprd.md`](../reports/redteam-260430-2211-cdea-newprd.md)
- Roadmap deferral: [`../260428-1631-phase-1-mvp-exam-platform/roadmap-future-phases.md`](../260428-1631-phase-1-mvp-exam-platform/roadmap-future-phases.md)

## Phase list

| # | File | Effort (impl + 30%) | Status | Depends on |
|---|---|---|---|---|
| 0 | [pre-reqs.md](pre-reqs.md) | 0.5d | pending | Phase 12 complete (✓) |
| 13 | [phase-13-discussion-url-parser.md](phase-13-discussion-url-parser.md) | 3–4d | pending | Pre-reqs |
| 16a | [phase-16a-admin-community-tab-readonly.md](phase-16a-admin-community-tab-readonly.md) | 1–3d | pending | Phase 13 schema migration applied |

**Sprint-1 total:** 4–7 working days realistic.

## Out of scope (Sprint-1)
- Phase 14 community fetcher (httpx + RQ worker + SSRF guard)
- Phase 15 community analyzer (rule-based or Ollama)
- Phase 16b admin actions (refetch / reanalyze / approve-for-student / unapprove / mark-reviewed)
- Phase 17 confidence engine
- Student-facing community panel
- Manual official-reference CRUD (defer Phase 18)
- Ollama / 2-server infra (Appendix A — only after ≥50–100 real reviews show rule-based insufficient)
- Paid AI fallback (deleted from CDEA scope)

## Roadmap boundary
- CDEA Phase 13–16 = Phase 1.5 community-signal work.
- Phase 2 (deferred) = official docs / high-trust evidence / AI verification — NOT touched here.
- Phase 3 (deferred) = AI tutor / glossary / weak-topic / flashcards / spaced repetition — NOT touched here.
- CDEA must NOT duplicate or silently replace Phase 2/3 capability.

## Key dependencies
- Pre-reqs unblock Phase 13.
- Phase 13 schema migration unblocks Phase 16a.
- Phase 16a UI fixture-driven; can scaffold parallel from day 2 of Phase 13.

## Gate strategy
- **Gate-A1** (NEW, CDEA-specific): Sprint-1 ship + 1 admin completes ≥10 community-signal reviews + admin feedback collected.
- Gate-A1 must pass BEFORE any commitment to Phase 14/15/16b/17.
- Gate-B (public soft-launch) NOT dependent on CDEA — CDEA stays post-MVP/experimental.

## Definition of done (Sprint-1)
- Pre-reqs verified (deps installed, fixtures captured, `PARSER_SCHEMA_VERSION` defined).
- Phase 13 done criteria met (parser + schema + audit emission).
- Phase 16a done criteria met (read-only tab + ignore action + review queue list with pagination).
- Tests pass; coverage ≥80% on new modules.
- Docs updated: `docs/system-architecture.md` Phase 1.5 section, `docs/project-roadmap.md` table, `docs/community-signal-policy.md` created.
- Audit log emits all CDEA actions correctly (system-actor with RQ-job correlation where applicable).
- Manual smoke: admin imports 1 dump → opens community tab on 5 questions → ignores 2.

## How to use this plan
1. Run pre-reqs first (blocks Phase 13).
2. Phase 13 implementation + schema migration.
3. Phase 16a UI parallel from day 2 of Phase 13.
4. Run tests + manual smoke.
5. Update docs.
6. STOP — do not start Phase 14 until Gate-A1 passes.
