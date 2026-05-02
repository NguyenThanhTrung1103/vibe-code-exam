---
title: Phase 16a — Admin Community Tab (read-only)
status: in_progress (Sprint-1-lite, read-only — 2026-05-02)
priority: high (Sprint-1 ship target)
effort: ~2.5 hours (refined scope; see refined plan)
depends_on: phase-13-discussion-url-parser.md (schema migration applied — DONE 2026-05-02 08:52)
parallel_ok: from day 2 of Phase 13 using fixture data
refined_plan: ../../reports/phase-16a-260502-0903-readonly-refined-plan.md
---

> **2026-05-02 scope reduction**: This plan originally included an "Ignore"
> mutation, a review-queue route, audit emissions, HTMX swaps, and CSRF
> protection. The implementation taken on 2026-05-02 is a strict read-only
> tab only — no Ignore action, no review queue, no audit emissions.
> The dropped features are deferred to Phase 16b. Refined plan:
> [`../../reports/phase-16a-260502-0903-readonly-refined-plan.md`](../../reports/phase-16a-260502-0903-readonly-refined-plan.md).

# Phase 16a — Admin Community Tab (read-only)

## Context links
- Plan overview: [`plan.md`](plan.md)
- Phase 13: [`phase-13-discussion-url-parser.md`](phase-13-discussion-url-parser.md)
- Design doc v2 §8: [`../NewPRD.md`](../NewPRD.md)
- Existing admin questions router: [`../../app/routers/admin/questions.py`](../../app/routers/admin/questions.py)
- Existing CSRF helper Phase 03: [`../../app/auth/csrf.py`](../../app/auth/csrf.py) (assumed path; verify in code)
- Existing admin templates: [`../../app/templates/admin/`](../../app/templates/admin/)

## Overview

**Priority:** High — Sprint-1 ship target.

**Brief:** Admin question detail page có thêm tab "Community Discussion" hiển thị community signal **read-only** + 1 action button "Ignore". Không có refetch, reanalyze, approve, unapprove (Phase 16b later).

**Goal Sprint-1:** đo admin engagement với community signal trên real Beta-A → quyết định trigger Sprint-2 (Phase 14 fetcher) hay không.

## Key insights

1. Sprint-1 = read-only ship target → giữ UI tối thiểu, đo phản hồi.
2. Phase 13 chỉ parse từ import; không có fetch nên `fetch_status` luôn `pending` cho data từ Phase 13. Tab vẫn hiển thị given_answer + vote distribution (đã có trong CDS row) + source URL — đủ để admin đánh giá signal mà không cần fetcher.
3. Ignore action = single mutation → audit emission + 1 RBAC + 1 CSRF check pattern.
4. Review queue list = bất kỳ CDS row nào với `needs_review=true` (sẽ là 0 trong Sprint-1 vì rule-based analyzer chưa ship — list rỗng hoặc chỉ hiển thị `answer_conflict=true` derived from import logic).
5. KHÔNG render summary HTML / markdown trong Sprint-1 → tránh stored XSS risk; plain text only.
6. Pagination LIMIT 50 mặc định cho review queue → ngăn DoS (red-team operational).

## Requirements

### Functional
- `GET /admin/questions/{id}/community` — render community tab cho 1 question; show all CDS rows (1 per source).
- Tab hiển thị: given_answer, community_answer (nếu có from import), vote distribution bar, source URL (nofollow), `fetch_status` badge, trust badge "Community Signal — not authoritative", conflict warning nếu `answer_conflict=true`.
- `POST /admin/community-sources/{id}/ignore` — toggle `ignored=true`, audit emission, redirect back hoặc HTMX swap.
- `GET /admin/community-review-queue` — paginated list of CDS rows where `needs_review=true OR answer_conflict=true AND ignored=false`. ORDER BY same as Phase 17 spec.
- All POST routes CSRF-protected (existing Phase 03 helper; verify HTMX header coverage).
- All routes RequireAdmin RBAC.
- Per-route rate-limit 5 req/min on POST.

### Non-functional
- Tab render p95 < 200ms (single query + 1 join).
- Review queue pagination LIMIT 50.
- HTMX for in-place updates (ignore button → swap card).
- Audit emission for every action.
- Coverage ≥80% on new router + service modules.

