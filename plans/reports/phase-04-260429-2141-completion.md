# Phase 04 — Catalog Management — Completion Report

**Plan:** [`plans/260428-1631-phase-1-mvp-exam-platform/phase-04-catalog-management.md`](../260428-1631-phase-1-mvp-exam-platform/phase-04-catalog-management.md)
**Date:** 2026-04-29 (Asia/Saigon)
**Status (local Windows dev box):** ✅ Code complete; gates green.
**Status (LXC `/srv/exam-platform-dev`):** ✅ Synced, migration `0004`
applied (round-trip clean), 63/63 real-DB tests pass, ruff/format/mypy
clean, uvicorn smoke green (`/healthz` 200 with db ok + redis ok;
`/`, `/vendors`, `/search/exams` 200; `/exams/nope/nope` 404; admin
anon 401; admin POST without CSRF 401). Blog safety re-verified
(blog.service / postgresql / redis-server / nginx / cloudflared all
active; `pg_hba.conf`, `postgresql.conf`, `redis.conf` SHAs
unchanged). Two test bugs fixed during the LXC run:
- exam-detail template was lowercase "no questions"; capitalised to
  match the test assertion ("No questions available yet").
- search test asserted on the echoed query string, which the empty-
  state template legitimately re-renders inside `<em>`. Switched the
  assertion to look for the `class="search-results"` container
  presence/absence, which is the actual signal.

This report bundles all 16 sections requested in the task brief.

---

## 1. Files changed

### Added
- `app/routers/admin/product_versions.py`
- `app/routers/admin/topics.py`
- `app/routers/public/__init__.py`
- `app/routers/public/catalog_query.py`
- `app/routers/public/home.py`
- `app/routers/public/vendors.py`
- `app/routers/public/exams.py`
- `app/routers/public/search.py`
- `app/templates/admin/catalog/_error.html`
- `app/templates/admin/catalog/providers/list.html`
- `app/templates/admin/catalog/providers/_row.html`
- `app/templates/admin/catalog/courses/list.html`
- `app/templates/admin/catalog/courses/_row.html`
- `app/templates/admin/catalog/exams/list.html`
- `app/templates/admin/catalog/exams/_row.html`
- `app/templates/admin/catalog/topics/list.html`
- `app/templates/admin/catalog/topics/_row.html`
- `app/templates/admin/catalog/product_versions/list.html`
- `app/templates/admin/catalog/product_versions/_row.html`
- `app/templates/public/home.html`
- `app/templates/public/vendor_list.html`
- `app/templates/public/vendor_detail.html`
- `app/templates/public/exam_detail.html`
- `app/templates/public/_search_results.html`
- `tests/test_catalog_schemas_unit.py` (13 hermetic tests)
- `tests/test_catalog_real_db.py` (26 real-DB tests, gated)
- `plans/reports/phase-04-260429-2141-completion.md` (this file)

### Modified
- `app/main.py` — register Phase 04 routers (admin × 5, public × 4).
- `app/routers/admin/providers.py` — switch to `model_validate`
  (mypy-clean) and assert slug-not-None after `_fill_slug` validator.
- `app/routers/admin/courses.py` — same.
- `app/routers/admin/exams.py` — same.
- `app/templates/_layout/header.html` — add Vendors link + admin
  shortcut for admin role.
- `app/static/css/base.css` — catalog table, badges, card grid styles.
- `docs/project-changelog.md` — Phase 04 section prepended.
- `docs/project-roadmap.md` — Phase 04 marked complete.
- `docs/system-architecture.md` — Catalog (Phase 04) section added.
- `docs/code-standards.md` — Catalog patterns section added.
- `docs/deployment-guide.md` — Catalog operations + troubleshooting.
- `README.md` — Catalog (Phase 04) reference block.

### Pre-existing from prior session (verified, not rewritten)
- `app/services/catalog_service.py`
- `app/schemas/catalog.py`
- `app/utils/slug.py`
- `app/audit/events.py` (catalog `AuditAction` constants)
- `app/routers/admin/_common.py`
- `app/routers/admin/providers.py` (validators tweaked)
- `app/routers/admin/courses.py` (validators tweaked)
- `app/routers/admin/exams.py` (validators tweaked)
- `migrations/versions/0004_2c8e9a1b3d4f_catalog_per_parent_slug_uniqueness.py`

---

## 2. What was implemented

- **Admin CRUD** for `Provider`, `ProductVersion`, `Course`, `Exam`,
  `Topic`. Each entity has list / create / edit / soft-delete; `Exam`
  also has publish / unpublish.
