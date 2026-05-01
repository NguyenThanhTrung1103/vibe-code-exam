---
phase: 04
title: Catalog management — provider/course/exam/topic CRUD
status: pending
effort: 3-4 days
priority: high
depends_on: [03]
---

# Phase 04 — Catalog Management

## Context Links
- PRD §2 (catalog), §7.2 (`providers`, `product_versions`, `courses`, `exams`, `topics`), §24 (private-default visibility)
- Phase 03 (auth + audit log) must be in place

## Overview
Admin CRUD for providers, product_versions, courses, exams, topics. Public listing pages render only `publish_status='published'` exams. Slug generation, validation, soft-delete via `deleted_at`. All writes go through **`CatalogService` methods** (`create_*`, `update_*`, …) that call **`audit_log_writer.write()` in the same transaction** — same pattern as Phase 03 (no mandatory single function named `mutate()`).

## Key Insights
- Catalog is read-heavy on the public side, write-light on the admin side. Cache nothing yet (premature); add cache only if a slow page forces it.
- `product_versions` is wired now even though Phase 1 mostly ignores it — Phase 2's AI verifier will use `documentation_base_url`. Keeps schema stable.
- **Slug generation** uses `python-slugify`; uniqueness scoped to parent (provider slug unique globally; course slug unique per provider; exam slug unique per course).
- **Visibility scope:** Phase 1 — `private` (default) and `published`. `archived` is wired but rarely used until Phase 2.
- **Topics** are simple flat per-exam in MVP. No nested topics, no sub-topics. Weight is optional (used in topic-breakdown stats; defaults to 1).

## Requirements
**Functional**
- Admin pages: `/admin/providers`, `/admin/courses`, `/admin/exams`, `/admin/topics`, `/admin/product-versions`.
- Each entity: list / create / edit / soft-delete / publish-toggle (where applicable).
- Public pages: `/`, `/vendors`, `/vendors/{provider-slug}`, `/exams/{provider-slug}/{exam-slug}`. Show only `published`.
- Exam detail public page shows: code, name, description, question count (published only), topic list, time_limit, passing_score, last_verified_at, "Start Practice" CTA.
- Search bar (basic) on `/` filters provider name + exam code/name. Use Postgres `ILIKE` on indexed columns; no full-text yet.

**Non-functional**
- Admin form uses HTMX `hx-post` → returns partial template fragment on success/error; full page reload only on first GET.
- Slugs URL-safe and stable (don't auto-update on rename without confirmation).
- Public pages render in <300 ms p95 with 1k exams seeded.

## Architecture

```
app/
├── routers/
│   ├── public/
│   │   ├── home.py
│   │   ├── vendors.py             # /vendors and /vendors/{slug}
│   │   └── exams.py               # /exams/{provider-slug}/{exam-slug}
│   └── admin/
│       ├── providers.py
│       ├── product_versions.py
│       ├── courses.py
│       ├── exams.py
│       └── topics.py
├── services/
│   └── catalog_service.py         # all CRUD funnels through here
├── templates/
│   ├── public/
│   │   ├── home.html
│   │   ├── vendor_list.html
│   │   ├── vendor_detail.html
│   │   └── exam_detail.html
│   └── admin/catalog/
│       ├── providers/list.html, _form.html, _row.html
│       ├── courses/...
│       └── exams/...
└── schemas/
    └── catalog.py                 # Pydantic input schemas + validators
```

### Service pattern (applies to all entities)
```python
class CatalogService:
    def create_provider(session, *, actor, name, slug, description) -> Provider: ...
    def update_provider(session, *, actor, provider_id, **changes) -> Provider: ...
    def soft_delete_provider(session, *, actor, provider_id) -> None: ...
    # all writes call audit.write() in same tx
```

## Related Code Files
**Create**
- `app/services/catalog_service.py`
- `app/schemas/catalog.py`
- `app/routers/public/{home,vendors,exams}.py`
- `app/routers/admin/{providers,product_versions,courses,exams,topics}.py`
- `app/templates/public/*.html`
- `app/templates/admin/catalog/**/*.html`
- `tests/test_catalog_service.py`, `tests/test_public_listing.py`, `tests/test_admin_catalog.py`

## Implementation Steps

1. **Pydantic schemas** for inputs (slug regex `^[a-z0-9-]+$`, length limits, required fields).
2. **`CatalogService`** — one class with create/update/soft-delete per entity. Each method: validate → apply SQL changes → **`audit_log_writer.write()`** → commit (single transaction).
3. **Admin routes** for each entity with HTMX patterns (post returns row partial; cancel returns row in read mode).
4. **Public home page** — hero, search input (server-rendered HTMX `hx-get="/search/exams"`), provider grid, "popular exams" (top by `attempts.count` — Phase 1 use total count; Phase 3 weighted).
5. **Vendor list page** — grid of providers with logo + course count.
6. **Vendor detail page** — list courses + their exams (published only). Group by course.
7. **Exam detail page** — metadata + topics + "Start Practice" CTA. Phase 1: clicking CTA goes directly to attempt creation in Phase 07/08.
8. **Search endpoint** — `ILIKE` against provider.name + exam.code + exam.name. Limit 20 results. Returns HTMX partial.
9. **Soft-delete handling** — exclude `deleted_at IS NOT NULL` everywhere via base query helper.
10. **Publish toggle** — admin clicks "Publish" → status flips, `last_verified_at = now()`, audit logged.
11. **Audit log entries** — every mutation: `entity_type='provider'`, action `provider.created`/`updated`/`soft_deleted`/`published`/`unpublished`, etc.
12. **Slug generation helper** — `slugify(name, max_length=64)`. Manual override allowed.
13. **Tests**: full CRUD for provider/exam, audit entries written, public pages exclude unpublished, search returns expected hits.

## Todo List
- [ ] Slug generation + validation
- [ ] Provider/Course/Exam/Topic/ProductVersion CRUD
- [ ] CatalogService funnels all writes through audit log
- [ ] Public home + vendor list + vendor detail + exam detail
- [ ] Admin pages with HTMX form interactions
- [ ] Search endpoint (ILIKE) returning HTMX partial
- [ ] Soft-delete excludes from all queries
- [ ] Publish/unpublish toggles and audit them
- [ ] Tests: CRUD + audit + public visibility filters
- [ ] No unpublished content visible on public routes

## Success Criteria
- Admin can create Fortinet provider → NSE course → NSE4 exam → 4 topics in <2 minutes via UI.
- Unpublished exam returns 404 on public detail route.
- Audit log shows all 7 writes with correct actor and entity_type.
- Search "NSE4" returns the exam in <100 ms.
- Soft-deleting a provider hides its courses/exams from public pages.

## Risk Assessment
- **Slug collision** on rename — handle via uniqueness constraint + clear error message.
- **Publishing partially-imported exam** (no questions yet) — allow it (admin's choice) but show warning banner.
- **Cascade soft-delete logic** is fiddly. Mitigate: soft-delete is per-entity; querying joins explicitly filter `deleted_at IS NULL`.

## Security Considerations
- All admin routes require `require_role("admin")`.
- All form POSTs validate CSRF token.
- Slug input sanitized (regex constraint).
- Description fields rendered through HTML sanitizer (Phase 09 hardens further).
- No HTML upload here — only text fields.

## Next Steps
Phase 05 — Excel import attaches questions to exams created here.
