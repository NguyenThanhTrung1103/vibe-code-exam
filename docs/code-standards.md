# Code Standards

Practical rules for the exam-platform codebase. Concise; expanded only
when a phase introduces a new pattern.

## File naming

- **Python modules:** snake_case per PEP 8 (e.g. `redis_client.py`,
  `health.py`). Imports use these names verbatim.
- **Shell / generic JS/TS / non-Python:** kebab-case with descriptive
  names (e.g. `db-setup.sh` locally; on-server we keep the plan's name
  `db_setup.sh`).
- **Templates / static / config / markdown:** descriptive names; long is
  fine — LLM tooling reads file names.

## Per-file size discipline

- **Target ≤ 200 LOC** per Python module. Split when a file exceeds 200
  lines or holds >1 logical concern.
- ORM-model files routinely exceed 200 because each file is one logical
  area (e.g. `catalog.py`). That's fine — the cap is a heuristic, not a
  rule.

## Imports

- `from __future__ import annotations` at the top of every Python file.
- Group: stdlib → third-party → first-party (`app.*`).
- Sorted within groups (ruff handles this; don't fight it).
- Re-exports go in `__init__.py` only.

## Configuration

- One source: `app/config.py` `Settings(BaseSettings)`.
- Read via `get_settings()` (cached).
- **Never** call `os.getenv` outside `config.py`.
- Add new env vars to `.env.example` AND `Settings`.

## Database

- All ORM models inherit from `app.models.base.Base`.
- Use SQLAlchemy 2.0 `Mapped[...]` + `mapped_column(...)` style.
- Columns have explicit nullability (`nullable=True/False`).
- ENUMs are native PG types declared in `app/models/enums.py` (StrEnum
  + a unique `name=` per type).
- FK on-delete: default `RESTRICT`. Document any `CASCADE` / `SET NULL`
  with a comment explaining why.
- Soft-delete tables include `deleted_at TIMESTAMPTZ NULL` via
  `SoftDeleteMixin` (only when the PRD lists `deleted_at`).
- **No DDL outside Alembic** — even tiny changes go through a revision.

## Migrations (Alembic)

- One revision per logical change.
- Filename pattern: `<NNNN>_<random>_<kebab-case-slug>.py` (the
  numeric prefix is for human chronology).
- After autogenerate **always** review:
  - duplicate `CREATE TYPE` for shared ENUMs → add `create_type=False`.
  - circular FKs → defer one edge to `op.create_foreign_key`.
  - downgrade must drop every ENUM type via explicit
    `op.execute("DROP TYPE IF EXISTS …")` — see
    `migrations/versions/0001_*.py` `_ENUM_TYPE_NAMES` pattern.
- Seed migrations: prefer `ON CONFLICT DO NOTHING` for tables with
  natural unique keys; `WHERE NOT EXISTS` (CTE) otherwise. Avoid
  `'val'::type` casts inside SQLAlchemy `text()` — clashes with
  `:param`. Use `CAST(:p AS type)`.

## Logging

- `from app.logging import get_logger`; `log = get_logger(__name__)`.
- Use structured fields, not f-strings: `log.info("event", key=value)`.
- Never log secrets, tokens, or full request bodies.
- `request_id` is bound automatically by `RequestIdMiddleware`.

## HTTP / FastAPI

- Routers live in `app/routers/<area>.py`. Mount in `app/main.py`.
- Dependencies via `Annotated[Type, Depends(...)]` aliases in `app/deps.py`.
- Status codes: explicit (don't rely on default 200).
- Response shape: JSON for APIs, `templates.TemplateResponse` for HTML.
- Always set `Cache-Control` on auth-sensitive responses (Phase 03+).

## Templates / HTMX

- Inherit from `templates/base.html`.
- HTMX patterns:
  - `hx-post` form → return a partial → swap into `hx-target` with
    `hx-swap="innerHTML"` (or `outerHTML` / `beforeend`).
  - `hx-boost="true"` for in-place link navigation.
  - Local UI state: Alpine `x-data` / `x-show` / `@click`. No
    server round-trip needed for toggles.
- HTMX + Alpine are **vendored** (`app/static/js/`). No CDN.

## Errors

- Raise specific exceptions; use `HTTPException(status_code, detail=…)`
  for HTTP layer.
- Service-layer errors (Phase 03+) wrap with custom exception types in
  `app/services/exceptions.py` (created when the first service needs it).
- Always log on exception path with `log.exception("event", ...)` —
  structlog captures the traceback.

## Tests

- `pytest` discovery rooted at `tests/`.
- Unit tests **mock backing services** (DB, Redis) — `tests/conftest.py`
  ships fakes.
- Real-DB tests are **gated** by `EXAM_PLATFORM_TEST_REAL_DB=1` env var;
  they wrap in a transaction and rollback at teardown.
- Test names: `test_<unit_under_test>_<scenario>_<expected_outcome>`.
- Don't mock what you don't own — wrap external SDKs in services and
  fake the service.

## Auth / RBAC / audit patterns (Phase 03)

### Adding a new admin route

```python
from app.auth.permissions import RequireAdmin

@router.post("/admin/exam/publish/{exam_id}")
def publish_exam(exam_id: int, user: RequireAdmin, session: SessionDep) -> JSONResponse:
    # ... mutate ...
    write_audit_log(
        session,
        actor_type=ActorType.user,
        actor_id=user.id,
        action=AuditAction.EXAM_PUBLISHED,           # add to events.py first
        entity_type="exam",
        entity_id=exam_id,
        old_value={...}, new_value={...},
        request_id=request.headers.get(REQUEST_ID_HEADER),
    )
    session.commit()                                  # audit + mutation atomic
```

Rules:
- **One** `session.commit()` per route. The audit row and the data
  change live in the same transaction.
- Catch `IntegrityError` and `session.rollback()` for friendly responses;
  do not swallow other exceptions.
- Add a new `AuditAction` value rather than reusing a generic one — keeps
  the audit log greppable.

### Adding a new state-changing route

- Always require CSRF on POST/PUT/PATCH/DELETE form routes. The pattern
  is centralized: GET issues the cookie+form via
  `_issue_csrf_for_template`, POST validates via `verify_csrf(request, form_token)`.
- Use the same `_issue_csrf_for_template` helper rather than inlining
  `issue_csrf_token`. Calling `issue_csrf_token` twice on one response
  breaks the form↔cookie pair — that's been bitten once already.

### Logging from auth-touching code

- Never log: passwords, CSRF tokens, session cookies, raw secrets, full
  request bodies of auth POSTs.
- `LOGIN_FAILED` audit row: include only safe metadata (normalized email
  or username, IP, request_id, "reason": "invalid_credentials").
  Do **not** include the attempted password.
- Generic UI message on any login error ("Invalid credentials") — no
  email-existence leak.

## Catalog patterns (Phase 04)

### Admin CRUD pattern

The catalog admin layer follows a two-file split per entity:

- `app/services/catalog_service.py` — **module-level functions** (no
  class). Each `create_* / update_* / soft_delete_* / publish_* /
  unpublish_*` does:
  1. Apply SQL change(s) on the supplied session (caller-owned).
  2. Catch `IntegrityError` for known unique constraints and re-raise as
     `DuplicateSlugError(...)` with a friendly message.
  3. Call `write_audit_log(session, ...)` so the audit row sits in the
     same transaction.
- `app/routers/admin/<entity>.py` — thin HTTP layer:
  1. `RequireAdmin` for RBAC. CSRF on every POST.
  2. Validate `Pydantic` schema (`app/schemas/catalog.py`).
  3. Call the service. Translate `DuplicateSlugError` to a 400 HTML
     partial. Translate `ValueError` (entity not found) to a 404.
  4. `session.commit()` once per route.

### Slug rules

- Regex `^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$`. Validated by
  `app/utils/slug.py:is_valid_slug` and Pydantic field constraint.
- Generated from name via `app/utils/slug.py:make_slug` (`python-slugify`)
  when the admin leaves the field blank. Fallback `n-a` if input is
  empty/non-ASCII.
- Slugs are **stable on rename** — name change does NOT auto-update slug.
  Admin can edit the slug explicitly.
- Per-parent uniqueness (DB constraints in migration `0004`):
  `providers.slug` global, `courses (provider_id, slug)`,
  `exams (course_id, slug)`, `topics (exam_id, slug)`,
  `product_versions (provider_id, product_name, product_version)`.

### Soft-delete

- Only `Exam` carries `deleted_at` (via `SoftDeleteMixin`).
- `Provider`/`Course`/`Topic` use refuse-with-active-children hard delete.
- Public reads filter `Exam.deleted_at IS NULL` **explicitly** in SELECT
  statements. Helper Selects are centralised in
  `app/routers/public/catalog_query.py`.
- We deliberately **do not** use SQLAlchemy global event hooks for the
  filter — explicit beats magic when reviewers audit visibility rules.

### Public visibility

Anonymous reads see only:
`Exam.publish_status == ExamPublishStatus.published` AND
`Exam.deleted_at IS NULL`. Anything else 404s.
A vendor with no published exams 404s on its detail page (no ghost UI).

### Empty published exam

`publish_exam()` is allowed even with zero questions (Phase 05 ships
the importer later). The exam-detail template:
- Renders a "Coming soon — No questions available yet" badge.
- Hides the "Start Practice" CTA.

### Audit actions (catalog)

`provider.{created,updated,soft_deleted}`,
`product_version.{created,updated,soft_deleted}`,
`course.{created,updated,soft_deleted}`,
`exam.{created,updated,published,unpublished,soft_deleted}`,
`topic.{created,updated,soft_deleted}`. Every mutation writes one row;
`old_value` captured for updates, `new_value` for creates and updates.

### Duplicate-slug troubleshooting

- Symptom: admin creates a course with slug already in use under that
  provider → router returns a 400 with body `course slug 'x' already
  used under this provider`.
- The user-facing string never contains a SQL constraint name or stack
  trace. If you ever see one, it's a bug — add a branch in
  `catalog_service` to translate the IntegrityError.
- To debug: tail the structlog `request_id`, look at the audit log
  entries, and check the unique constraints in
  `migrations/versions/0004_*.py`.

### Adding a new catalog entity

1. Add the SQLAlchemy model in `app/models/catalog.py` with
   `UniqueConstraint(parent_id, slug, name="uq_<entity>_parent_slug")`.
2. Migration: `op.create_unique_constraint(...)`.
3. Pydantic input schemas in `app/schemas/catalog.py`. Use the same
   `_resolve_slug` helper for blank-slug autoderive.
4. Service functions in `app/services/catalog_service.py` — translate
   the new constraint name into a `DuplicateSlugError` branch.
5. New `AuditAction` constants in `app/audit/events.py`.
6. Admin router in `app/routers/admin/<entity>.py` mirroring the
   existing pattern.
7. List + row templates under `app/templates/admin/catalog/<entity>/`.
8. Public exposure (if any) — funnel through
   `app/routers/public/catalog_query.py` so visibility rules stay
   centralised.

## Question CRUD patterns (Phase 06)

### Service surface

`app/services/question_service.py` exposes module-level functions:
`create_question`, `update_question`, `set_options`,
`set_overall_explanation`, `retire`, `restore`, `assign_topic_bulk`.
Every function takes the SQLAlchemy session as the first positional
arg and writes the audit row in the same session. Caller commits.

### Correct-answer validation

`_validate_options(options, correct, qtype)` raises
`QuestionValidationError` when:
- |options| < 2 or > 5.
- Labels not consecutive starting at A (`["A","C"]` rejected).
- Any correct label doesn't match an option label.
- single → not exactly 1 correct.
- multiple → fewer than 2 correct.

### Topic-exam membership

Single-row update and bulk-assign both reject any
`(question_id, topic_id)` pair where `question.exam_id != topic.exam_id`.
The error message reads `question X belongs to exam Y; topic Z belongs
to exam W` — keep this format stable; tests match on `belongs to exam`.

### Soft retire semantics

`retire()` sets `retired_at=now()` + `status=retired`. Existing
attempts retain history. Phase 07/08 query builders MUST filter
`retired_at IS NULL AND deleted_at IS NULL AND status != retired`
when sourcing questions for new attempts.

### Bulk audit verbosity

`assign_topic_bulk` emits exactly one audit row regardless of selection
size, with `new_value={"question_ids": [...], "topic_id": ...}`. We
do not fan out per-question entries to keep the audit table
proportional.

### Question CRUD troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `belongs to exam X` on assign | Topic and question live under different exams | Pick a topic from the same exam |
| `single-choice question requires exactly one correct label` | Type=single but multiple labels marked correct | Switch type to `multiple`, or trim correct labels |
| `option labels must be A,B,...; consecutive starting at A` | Skipped a label slot (e.g. left B blank, filled C) | Move the value to the lower slot |
| `correct_answer must reference at least one option` | All options empty or no labels chosen | Fill at least 2 options + at least 1 correct label |

## Excel import patterns (Phase 05)

### Service split

- `app/services/excel_parser.py` — openpyxl streaming, header → canonical
  mapping, row iteration. No DB.
- `app/services/import_normalizer.py` — bleach + NFKC + zero-width strip
  + whitespace collapse. Pure functions.
- `app/services/import_validator.py` — required fields, length caps,
  type / difficulty enums, correct-answer label validation. Pure
  functions.
- `app/services/import_dedup.py` — canonical SHA-256 + DB lookup
  (the only DB-touching helper here).
- `app/services/import_service.py` — orchestrator. Every public function
  funnels through `write_audit_log()` in the same session. Caller
  commits.

### Confirm idempotency contract

`confirm_import()` MUST be safe to re-run. Filter:

```python
select(ImportItem).where(
    ImportItem.import_id == imp.id,
    ImportItem.status == ImportItemStatus.ok,
    ImportItem.question_id.is_(None),
)
```

Items already converted have `question_id` set and `status='imported'`,
so they're naturally skipped. A second confirm yields zero new
questions.

### Partial-failure tolerance

Per-item subtransaction:

```python
sp = session.begin_nested()
try:
    question = _create_question_from_item(...)
    item.question_id = question.id
    item.status = ImportItemStatus.imported
    sp.commit()
except SQLAlchemyError as exc:
    sp.rollback()
    item.status = ImportItemStatus.error
    item.error_message = f"confirm failed: {exc.__class__.__name__}: {exc}"
```

Failures don't poison subsequent items; the parent transaction stays
open until the outer `s.commit()`.

### Session flush requirement

`parse_and_stage()` calls `session.flush()` at the end so subsequent
operations in the same transaction see the new `import_items`. This is
necessary because `SessionLocal` runs with `autoflush=False` — without
the explicit flush, `confirm_import()` would not see items added during
parse if both run in one transaction without an intermediate commit.

### Sanitization recipe

```python
bleach.clean(value, tags=[], attributes={}, strip=True)  # 1. HTML strip
unicodedata.normalize("NFKC", ...)                         # 2. fold
re.sub("[\\u200B-\\u200F\\u2028-\\u202F\\u2060-\\u206F\\uFEFF]", "", ...)
                                                            # 3. invisibles
```

Always preserve the **raw** value too (`import_items.raw_data`) for
debugging and DMCA traceability.

### Upload safety

- Reject if `len(file_bytes) > settings.import_max_bytes`.
- Reject if not starting with the XLSX zip magic `PK\x03\x04`.
- `Path(name).name` strips path-traversal segments before storage.
- Files stored at `settings.uploads_dir/imports/{id}.xlsx`, mode 600.
- No HTTP route serves them; admin retrieval is via shell/SSH.

### Import troubleshooting

**Symptom:** `parse_and_stage` says all rows are `ok`, but admin expected duplicates.

Cross-exam dedup checks `existing_question_hashes_for_exam`. If the
parent exam has no published-or-imported questions yet (or they have
NULL `content_hash`), nothing matches. Verify
`SELECT COUNT(*) FROM questions WHERE exam_id=:e AND content_hash IS NOT NULL;`.

**Symptom:** `confirm_import` returns `imported=0`.

Check:
- Items have `status='ok'` (not `skipped` or `duplicate`).
- The session has flushed parse_and_stage's adds (parse_and_stage now
  flushes itself, but if you bypass the service and write items
  yourself, you must flush before confirming).

**Symptom:** Upload returns "file is not a valid .xlsx (bad magic bytes)".

The file isn't a real XLSX (.xls / .csv / .ods upload mistakes). Ensure
the admin uses the canonical Excel template.

## Security

- Sanitize user-supplied HTML/Markdown via `bleach` + `markdown-it-py`
  (Phase 02 deps; usage starts in Phase 05+ on the import path and
  Phase 06 on the editor).
- Passwords: Argon2id via `passlib[argon2]` (Phase 03+).
- Sessions: signed cookie via `itsdangerous` + `SECRET_KEY` (Phase 03+).
- CSRF: signed token in cookie + form field, verified on POST (Phase 03+).
- Never disable HTTPS-related middleware in prod (`ProxyHeadersMiddleware`).
- No secrets in code, in `pyproject.toml`, in commit messages, or in
  any file under `.env.example`.

## Commits

- Conventional Commits: `feat:`, `fix:`, `chore:`, `refactor:`, `test:`,
  `docs:`, `ci:`, `build:`, `perf:`.
- One scope per commit; don't bundle unrelated changes.
- No "AI references" in commit messages (per project CLAUDE.md).
- Never commit `.env`, `.env.<env>`, secrets, or large binaries.
- `pre-commit` hooks block secret patterns via gitleaks.

## Lint / format / type-check

- `ruff check` — lint. Failing rules block CI.
- `ruff format` — formatter. Source of truth.
- `mypy app` — types. New code must type-check; legacy `tests/` and
  `migrations/` are exempt for now.
- Never `# type: ignore` without a comment explaining why.

## Decision rationale (style)

**Why ruff for both lint and format instead of black + ruff?**
ruff-format matches black 1:1 in output and runs ~10x faster. Eliminates
"black says X, ruff says Y" friction. Black stays as a dev dep for
quick CLI use.

**Why mypy instead of pyright?**
Pyright is faster but harder to configure for SQLAlchemy 2.0 typing
quirks. Mypy with `ignore_missing_imports = true` and `check_untyped_defs
= true` gives us 90% of the value with zero IDE-vs-CLI drift.

**Why kebab-case for shell scripts but snake_case for Python?**
Shell scripts run as command-line tools — `db-setup.sh` reads more
naturally as a CLI noun. Python modules become identifiers
(`from app.models.imports import …`); kebab-case is illegal there.
Each tool to its ecosystem convention.

**Why no docstrings on every function?**
Per project CLAUDE.md: "default to writing no comments." Self-documenting
names + clear types beat boilerplate docstrings. Docstrings only when
the why is non-obvious (hidden constraint, workaround, surprising
behavior).