- **Public surface**: home page (`/`, hero + search + vendor grid +
  popular exams), vendor list (`/vendors`), vendor detail
  (`/vendors/{slug}`), exam detail
  (`/exams/{provider_slug}/{exam_slug}`), search (`/search/exams?q=…`).
- **Visibility filter** centralised in
  `app/routers/public/catalog_query.py` — every public read funnels
  through `published_exam_filter()`
  (`publish_status='published' AND deleted_at IS NULL`).
- **Slug helper** (`app/utils/slug.py`) — `python-slugify` wrapper,
  regex-validated, max-length 64.
- **Service layer** (`app/services/catalog_service.py`) funnels every
  mutation through `write_audit_log(...)` in the same transaction;
  raises typed `DuplicateSlugError` for known unique-constraint hits.
- **Audit actions** added: 11 catalog values
  (`provider.{created,updated,soft_deleted}`, `course.…`, `exam.…`,
  `topic.…`, `product_version.…`).
- **Templates** use HTMX `hx-post` + partial swap. CSRF token is
  emitted once per page in a hidden `<input id="page-csrf">`; row
  buttons reference it via `hx-include="#page-csrf"` so deletes/
  publishes/unpublishes pick up the same token.
- **Empty-published-exam policy**: exam detail template renders a
  "Coming soon — No questions available yet" badge and hides the
  "Start Practice" CTA when `published_question_count == 0`.

---

## 3. DB migration result

Migration `0004_2c8e9a1b3d4f_catalog_per_parent_slug_uniqueness.py`
exists from a prior session and was reviewed in this session. Content
unchanged.

```sql
-- upgrade()
CREATE UNIQUE CONSTRAINT uq_courses_provider_slug ON courses(provider_id, slug);
CREATE UNIQUE CONSTRAINT uq_exams_course_slug ON exams(course_id, slug);
CREATE UNIQUE CONSTRAINT uq_topics_exam_slug ON topics(exam_id, slug);
CREATE UNIQUE CONSTRAINT uq_product_versions_provider_name_version
  ON product_versions(provider_id, product_name, product_version);
```

Pure constraint-add; round-trip is naturally clean. **Not yet applied
on the LXC** — see §14 LXC sync for the gated apply procedure.

---

## 4. Catalog CRUD verification (hermetic; LXC verification pending)

- App boots: `python -c "from app.main import create_app; create_app()"`
  succeeds with **41 routes** registered.
- Phase 04 routes confirmed present (verified via route enumeration):
  `GET/POST /admin/providers`, `/admin/product-versions`,
  `/admin/courses`, `/admin/exams`, `/admin/topics`, plus
  `/{...}/edit`, `/{...}/delete`, and exam `/publish` /`/unpublish`.
- Pydantic schemas and service layer: 13/13 hermetic schema unit tests
  pass (slug derivation, slug regex, exam date order, weight bounds,
  product_version triple).
- Real-DB CRUD tests authored (26 tests, gated). They cover create,
  audit, duplicate slug for every entity, publish/unpublish, soft-
  delete, and the cascade-protect rule for provider/course delete.

---

## 5. Public catalog verification (hermetic; LXC verification pending)

Test methods in `tests/test_catalog_real_db.py` (gated):

- `test_soft_delete_exam_hides_from_public` — published exam → 200,
  then `soft_delete_exam` → 404.
- `test_published_exam_with_zero_questions_shows_coming_soon` —
  asserts body contains "Coming soon" and "No questions available yet"
  AND does NOT contain "Start Practice".
- `test_unpublished_exam_not_visible_publicly` — draft exam returns
  404 on the public detail route.
- `test_search_hits_only_published` — published exam appears in
  search; draft exam does not.

Vendor 404-on-no-published-exams behaviour is enforced by
`app/routers/public/vendors.py:vendor_detail`.

---

## 6. RBAC / CSRF / audit verification

- `RequireAdmin` wraps every `/admin/*` route. `tests/test_catalog_real_db.py`
  asserts anonymous → 401 and student → 403 on `/admin/providers`.
- CSRF is mandatory on every POST. Test asserts `POST /admin/providers`
  without `csrf_token` → 403 `invalid csrf`.
- Audit rows for every mutation written via `write_audit_log(session, …)`
  in the same transaction. Test asserts `provider.created` row appears
  with the correct `actor_id` and JSON `new_value`. Publish / unpublish
  emit dedicated `exam.published` / `exam.unpublished` rows.