### Out of scope (Sprint-1)
- Refetch / reanalyze / approve / unapprove / mark-reviewed (Phase 16b).
- Student-facing community panel.
- Confidence-driven re-sorting (Phase 17).
- Manual official-reference (Phase 18).
- Common arguments table render (Ollama only — Appendix A).

## Architecture

### Routes

| Method | Path | RBAC | CSRF | Rate-limit | Notes |
|---|---|---|---|---|---|
| GET | `/admin/questions/{id}/community` | RequireAdmin | n/a | default | Community tab view |
| POST | `/admin/community-sources/{id}/ignore` | RequireAdmin | required | 5/min | Toggle ignored=true |
| GET | `/admin/community-review-queue` | RequireAdmin | n/a | default | Paginated list |

### CSRF + HTMX coverage

POST `/ignore`:
- Form submit: `<form hx-post="..." hx-target="#cds-card-{id}">` với hidden `<input name="csrf_token" value="{{ csrf_token }}">`.
- HTMX header: `<form hx-headers='{"X-CSRF-Token": "{{ csrf_token }}"}'>` AS WELL.
- CSRF helper kiểm tra cả form field VÀ header (defense-in-depth, red-team #13).

### Templates

- `templates/admin/questions/community_tab.html` — full page tab (extends `admin/_layout.html` if exists).
- `templates/admin/questions/_community_summary_card.html` — partial card for 1 CDS row (HTMX swap target).
- `templates/admin/community/review_queue.html` — review queue list with pagination.
- `templates/admin/community/_review_queue_row.html` — partial row.

### Service layer

- `app/services/community_admin_service.py` — read-only queries + ignore mutation.
  - `get_community_sources_for_question(session, question_id) -> list[CDS]`
  - `get_review_queue(session, page, page_size=50) -> tuple[list[CDS], total_count]`
  - `ignore_community_source(session, cds_id, actor_id, request_id) -> CDS` (audit emission)

## Related code files

### Files to MODIFY
- `app/routers/admin/__init__.py` — register new router(s).
- `app/routers/admin/questions.py` — link to community tab from question detail page (sidebar / tab nav).
- `app/audit/events.py` — add `AuditAction.community_source.ignored`, `community_source.unignored`.

### Files to CREATE
- `app/routers/admin/community_sources.py` — Phase 16a routes (3 routes).
- `app/services/community_admin_service.py` — read + ignore service.
- `app/schemas/community.py` (extend) — admin form schemas (`IgnoreSourceForm` if needed).
- `app/templates/admin/questions/community_tab.html`
- `app/templates/admin/questions/_community_summary_card.html`
- `app/templates/admin/community/review_queue.html`
- `app/templates/admin/community/_review_queue_row.html`
- `tests/routers/admin/test_community_sources.py` — RBAC + CSRF + audit emission.
- `tests/services/test_community_admin_service.py` — read + ignore unit tests.
- `tests/templates/test_community_tab_render.py` — snapshot 4 trạng thái card.

### Files to DELETE
- None.

## Implementation steps

1. **Verify Phase 13 schema migration applied** (`alembic upgrade head` → CDS table exists).
2. **Service layer:**
   1. Create `app/services/community_admin_service.py`:
      - `get_community_sources_for_question(session, question_id)` — SELECT all CDS WHERE question_id=? AND ignored=false ORDER BY source_name, created_at.
      - `get_review_queue(session, page, page_size=50, total_count_cap=10000)` — SELECT WHERE (needs_review=true OR answer_conflict=true) AND ignored=false, paginated.
      - `ignore_community_source(session, cds_id, actor, request_id)` — UPDATE ignored=true, audit emission, return updated row.
3. **Audit events:**
   - Add 2 actions: `community_source.ignored`, `community_source.unignored` (unignored unused in Sprint-1 but added for symmetry).
4. **Router:**
   1. Create `app/routers/admin/community_sources.py`:
      - `GET /admin/questions/{id}/community` → `templates/admin/questions/community_tab.html`.
      - `POST /admin/community-sources/{id}/ignore` → service.ignore + HTMX swap response or redirect.
      - `GET /admin/community-review-queue` → `templates/admin/community/review_queue.html`.
   2. Register router in `app/routers/admin/__init__.py`.
5. **Templates:**
   1. `community_tab.html` — header (question reference) + per-source cards.
   2. `_community_summary_card.html` — given_answer + community_answer + vote bar (CSS) + source URL (rel="noopener noreferrer nofollow") + trust badge + conflict warning + ignore button (HTMX).
   3. `review_queue.html` — pagination controls + list of cards.
   4. Plain text rendering only (`{{ value }}` autoescape) — NO markdown filter on summary in Sprint-1 (defer to Phase 16b after sanitization design).
6. **Question detail integration:**
   - Add tab link in existing question admin detail page (Phase 06): "Community" tab pointing to new route.
7. **Tests:**
   1. Service: 6 cases (no sources, 1 source, multiple sources, ignored excluded, review queue filter, pagination).
   2. Router: RBAC (anon → 401, student → 403, admin → 200), CSRF (no token → 403, valid → 200/302), rate-limit (6th req/min → 429), audit emission per ignore.
   3. Template snapshots: 4 states (agrees, disagrees, split/no_data, ignored).
8. **Manual smoke:**
   ```bash
   # Import 1 dump with discussion_url data (from Phase 13)
   # Open admin question detail
   # Click "Community" tab
   # Verify card renders correctly
   # Click "Ignore" → card greys out, audit log shows community_source.ignored
   # Open review queue → ignored row not listed
   ```
9. **Compile + lint + tests:**
   ```bash
   uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest
   ```

## Todo list
- [ ] Phase 13 done + schema migration applied
- [ ] `app/services/community_admin_service.py` — 3 functions
- [ ] `app/audit/events.py` — 2 new audit actions
- [ ] `app/routers/admin/community_sources.py` — 3 routes
- [ ] Templates: 4 files
- [ ] Tab link added to question admin detail page
- [ ] Tests: service (6 cases), router (RBAC + CSRF + rate-limit + audit), templates (4 snapshots)
- [ ] HTMX CSRF coverage verified (form field + X-CSRF-Token header both work)
- [ ] Manual smoke pass
- [ ] Lint + mypy + pytest green
- [ ] Audit query: `entity_type='community_source', action='community_source.ignored'` returns rows with admin actor_id

## Success criteria
- Admin opens `/admin/questions/{id}/community` → tab renders with all CDS rows for that question.
- Card hiển thị given vs community + vote bar + source URL + conflict warning (nếu có).
- "Ignore" button → POST → CDS `ignored=true` + audit row + HTMX swap (card greyed).
- Review queue list paginates with LIMIT 50; ignored rows excluded.
- All POST routes CSRF-protected; HTMX header alternative works.
- 0 raw HTML / markdown rendered (plain text only).
- Test coverage ≥80% on new modules.
- Manual smoke: import 1 dump → 5 questions visible community tab → ignore 2 → review queue shows 3.

## Risk assessment
- **Low:** Sprint-1 scope is intentionally minimal; few moving parts.
- **Medium:** HTMX + CSRF interaction footgun (red-team #13). Mitigation: explicit test for both form field AND header path.
- **Low:** Review queue empty in Sprint-1 (analyzer not shipped) → expected; UX message "No items to review yet" displayed.

## Security considerations
- RBAC: RequireAdmin on all 3 routes.
- CSRF: cả form field + `X-CSRF-Token` header để chống HTMX JSON content-type bypass.
- Rate-limit per-route 5 req/min on POST `/ignore`.
- Plain text rendering only on `summary`, `common_arguments` — no markdown / HTML in Sprint-1 (defer to Phase 16b after design).
- Source URL link: `rel="noopener noreferrer nofollow" target="_blank"`.
- Audit: every action emits `audit_log` row in same session as data mutation; `actor_id=current_admin.id`, `request_id` from middleware.
- No raw HTML stored from import (Phase 13 normalizer sanitizes via existing `bleach` pipeline + new `url_validator`).

## Next steps
After Phase 16a done → Sprint-1 ship → Beta-A admin trial → Gate-A1 evaluation:
- ≥1 admin completes 10+ community-signal reviews.
- Feedback collected: useful / not useful / want X.
- Decision point: trigger Sprint-2 (Phase 14 fetcher + Phase 15 analyzer) hay defer indefinitely.

If Sprint-2 triggered → write `phase-14-community-fetcher.md` + `phase-15-community-analyzer.md` in this same plan dir, append to `plan.md` table, update `docs/project-roadmap.md`.
