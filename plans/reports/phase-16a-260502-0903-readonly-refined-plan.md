---
title: Phase 16a — Admin Community Tab (read-only) — refined implementation plan
date: 2026-05-02 09:03 (Asia/Saigon)
plan: ../260430-2233-cdea-phase-13-16a/phase-16a-admin-community-tab-readonly.md
prior_reports: phase-13-260502-0753-completion.md, phase-13-260502-0806-step-d-lxc-isolated-plan.md, phase-13-260502-0829-prod-migration-plan.md
status: APPROVED — implementation in progress
scope: strict read-only admin community tab; no Ignore mutation; no review queue; no audit emission
---

# Phase 16a — Refined plan (Sprint-1-lite, read-only)

> Reduces the prior plan to a strict read-only admin tab — drops the Ignore action, the review queue, audit emissions, and HTMX. Single GET route + single template + tests.

## Scope (delta from `phase-16a-admin-community-tab-readonly.md`)

| Item | Original | Refined |
|---|---|---|
| `GET /admin/questions/{id}/community` | YES | KEEP |
| `POST /admin/community-sources/{id}/ignore` | YES | DROP |
| `GET /admin/community-review-queue` | YES | DROP |
| Audit `community_source.ignored / unignored` | YES | DROP |
| HTMX | YES | DROP |
| CSRF | YES | DROP (no POST) |
| RBAC RequireAdmin | YES | KEEP |
| Tab link from `/admin/questions/{id}/edit` | YES | KEEP |
| Plain text rendering | YES | KEEP |

## Refinements applied

1. **Service abstraction dropped.** SELECT inlined in router.
2. **Ordering** `community_confidence DESC, created_at DESC` (highest confidence first).
3. **Hard cap LIMIT 20** with truncation notice.
4. **Vote distribution** rendered as label/count/percent bars — never raw JSON.
5. **Template grouped** into 3 sections: Answer · Community Insight · Metadata.
6. **Performance**: column projection (13 columns), not full ORM row load.
7. **RTK** passthrough only (hook not installed).
8. **Skills** activated at code-time: `cook` first, then `backend-development`, `frontend-development`, `web-testing`, `git`.

## Files

CREATE:
- `app/routers/admin/community_sources.py`
- `app/templates/admin/questions/community_tab.html`
- `tests/test_community_vote_format_unit.py`
- `tests/routers/__init__.py`, `tests/routers/admin/__init__.py`
- `tests/routers/admin/test_community_tab.py` (real-DB-gated, skipped by default)

MODIFY:
- `app/main.py` — register the new router (the approved-list `app/routers/admin/__init__.py` is empty/no-op; main.py is the actual integration point, flagged as a minor deviation from scope wording but matches existing pattern).
- `app/templates/admin/questions/edit.html` — add `Edit | Community` tab strip.
- `plans/260430-2233-cdea-phase-13-16a/phase-16a-admin-community-tab-readonly.md` — status flip + scope-reduction note.

## Architecture

Single GET route returns HTML. Pure helper `format_vote_distribution()` lives at the top of the router file. Template renders 3 sections per CDS card. Empty state and 20-row truncation handled client-side in the template.

## Test layout

| File | Type | Coverage |
|---|---|---|
| `tests/test_community_vote_format_unit.py` | hermetic | helper purity (empty, single, multi, ties, pick flag, /0 edge) |
| `tests/routers/admin/test_community_tab.py` | real-DB-gated (`EXAM_PLATFORM_TEST_REAL_DB=1`) | RBAC, empty state, full render, 404, soft-delete, ordering, truncation |

Default suite stays hermetic. Real-DB-gated tests skip without the env flag.

## Boundaries

No student UI · no AI · no fetcher · no RQ · no DB schema change · no migration · no blogdb / blog role / /srv/blog-website / nginx / cloudflared / PG-config / Redis-config / blog.service touch · no service restart · no git push · no Phase 16b/14/15/17 work.

## Skills used at code-time

| Skill | Path | Why |
|---|---|---|
| cook | `.claude/skills/cook/SKILL.md` | Pre-feature gate per project rule |
| backend-development | `.claude/skills/backend-development/SKILL.md` | FastAPI router |
| frontend-development | `.claude/skills/frontend-development/SKILL.md` | Jinja templates |
| web-testing | `.claude/skills/web-testing/SKILL.md` | pytest TestClient pattern |
| git | `.claude/skills/git/SKILL.md` | Conventional commit (single end-of-phase commit) |
| development-rules | `.claude/rules/development-rules.md` | Files ≤200 LOC, no secrets |
| primary-workflow | `.claude/rules/primary-workflow.md` | Gate cycle |
| documentation-management | `.claude/rules/documentation-management.md` | Update existing plan in place |

## RTK

Hook NOT installed → passthrough. Streams that would benefit if installed: `pytest -v` (~80% saving), `pytest -q` (~83%), `mypy` (~80%). Safety-critical (errors, SQL queries, schema reads) NEVER compressed regardless.

## Effort

~2.5 hours including gate cycle.