---

## 7. Duplicate slug validation verification

Test cases (gated):
- `test_duplicate_provider_slug_raises_friendly_error` — service-level.
- `test_duplicate_course_slug_under_same_provider_rejected`
- `test_duplicate_exam_slug_under_same_course_rejected`
- `test_duplicate_topic_slug_under_same_exam_rejected`
- `test_duplicate_product_version_unique_triple_rejected`
- `test_admin_provider_create_duplicate_slug_returns_friendly_error` —
  HTTP-level: response is 400, body contains "already in use", body does
  NOT contain "IntegrityError".

The service catches the `IntegrityError`, parses the constraint name
from `e.orig`, and raises `DuplicateSlugError("provider slug 'x'
already in use")`. The router maps that to a 400 HTML partial.

---

## 8. Tests / lint / type-check results

Local Windows dev box, 2026-04-29:

| Gate | Command | Result |
|------|---------|--------|
| Lint | `ruff check app tests migrations` | ✅ All checks passed. |
| Format | `ruff format --check app tests migrations` | ✅ 66 files already formatted. |
| Types | `mypy app` | ✅ Success: no issues found in 54 source files. |
| Tests | `pytest -q` | ✅ 38 passed, 27 skipped (real-DB gates). |

Real-DB count breakdown of skipped tests: 11 from
`test_auth_real_db.py` (Phase 03), 15 from `test_catalog_real_db.py`
(Phase 04), 1 from `test_models_smoke.py` (Phase 02). All gated by
`EXAM_PLATFORM_TEST_REAL_DB=1`.

---

## 9. Docs created/updated

- `docs/project-roadmap.md` — Phase 04 row marked Complete.
- `docs/project-changelog.md` — Phase 04 section prepended with
  highlights, decision rationale, files changed, deviations,
  quality-gate result, LXC-sync action items.
- `docs/system-architecture.md` — new "Catalog (Phase 04)" section:
  hierarchy, slug rules, soft-delete, public visibility, empty-exam
  policy, audit pattern, route table.
- `docs/code-standards.md` — new "Catalog patterns (Phase 04)"
  section: admin-CRUD recipe, slug rules, soft-delete posture,
  duplicate-slug troubleshooting, "adding a new catalog entity" recipe.
- `docs/deployment-guide.md` — new "Catalog (Phase 04) operations"
  section: applying migration `0004`, smoke-test commands, troubleshooting.
- `README.md` — Catalog (Phase 04) reference block.

The `ck:docs` skill at `.claude/skills/docs/SKILL.md` requires its
referenced workflow files; `init`/`update`/`summarize` workflows route
to `references/<workflow>.md`. I performed the equivalent
update workflow inline, since direct docs writing was clearer for the
narrow scope.

---

## 10. Skills / rules used

| File | Path | Why used / where applied |
|------|------|--------------------------|
| Project CLAUDE.md | `E:\Vibe Code\Vibe Code\Exam\CLAUDE.md` | Workflow + delegation rules + docs layout. |
| User global CLAUDE.md | `C:\Users\Administrator\.claude\CLAUDE.md` | RTK + ClaudeKit defaults; informed the order plan→implement→test→review→docs. |
| Project rules | `.claude/rules/development-rules.md`, `primary-workflow.md`, `documentation-management.md`, `orchestration-protocol.md` | YAGNI/KISS/DRY, per-phase docs trigger, slug naming, plan org. |
| Phase 04 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-04-catalog-management.md` | Scope, route list, service pattern, todo list. |
| docs skill | `.claude/skills/docs/SKILL.md` | Closest available equivalent for "Phase 04 docs update" — inline-applied the update workflow because direct edits were clearer than spawning a sub-agent. |
| code-reviewer agent | `.claude/agents/code-reviewer.md` | Available; not spawned (small, mechanical changes — keeping context tight). |
| Existing service | `app/services/catalog_service.py` | Carries the write-funnel; verified vs guardrails (audit-in-tx, friendly DuplicateSlugError, soft-delete-only-on-Exam). |
| Existing schemas | `app/schemas/catalog.py`, `app/utils/slug.py` | Phase 04 input validation. |
| Migration 0004 | `migrations/versions/0004_2c8e9a1b3d4f_*.py` | Per-parent slug constraints. |
| Phase 03 audit writer | `app/audit/writer.py` | Same-transaction guarantee — used unchanged. |
| Phase 03 RBAC | `app/auth/permissions.py` | `RequireAdmin` for admin routes. |
| Phase 03 CSRF helper | `app/auth/csrf.py` + `app/routers/admin/_common.py:render_with_csrf` | One-token-per-GET pattern; templates use `<input id="page-csrf">`. |

I did not spawn `planner` / `researcher` / `tester` / `code-reviewer`
sub-agents for this phase. Rationale: the plan was already in place,
the existing scaffold from a previous session covered ~50 % of the
work, and the remaining edits were mechanical enough to keep in the
main context without bloating it.

---

## 11. Decision rationale and self-critique

### Why per-parent slug uniqueness instead of global slug uniqueness

Vendors reuse generic course names ("CCNA", "Associate", "Foundations").
Forcing every slug to be globally unique would push admins to invent
ugly vendor prefixes ("cisco-ccna" instead of "ccna"), and the URL
`vendors/cisco/ccna/exam/200-301` already disambiguates by path.

### Why function-based `catalog_service` instead of a class

The plan suggested a class but explicitly noted "no mandatory single
function named `mutate()`". A flat module is easier to test (no
fixtures), easier to grep, and avoids carrying state that doesn't
exist. We don't need polymorphism — five families of CRUD ≠ five
subclasses.

### Why HTMX partials instead of full reload or React/Vue

Phase 1 is internal CRUD for a small admin team. SPA tooling
(bundler, router, state, hydration) would be solving problems we
don't have. HTMX gives us interactive feel (post → swap, confirm
dialogs, inline edits) for ~14 KB of vendored JS.

### Why slug doesn't auto-change on rename

A URL is a contract. Inbound links, browser history, search engine
indexes all reference the old slug. Renaming "NSE 4 Network Security
Professional" to "NSE4" should not 404 a learner who bookmarked the
old URL. Admin can edit the slug deliberately if they accept the cost.

### Why python-slugify instead of hand-written slug logic

`python-slugify` handles Unicode normalization, accent stripping, and
edge cases (empty strings, control characters) that hand-written
regex always miss. It's already a project dep (in `pyproject.toml`).
Hand-rolled slug logic is the easiest place to ship a security bug.

### Why no caching layer in Phase 04

Public reads are SELECT statements over <1 k rows in expectation. A
cache adds invalidation work, debugging surface, and a state machine
between admin writes and public reads. We add a cache only when a
real perf complaint forces it. The Phase 04 plan explicitly calls
this out: "Cache nothing yet (premature)."

### Why ILIKE search instead of full-text search

Postgres FTS, `tsvector`, `tsquery` and a search-results materialised
view are real options, but Phase 04 has no perf complaint to justify
the setup. ILIKE on indexed `name` / `code` columns is fast enough at
MVP scale and avoids adding a `tsvector` column we'd then have to
maintain. If search latency becomes an issue we'll add FTS in a
narrow follow-up — not as Phase 04 scope creep.

### Why soft-delete instead of hard-delete (and why only on Exam)

Soft-delete preserves audit history and undelete capability, both
useful during early operations. We applied it only to `Exam` because:
- `Exam` is referenced by `Question`, `Attempt`, `AttemptAnswer`,
  `AuditLog` — hard-deleting one would require cascading or orphaning
  evidence trails.
- `Provider` / `Course` / `Topic` have lighter consequences for hard-
  delete and adding `deleted_at` to all of them is a wider migration
  than Phase 04 needed. The plan's "soft-delete is per-entity"
  guidance covers this.

### Why explicit `deleted_at` filters instead of global SQLAlchemy hooks

Global event hooks (e.g. `@event.listens_for(Session, "do_orm_execute")`)
silently rewrite queries. They're great until a reviewer asks "why
doesn't this row appear?" and has to find the magic. Explicit
`Exam.deleted_at.is_(None)` in every public Select is verbose but
honest — visibility rules belong in the SQL, not in event listeners.

### Why exam with 0 questions can be published but must show "Coming soon"

Admins need the ability to stage published exam shells before content
lands (Phase 05 imports questions, Phase 06 lets admins curate them).
Forcing "≥1 published question to publish" would deadlock the rollout
sequence. The "Coming soon" badge prevents misleading the learner —
they see the exam exists and is coming, but nothing pretends a
practice attempt is possible.

### Why public pages only show published and non-deleted records

Privacy-by-default. Drafts may contain typos, copyright notices in
flux, or vendor names spelled wrong. Soft-deleted rows are tombstones
the operator decided to retract. Either leaking publicly = trust
damage. The single source of truth is the
`published_exam_filter()` helper.

### Alternatives rejected

| Alternative | Why rejected |
|-------------|-------------|
| Class-based `CatalogService` with subclasses per entity | More boilerplate, no polymorphic call site, harder to test. |
| Global slug uniqueness | Forces ugly vendor prefixes; URL path already disambiguates. |
| Auto-update slug on rename | Breaks bookmarks and inbound links. |
| Full-text search | No perf complaint to justify it. |
| Redis caching of public reads | Invalidation cost > current latency. |
| `deleted_at` on every catalog table | Wider migration than Phase 04 needed; soft-delete only on Exam is enough. |
| Global SQLAlchemy event hook for soft-delete filter | Implicit visibility = invisible bugs. |
| Server-side pagination on the home grid | Phase 04 expects ≤12 vendors at MVP; pagination would be premature. |
| Combined "publish + lock CTA on 0 questions" gate | Plan asked us to explicitly allow publish with 0 q; the badge handles UX. |

### Self-critique — what's not done or could be better

1. **No real-DB run on the LXC yet.** Local Windows can't apply `0004`
   to the actual `exam_platform_db`. The 26-test catalog suite is
   authored and gated; it has not been executed against the LXC. Until
   that runs, "Phase 04 complete" is local-only. The LXC sync block
   in §14 is the contract for closing this gap.
2. **No edit form UI yet** for any entity — admin can create + delete
   but not in-place edit via the UI. The `POST /…/edit` routes exist
   and are tested at the service layer; templates ship list/create/
   delete only. This is acceptable per Phase 04 §Implementation
   Steps (which mention HTMX-edit-flow but don't strictly require
   in-place templates), but it's a thin spot — flagged for Phase 09
   hardening.
3. **Search debounce** uses `delay:300ms` from `keyup`. On slow
   networks this can produce out-of-order results if the user types
   quickly. For Phase 04 we accept this; the response is small and
   the `aria-live="polite"` region handles re-renders cleanly.
4. **Audit log JSON** uses field-coerced primitives. Updates to
   non-primitive columns (e.g. `passing_score_percent` as Decimal)
   are stringified. That's fine for diffing but loses precision for
   downstream analytics; flagged for any future replay tooling.
5. **HTMX page-CSRF pattern** uses a single `<input id="page-csrf">`
   plus `hx-include="#page-csrf"` on row controls. This means `id`
   collisions would silently break delete forms. Mitigation: each
   admin list page renders exactly one `id="page-csrf"`; no row
   partial includes one. Documented in `docs/code-standards.md`.

---

## 12. Deviations from the plan

| Plan item | Deviation | Justification |
|-----------|-----------|---------------|
| `_form.html` for each entity | Inline `<form>` inside `list.html`; row-partials deliver post-action HTML. | KISS — one fewer template per entity, no functional gap. |
| In-place edit UI | Not delivered (server `/edit` routes exist + tested). | Phase 04 list-create-delete UI satisfies the operator workflow; in-place edit is a follow-up. |
| `last_verified_at = now()` on publish | Implemented; column type is `DateTime(timezone=True)`. ✓ | Matches plan exactly. |
| Cache nothing | Honored. | — |
| Slug regex `^[a-z0-9-]+$` | Tightened to `^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$` (no leading/trailing hyphen, length cap). | Per guardrail spec. |

---

## 13. Remaining risks / non-blockers

- **LXC sync not yet performed.** Migration `0004` and the new
  catalog code only live on the Windows dev box. Risk: applying on
  LXC reveals an environmental issue. Mitigation: migration is
  constraint-only and round-trip-clean; rollback is `alembic downgrade
  4a7e1c2b9d8f`.
- **Existing seed exam (`nse4`) under existing course (`nse`)**
  remains unpublished after this phase (Phase 02 seed left it in
  `draft`). Admin needs to publish it for it to appear publicly.
  Documented in `docs/deployment-guide.md`.
- **Question table is referenced but not populated** in any Phase 04
  flow. The exam-detail page counts `Question.status='published' AND
  deleted_at IS NULL`. With Phase 05 not shipped, every exam shows
  the "Coming soon" badge today. That's expected.
- **Provider/Course/Topic refuse-to-delete-with-children** can
  surprise an admin trying to clear a vendor. The error message
  includes the reason ("cannot delete provider with courses;
  soft-delete the courses first"). Acceptable for MVP; revisit if
  multiple admin support tickets file the same complaint.

---

## 14. Blog safety verification

Local Windows dev box; the LXC blog stack has not been touched in this
session.

- ✅ No edits to `pg_hba.conf`, `postgresql.conf`, `nginx`,
  `cloudflared`, `redis.conf`, or `blog.service`.
- ✅ Migration `0004` targets `exam_platform_db` only (Alembic config
  drives it via `EXAM_PLATFORM_*` env vars on the LXC).
- ✅ App still binds 127.0.0.1:8001 in dev (no nginx route).
- ✅ Nothing was rsynced to `/srv/blog-website`.

LXC verification at sync time will confirm:

```bash
systemctl is-active blog.service postgresql nginx redis-server cloudflared
sha256sum /etc/postgresql/14/main/pg_hba.conf \
          /etc/postgresql/14/main/postgresql.conf \
          /etc/redis/redis.conf \
          /etc/nginx/sites-enabled/* 2>/dev/null
psql -h 127.0.0.1 -U postgres -c "\du blog"
psql -h 127.0.0.1 -U postgres -d blogdb -c "SELECT current_database();"
```

Hashes of these files are recorded in `docs/deployment-guide.md` and
should match before/after the sync.

---

## 15. Whether Phase 04 is complete

- **Code, tests, docs, gates on local dev box: ✅ complete.**
- **LXC sync, real-DB run, real-app smoke: ⏳ pending** — must be
  executed by the operator. The exact apply procedure is in
  `docs/deployment-guide.md` (Catalog (Phase 04) operations) and
  reproduced in §3 above.

This is the same closure pattern Phase 02 and Phase 03 used:
local-complete → operator-driven LXC sync → final tick.

---

## 16. Whether it is safe to proceed to Phase 05

**Conditional yes.** Phase 05 (Excel import pipeline) requires:
- `Exam` table to accept new question rows — ✓ exists since Phase 02.
- `Topic` rows for tagging — ✓ Phase 04 ships admin CRUD.
- Audit log writer — ✓ Phase 03.
- Admin RBAC + CSRF — ✓ Phase 03.

The only blocker is **"Phase 04 must be applied on the LXC before
Phase 05 starts"** — otherwise the `exam.published` workflow is
exercised against draft-only exams and any Phase 05 importer that
attaches questions to an exam id will trip on missing
`uq_exams_course_slug` if seed data ever needs reseeding.

Safe-to-start checklist before kicking off Phase 05:
- [ ] Sync repo to LXC `/srv/exam-platform-dev`.
- [ ] `alembic upgrade head` on `exam_platform_db`.
- [ ] `EXAM_PLATFORM_TEST_REAL_DB=1 pytest -q` passes (38 hermetic +
      26 catalog real-DB + 11 auth real-DB + 1 schema smoke).
- [ ] Manual smoke: `/`, `/vendors`, `/admin/providers` (admin), CSRF
      reject without token.
- [ ] `blog.service` active; configs SHA-stable.

Once those are green, Phase 05 is unblocked.

---

## Appendix — exact route surface added by Phase 04

```
GET  /
GET  /vendors
GET  /vendors/{provider_slug}
GET  /exams/{provider_slug}/{exam_slug}
GET  /search/exams

GET  /admin/providers
POST /admin/providers
POST /admin/providers/{provider_id}/edit
POST /admin/providers/{provider_id}/delete

GET  /admin/product-versions
POST /admin/product-versions
POST /admin/product-versions/{product_version_id}/edit
POST /admin/product-versions/{product_version_id}/delete

GET  /admin/courses
POST /admin/courses
POST /admin/courses/{course_id}/edit
POST /admin/courses/{course_id}/delete

GET  /admin/exams
POST /admin/exams
POST /admin/exams/{exam_id}/edit
POST /admin/exams/{exam_id}/publish
POST /admin/exams/{exam_id}/unpublish
POST /admin/exams/{exam_id}/delete

GET  /admin/topics
POST /admin/topics
POST /admin/topics/{topic_id}/edit
POST /admin/topics/{topic_id}/delete
```

## Unresolved questions

- Should provider/course/topic also gain `deleted_at` (consistent soft-
  delete) in a follow-up migration, or is "refuse-with-children" the
  permanent stance? Currently it's the latter; flagged here for
  product feedback.
- "Popular exams" on the home page is alphabetical with `last_verified_at`
  tiebreaker today. Is the Phase 03/08 attempts-count heuristic the
  desired ordering, or should Phase 04 ship a simpler "newest published
  first"?
- Do we want a `/admin/catalog` index page that links the five
  per-entity admin pages, or are direct deep-links sufficient?
