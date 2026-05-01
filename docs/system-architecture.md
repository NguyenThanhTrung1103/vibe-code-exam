# System Architecture

Concise architectural reference. Updated after each phase that changes
runtime topology, schema, or surface area.

## LXC deployment (Phase 11 — loopback)

```
LXC (192.168.99.97)
├── /opt/exam-python-3.12/                   ← relocated uv-managed CPython
├── /srv/exam-platform/                      ← prod root (root:exam-platform 750)
│   ├── .env                                  640 root:exam-platform
│   ├── .venv/                                exam-platform:exam-platform
│   ├── app/  migrations/  ops/  uploads/  logs/
│   └── pyproject.toml  uv.lock  alembic.ini  README.md
├── /etc/systemd/system/
│   ├── exam-platform-web.service             User=exam-platform; bind 127.0.0.1:8001
│   ├── exam-pg-backup.service                oneshot
│   └── exam-pg-backup.timer                  daily 02:30 UTC
└── (untouched)
    ├── /srv/blog-website/                    blog
    ├── blog.service                          gunicorn :8000
    ├── nginx :80 / :443                      blog vhost only
    └── cloudflared                           blog tunnel
```

systemd hardening on the web unit: `User/Group=exam-platform`,
`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=yes`,
`PrivateTmp=yes`, `ProtectKernelTunables/Modules/ControlGroups`,
`RestrictNamespaces/Realtime`, `MemoryDenyWriteExecute`,
`SystemCallArchitectures=native`. Read-write limited to
`/srv/exam-platform/{uploads,logs}`.

Public exposure (Nginx vhost + Certbot TLS) is **NOT** active. Templates
live at `ops/nginx/exam-platform.conf` and `ops/logrotate/exam-platform`
for Phase 12 review. Phase 12 readiness checklist gates installation.

## Backup + observability (Phase 10)

```
┌──────────────────── exam_platform_db ─────────────────────┐
│  pg_dump --format=custom (cron 02:30 UTC, Phase 11 timer)  │
│         │                                                  │
│         ▼                                                  │
│   /var/backups/postgres/exam_<UTC>.dump  (local staging)   │
│         │                                                  │
│         ▼  (when RESTIC_REPO set)                          │
│   restic backup → encrypted off-site repo                  │
│   restic forget --keep-daily 7 --keep-weekly 4 --monthly 6 │
└────────────────────────────────────────────────────────────┘

DR drill: ops/backup/restic-restore.sh → exam_platform_db_drill
          → smoke counts → drop drill DB.
          Operator pre-creates drill DB via postgres superuser.

Health endpoints:
  GET /healthz  — DB SELECT 1 + Redis PING                  → 200/503
  GET /readyz   — /healthz + alembic head match             → 200/503
```

Logging is structlog → stdout, console renderer in dev/local/test,
JSON in `prod`/`staging`. Sentry receives errors with `release`
stamped from `SENTRY_RELEASE` env (set by Phase 11 deploy script).
`request_id` flows through middleware → logs → audit_logs → Sentry.

Operational docs live in `ops/docs/`:
* `backup-runbook.md` — manual + automated backup procedure.
* `restore-runbook.md` — drill steps + production-cutover playbook.
* `dr-drill-log.md` — append-only signed-off drill records.
* `observability.md` — log/Sentry/UptimeRobot contracts.

## Security baseline (Phase 09)

The app sits behind a defence-in-depth stack assembled by Phase 09. The
canonical specification is `docs/security-baseline.md` — this section
records the architectural moves only.

```
┌──────────────────────────────────────────────────────────────────────┐
│  ProxyHeadersMiddleware (non-local envs only — trusted=127.0.0.1)    │
├──────────────────────────────────────────────────────────────────────┤
│  RequestIdMiddleware       (Phase 03 — UUID v4 per req → structlog)  │
├──────────────────────────────────────────────────────────────────────┤
│  SecurityHeadersMiddleware (CSP, X-Frame, X-CTO, Referrer, Perms,    │
│                             HSTS-in-prod)                            │
├──────────────────────────────────────────────────────────────────────┤
│  GZipMiddleware                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  Routes  ── Per-route rate-limit Depends (Redis sliding window)      │
│         ── CSRF (Phase 03) on every state-changing POST              │
│         ── RBAC (Phase 03) — 401 vs 403 distinction                  │
└──────────────────────────────────────────────────────────────────────┘
```

Render path: admin-authored Markdown passes through `render_md` Jinja
filter → `markdown-it` (html=False) → bleach allow-list → linkify with
`rel="noopener noreferrer nofollow" target="_blank"`. Templates that
display plain user text continue to rely on Jinja auto-escape.

Upload path: `app/security/upload_validator.validate_xlsx_bytes` is the
single gate for the Phase 05 admin import — extension allow-list, magic
bytes (`PK\x03\x04`), size cap. Browser `Content-Type` is not trusted.

Production-safe error handler is installed only in `prod` / `staging`
so dev keeps full tracebacks.


## Runtime topology — current (post-Phase 02)

```
┌──────────────────────────────────────────────────────────────────────┐
│  Ubuntu 22.04 LXC (192.168.99.97) — co-tenant host                    │
│                                                                      │
│  ┌────────────────┐    ┌──────────────────┐    ┌──────────────┐     │
│  │ blog stack     │    │ exam-platform    │    │ shared infra │     │
│  │  (untouched)   │    │   (NEW)          │    │              │     │
│  │                │    │                  │    │              │     │
│  │ Flask+Gunicorn │    │ FastAPI+uvicorn  │    │ PostgreSQL14 │     │
│  │ 127.0.0.1:8000 │    │ 127.0.0.1:8001   │    │ 127.0.0.1:   │     │
│  │                │    │   (dev)          │    │  5432        │     │
│  │                │    │                  │    │              │     │
│  │ /srv/blog-     │    │ /srv/exam-       │    │ Redis 7      │     │
│  │  website       │    │  platform-dev    │    │ 127.0.0.1:   │     │
│  │                │    │                  │    │  6379 (NEW)  │     │
│  │                │    │ DB: exam_        │    │              │     │
│  │ DB: blogdb     │    │  platform_db     │    │ nginx 80/443 │     │
│  │ Role: blog     │    │ Role: exam_      │    │ (only blog   │     │
│  │                │    │  platform_user   │    │  vhost)      │     │
│  └────────────────┘    └──────────────────┘    │              │     │
│                                                │ cloudflared  │     │
│                                                │ (loopback    │     │
│                                                │  only)       │     │
│                                                └──────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

- **Public ingress** is via nginx 80/443 → blog vhost only. Exam-platform
  has **no** nginx route in dev. Phase 11 will add the prod vhost.
- **Postgres** listens on `localhost` (loopback). Two databases on one
  cluster: `blogdb` (existing) and `exam_platform_db` (new in Phase 02).
- **Redis** is loopback-only (`bind 127.0.0.1 ::1`, `protected-mode yes`,
  no auth — relies on loopback isolation). Installed in Phase 02; no
  jobs use it yet (RQ scaffolded for Phase 2).

## Application layout (FastAPI app)

```
app/
├── main.py            # create_app() factory, middleware, router mount
├── config.py          # pydantic-settings — read .env once, no os.getenv
├── db.py              # SA 2.0 engine + sessionmaker + get_session
├── deps.py            # Annotated[...] FastAPI dependencies
├── logging.py         # structlog config (console-dev, JSON-prod)
├── middleware.py      # RequestIdMiddleware → X-Request-ID + structlog ctx
├── redis_client.py    # singleton Redis client w/ short timeouts
├── routers/
│   └── health.py      # GET /healthz — pings DB + Redis
├── models/            # Phase 02: 13 model files, all under Base.metadata
│   ├── base.py
│   ├── enums.py       # 23 native PG ENUM types
│   ├── users.py
│   ├── catalog.py     # provider, product_version, course, exam, topic
│   ├── questions.py   # question, option, explanation, duplicate_group
│   ├── evidence.py    # source_domain, question_reference, fetch_log
│   ├── ai.py          # ai_verification_job (Phase 2 stub)
│   ├── imports.py     # import + import_item (NEW per Phase 02 plan)
│   ├── attempts.py    # attempt + attempt_answer (with order_index)
│   ├── reports.py     # question_report
│   ├── audit.py       # audit_log
│   └── glossary.py    # glossary_term (Phase 3 stub)
├── services/          # business logic (Phase 03+)
├── schemas/           # Pydantic I/O (Phase 03+)
├── templates/         # Jinja base + per-page partials
└── static/            # vendored htmx.min.js, alpine.min.js, base.css
```

## Database — Phase 02 active tables (16)

`users`, `providers`, `product_versions`, `courses`, `exams`, `topics`,
`imports`, **`import_items`**, `questions`, `question_options`,
`question_explanations`, `question_references`, `attempts`, `attempt_answers`,
`question_reports`, `audit_logs`.

## Database — Phase 2/3 schema-only stubs (5)

`source_domains` (seeded with 5 trusted domains), `ai_verification_jobs`,
`evidence_fetch_logs`, `question_duplicate_groups`, `glossary_terms`.

These exist so Phase 2 doesn't pay migration churn. **No service code or UI
references them in Phase 1.**

## Key schema decisions (Phase 02)

1. **`import_items`** — row-level Excel import staging:
   `(import_id, row_number, sheet_name)` UNIQUE, status enum
   (parsed/ok/duplicate/warning/error/skipped/imported), `content_hash CHAR(64)`,
   `question_id FK ON DELETE SET NULL`. Lets confirm be idempotent and lets
   debugging back-trace any question to its import row.

2. **`questions.source_locator JSONB`** — back-trace
   `{import_id, import_item_id, file_name, sheet_name, row_number}`.
   Required for audit, DMCA review, debugging.

3. **`attempt_answers.order_index INT NOT NULL`** + `UNIQUE(attempt_id, order_index)` —
   the **source of truth** for question presentation order in an attempt,
   frozen at attempt start. Survives later question edits/retirement.

4. **`content_hash`** (CHAR(64)) on `questions` and `import_items` —
   `sha256(normalized_question + "|" + "||".join(sorted(normalized_options)))`.
   Used **only** for exact-duplicate detection. Near-duplicate is Phase 3.

5. **23 native PG ENUM types** — schema-tracked, including ones whose values
   are unused in Phase 1 (e.g. `ai_verification_status`) so Phase 2 can
   populate them without schema migration.

6. **All FK on-delete** = `RESTRICT` by default. Two exceptions:
   `import_items.import_id` → `CASCADE` (item is part of its import),
   `import_items.question_id` → `SET NULL` (question can be retired without
   losing the import row).

## Indexes (PRD §7.3 + Phase 02 plan additions)

- `questions(exam_id, status, deleted_at)` — exam-page list query.
- `questions(needs_human_review, confidence_level)` — review queue.
- `questions(content_hash)` — dedup lookup.
- `questions(next_verification_due_at) WHERE stale_status<>'fresh'` — partial; staleness scan.
- `attempt_answers(question_id, is_correct)` — most-missed analytics.
- `audit_logs(entity_type, entity_id, created_at DESC)` — entity history.
- `question_references(source_domain_id, fetch_status)` — broken-source scan.
- **NEW** `import_items(import_id, status)` — preview filter.
- **NEW** `import_items(content_hash)` — pre-insert dedup check.
- **NEW** UNIQUE `attempt_answers(attempt_id, order_index)` — frozen order invariant.

## Authentication & authorization (Phase 03)

### Session cookies (`itsdangerous`-signed)

- Cookie name: `exam_session`. Payload: `{"user_id": int, "iat": <epoch>, "sid": <random>}`.
- Signing: `URLSafeTimedSerializer(SECRET_KEY, salt="exam-session")`.
- Flags: `HttpOnly`, `SameSite=Lax`, `Secure` outside `local`/`test`.
- TTL: `SESSION_TTL_DAYS=7` (env-overridable).
- Session-id rotation on every login (fresh `iat`+`sid` → different signed
  token → defeats fixation; the previous cookie is cryptographically dead).

### Passwords (Argon2id via `passlib`)

- Backend: `passlib.context.CryptContext(schemes=["argon2"], deprecated="auto")`.
- Tuning: passlib defaults (~50 ms on modern CPU).
- `verify_password` always runs, even on missing user → constant-time
  defence against username-enumeration timing attacks (`dummy_verify`).
- `users.last_password_at TIMESTAMPTZ NULL` records when the password was
  set or last typed; admin role re-prompts at `ADMIN_REPROMPT_HOURS=24`
  since that timestamp.

### CSRF (stateless HMAC, signed by `itsdangerous`)

- Cookie name: `exam_csrf`. Token TTL: 4 hours.
- Pattern: GET issues a token via cookie + form-field. POST verifies
  cookie token == form token (both sent), and the cookie token verifies
  with the secret. Both checks use `secrets.compare_digest`.
- One token per GET — the helper `_issue_csrf_for_template()` mints
  exactly one and uses it in both the cookie and the rendered form.
- Required on every state-changing form POST. **Skipped** for GET and
  `/healthz`.

### RBAC

- `Role` is the existing `UserRole` enum (`admin | instructor | student | system`).
  Phase 03 only uses `admin` and `student`; `instructor` is a Phase-2
  schema seed.
- `app/auth/permissions.py` exports:
  - `get_current_user` (request → `User | None`)
  - `get_current_user_required` (raises 401 if anonymous)
  - `require_role(*roles)` factory (raises 401 anon, 403 wrong role)
  - `CurrentUser`, `OptionalUser`, `RequireAdmin`, `RequireStudent` typed aliases.
- 401 vs 403: 401 = no/expired session. 403 = authenticated but role mismatch.

### Login rate limit (Redis sliding window)

- Per IP: 5 attempts / 60 s (`rl:login_ip:<ip>`).
- Per identifier (lowercased email or username): 20 attempts / 3600 s
  (`rl:login_ident:<lower(ident)>`).
- Both checked together; either threshold trips returns 429 with
  `Retry-After`.
- **Fail-closed:** if Redis is unreachable, login is rejected with a
  `Retry-After: 30` 429 — never falls back to "allow unlimited."

### Audit log writer (same-transaction)

- `app.audit.writer.write_audit_log(session, *, actor_type, actor_id,
  action, entity_type, entity_id, old_value=None, new_value=None,
  reason=None, request_id=None)` — caller passes the same SQLAlchemy
  session they're using for the data change. Writer just `session.add(AuditLog(...))`.
  Caller commits; if they roll back, the audit row rolls back with them.
- `request_id` accepts `str | UUID | None`; coerced to UUID. Invalid →
  `None` (we never crash audit; never silently drop the surrounding
  mutation either).
- `AuditAction` is a `StrEnum`. Every subsequent phase appends new values.

### Admin bootstrap CLI

`uv run python -m scripts.create_admin --email <e> --username <u>` —
prompts for password (or reads `EXAM_ADMIN_PW` env). Idempotent error on
existing email/username. Writes a `system`-actor `user.registered` audit
row.

### Admin audit viewer

Mounted at `GET /admin/audit` (HTML) and `GET /admin/audit.json` (JSON).
Pagination: `page` + `page_size`, `entity_type` and `actor_id` filters.
Read-only. RBAC: `RequireAdmin`.

### Phase 03 routes

| Method | Path | RBAC | Notes |
|---|---|---|---|
| GET | `/auth/register` | anon | Issues CSRF cookie + form. |
| POST | `/auth/register` | anon | Creates `student`. Audit row. **Internal-beta only** — gate before public launch. |
| GET | `/auth/login` | anon | Issues CSRF cookie + form. |
| POST | `/auth/login` | anon | Rate-limited; rotates session cookie; audits success/failure. |
| POST | `/auth/logout` | `CurrentUser` | Audits; clears cookie. |
| GET | `/auth/me` | `CurrentUser` | Returns id/email/username/role. |
| GET | `/admin/audit` | `RequireAdmin` | HTML viewer, paginated. |
| GET | `/admin/audit.json` | `RequireAdmin` | JSON viewer, paginated. |

## Catalog (Phase 04)

### Hierarchy

```
Provider (1) ── (n) Course ── (n) Exam ── (n) Topic
   └── (n) ProductVersion        └── (deleted_at via SoftDeleteMixin)
```

`ProductVersion` is wired but unused on the public surface — it pins the
"docs revision" used by the Phase 02 AI verifier.

### Slug rules

- Regex: `^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$` (lowercased, no
  leading/trailing hyphen, max 64 chars).
- Generated from name via `app/utils/slug.py:make_slug` (`python-slugify`).
  Falls back to `n-a` for empty/non-ASCII inputs.
- Slugs are **stable**: renaming an entity does NOT update its slug. URL
  stability matters; admins must explicitly edit the slug to change it.
- **Per-parent uniqueness** (migration `0004`):
  - `providers.slug` global unique.
  - `courses` `UNIQUE(provider_id, slug)`.
  - `exams` `UNIQUE(course_id, slug)`.
  - `topics` `UNIQUE(exam_id, slug)`.
  - `product_versions` `UNIQUE(provider_id, product_name, product_version)`.
- Duplicate writes raise `catalog_service.DuplicateSlugError`, mapped by
  the router to a 400 HTML partial. Raw `IntegrityError` is **never**
  exposed to the user.

### Soft-delete

Only `Exam` carries `deleted_at` (via `SoftDeleteMixin`). For
`Provider`/`Course`/`Topic`, the service refuses delete if any active
child rows exist (cascade safety net + simpler model — Phase 04
explicitly avoids a wider migration to add `deleted_at` to those
entities).

Public reads filter `Exam.deleted_at IS NULL` **explicitly** in the SELECT
— centralised in `app/routers/public/catalog_query.py`. We deliberately
avoid global SQLAlchemy event hooks; explicit filters keep visibility
rules visible to readers and reviewers.

### Public visibility

Anonymous (and student) reads see only:
- `Exam.publish_status == 'published'`, AND
- `Exam.deleted_at IS NULL`.

Anything else → 404 (never "draft" or "deleted" leakage). Vendor pages
with no published exams also 404 to avoid empty ghost pages. The home
page hides vendors with zero published exams.

### Empty published exam

A published exam with zero questions is permitted (Phase 04 is shipping
ahead of Phase 05's importer). The exam detail page must:
- Show "Coming soon — No questions available yet" badge.
- Hide the "Start Practice" CTA.
- The template enforces this; tests cover both branches.

### Audit pattern

Every catalog mutation calls `write_audit_log(session, …)` in the same
session as the SQL change. The route handler commits; if it rolls back
on error the audit row rolls back too. Audit actions added in Phase 04:
`provider.{created,updated,soft_deleted}`,
`product_version.{created,updated,soft_deleted}`,
`course.{created,updated,soft_deleted}`,
`exam.{created,updated,published,unpublished,soft_deleted}`,
`topic.{created,updated,soft_deleted}`.
For updates, we capture `old_value` before mutating; for creates, only
`new_value` is written.

## Scoring + result/review (Phase 08)

### Submit pipeline

`attempt_service.submit_attempt(...)` (Phase 07) now calls
`scoring_service.compute_attempt_score(...)` in the **same
transaction**. The row is finalised + scored together, or neither.

```
submit_attempt:
  if finished_at IS NULL:
    set finished_at, duration_seconds
    audit ATTEMPT_SUBMITTED
    compute_attempt_score:
      load all attempt_answers + question_options for involved qs
      per row: is_correct = set(selected) == set(correct)
      persist score_percent, correct_count, wrong_count, passed
      audit ATTEMPT_SCORED
  idempotent — already-finished attempt is a no-op
```

### Scoring rules (Phase 1)

- Single-choice: `selected == {correct_label}`.
- Multi-choice: `set(selected) == set(correct_labels)` —
  **all-or-nothing**.
- Unanswered (`selected_options IS NULL`) → wrong.
- `score_percent = round(100 * correct / total, 2)`.
- `passed = score_percent >= exam.passing_score_percent` if set,
  else `None`.

### Topic breakdown + recommendation

Per-topic aggregation via `attempt_answers → questions`. Questions
without `topic_id` roll into the **"Untagged"** bucket. Recommendation
returns at most 2 topics where `total ≥ 3` AND
`topic_percent ≤ overall_percent − 10 pp`, sorted by gap descending.

### Confidence badge

Phase 1 review always renders **"Unverified (admin-supplied)"** —
honest expectation-setting until Phase 2's AI verifier ships.

### Phase 08 routes

| Method | Path | Auth |
|---|---|---|
| GET | `/attempts/{id}/result` | owner only |
| GET | `/attempts/{id}/review` | owner only |
| GET | `/attempts/{id}/review/q/{order}` | owner only |
| POST | `/questions/{id}/reports` | any authenticated |
| GET | `/admin/question-reports` | admin |
| POST | `/admin/question-reports/{id}/resolve` | admin |
| POST | `/admin/question-reports/{id}/reject` | admin |

## Practice & exam mode (Phase 07)

### Routes (auth required)

| Method | Path |
|---|---|
| POST | `/attempts/start` |
| GET | `/attempts/{id}/q/{order}` |
| POST | `/attempts/{id}/q/{order}/answer` (autosave) |
| POST | `/attempts/{id}/q/{order}/flag` |
| GET | `/attempts/{id}/submit-confirm` |
| POST | `/attempts/{id}/submit` |
| GET | `/attempts/{id}/submitted` (Phase 08 replaces the stub) |

### Attempt state machine

```
nothing → in_progress → submitted (or auto-submitted on expiry)
```

`Attempt.started_at` set at `start_attempt`. `Attempt.finished_at` set
on submit / expiry — idempotent. `Attempt.duration_seconds` derived
from the gap.

### Frozen `order_index`

`start_attempt` snapshots publishable questions
(`status='published' AND retired_at IS NULL AND deleted_at IS NULL`),
shuffles once, then inserts N `attempt_answers` rows with `order_index`
1..N. The DB-level `UNIQUE(attempt_id, order_index)` guarantees no
duplicates. **Subsequent admin edits or retirements DO NOT mutate the
snapshot** — `attempt_answers` references `question_id` directly,
without re-applying the publishable filter at read time.

### Selected-label format

- Single-choice: `"B"`.
- Multi-choice: comma-joined sorted labels: `"A,C"`.
- Empty selection: `NULL`.

`_parse_selected_labels` normalises every input: sorted, unique,
upper-case. Each label must exist on the question; unknown labels
return HTTP 400 with no DB write.

### Timer model

```
remaining = max(0, attempt.started_at + exam.time_limit_seconds - now())
```

Every page render computes `remaining`; if `remaining == 0` and the
mode is `exam`, the server forces an idempotent submit and redirects to
`/submitted`. The Alpine countdown is display-only — client clock
manipulation cannot extend the deadline.

### RBAC + ownership

All routes require an authenticated session. Every read/write path
enforces `attempt.user_id == current_user.id` → 403 otherwise. Anonymous
→ 401. Admins are not exempted from the ownership check (a read-only
admin viewer is reserved for Phase 09).

### Empty-exam guard

`start_attempt` raises `AttemptValidationError("no questions available
yet for this exam")` if the publishable snapshot is empty. UX matches
Phase 04's "Coming soon" badge: no attempt is created, no
`attempt_answers` rows are inserted.

## Question bank CRUD (Phase 06)

### Surface

Admin-only routes at `/admin/questions/*` (RBAC `RequireAdmin`, all POSTs
CSRF-checked):

| Method | Path |
|---|---|
| GET | `/admin/questions` (list with filters: exam, topic, status, difficulty, q) |
| GET | `/admin/questions/new` (manual create form) |
| POST | `/admin/questions` |
| GET | `/admin/questions/{id}/edit` |
| POST | `/admin/questions/{id}/edit` (text, type, topic, difficulty, status) |
| POST | `/admin/questions/{id}/options` (replace option set + correct answer) |
| POST | `/admin/questions/{id}/explanation` (upsert overall explanation) |
| POST | `/admin/questions/{id}/retire` (with reason) |
| POST | `/admin/questions/{id}/restore` |
| POST | `/admin/questions/bulk-topic` (bulk topic assignment) |

### Validation

- 2–5 options with **consecutive** labels A,B,…,E starting at A.
- `correct_answer` labels must each reference an existing option.
- `single` → exactly 1 correct label; `multiple` → ≥2 correct labels.
- `question_text` non-empty after `.strip()`; capped at 4 000 chars
  (option max 1 000 chars).
- Topic FK must belong to the same exam as the question.

### Status lifecycle

- Imported questions arrive with `status=imported` (Phase 05).
- Manual edits via Phase 06 update text/options without changing
  status; admin can explicitly set status from the editor dropdown.
- Retire → `status=retired` + `retired_at=now()`. Restore → status
  back to `verified_low`, `retired_at=NULL`.
- "Published" in MVP means *exam is published AND question is not
  retired*. There is no per-question publish toggle in Phase 1.

### Content hash on edit

Editing `question_text` or `options` recomputes `content_hash` with the
**same canonical recipe** as `app/services/import_dedup.py` — `sha256(
normalized_q + "|" + "||".join(sorted_normalized_options))`. Sort by
text (not label) so re-shuffling answer choices doesn't artificially
change the hash.

### Audit trail

Every mutation writes to `audit_logs` in the same session as the SQL
change. Actions: `question.created`, `question.text_edited`,
`question.option_edited`, `question.explanation_edited`,
`question.retired`, `question.restored`, `question.topic_assigned`.
`old_value` captures the field's previous content; `new_value` the new
content (option arrays, correct labels, etc.).

### Soft retire vs soft delete

`questions.deleted_at` (from `SoftDeleteMixin`) is reserved for
admin-initiated row removal — not used by the editor today. Retire is
a separate soft-state via `retired_at` + `status=retired`. Future
Phase 2 work may add hard-delete for DMCA / legal removal; the column
exists for that.

## Excel import pipeline (Phase 05)

### Wizard

```
upload  →  mapping  →  preview  →  done
(POST   →  GET POST →  GET POST →  GET)
```

- **Upload**: validates magic bytes (`PK\x03\x04`), size ≤ 25 MB, exam
  exists. Saves XLSX to `settings.uploads_dir/imports/{id}.xlsx` with
  mode 600. Filename is path-traversal-sanitised before storage.
- **Mapping**: shows Excel headers and the canonical fields side by
  side; auto-suggests via alias map. Admin's saved mapping is replayed
  on re-visit. Required canonical fields enforced server-side
  (`question_text`, `option_a`, `option_b`, `correct_answer`).
- **Preview**: paginated 50/page. Filters by `import_items.status`
  chips (all / ok / duplicates / errors / warnings / skipped /
  imported). Row toggle flips `ok ↔ skipped` via HTMX `hx-post`.
- **Confirm**: idempotent — selects only items with `status='ok' AND
  question_id IS NULL`. Per-item `session.begin_nested()` (PG SAVEPOINT)
  isolates failures so one bad row does not block the rest.

### Tables

`imports` row holds wizard state:
`status`, `column_mapping JSONB`, `target_exam_id` FK, `file_path`,
`import_source_claim`, counters.

`import_items` is the per-Excel-row staging table. `(import_id,
row_number, sheet_name)` UNIQUE. Index on `(import_id, status)` powers
the filter chips. `content_hash CHAR(64)` for dedup. `question_id`
links back once an item gets imported.

### Status state machines

```
imports.status:
  uploaded → needs_mapping → normalized → ready_to_publish (or
                                          partially_verified on errors)
import_items.status:
  parsed → ok        → imported     (happy path)
         → duplicate                (within-import or cross-exam)
         → warning                  (non-fatal — defaulted difficulty)
         → error                    (validation / confirm failure)
         → skipped                  (admin deselect)
```

### Content hash (canonical)

```python
sha256(
    normalized_question_text
    + "|"
    + "||".join(sorted(non_empty_normalized_option_texts))
)
```

Same recipe in `app/services/import_dedup.py:content_hash` and Phase 06's
question editor. Sort by **text** (not label) so re-shuffling answer
choices does not change the hash.

### Sanitization

Three-step per cell, applied at parse:

1. `bleach.clean(value, tags=[], attributes={}, strip=True)` — full HTML strip.
2. `unicodedata.normalize("NFKC", ...)`.
3. Strip zero-width / RTL / LTR override / BOM characters; collapse whitespace.

`raw_data` JSONB preserves the pre-sanitize snapshot for debugging /
DMCA review; `normalized_data` JSONB stores the cleaned canonical form.

### File storage

Uploads live at `<uploads_dir>/imports/<import_id>.xlsx` with mode 600.
`uploads_dir` defaults to `/srv/exam-platform/uploads`. **Never** under
`app/static`, never reachable via any HTTP route. Phase 09 hardens
admin re-download (currently no download endpoint exists; admin can
SSH and read the file).

### Phase 05 routes

Admin (all `RequireAdmin`, all POSTs CSRF-checked):

| Method | Path |
|---|---|
| GET/POST | `/admin/imports` (list + upload) |
| GET/POST | `/admin/imports/{id}/mapping` |
| GET | `/admin/imports/{id}/preview` |
| POST | `/admin/imports/{id}/items/{item_id}/toggle` |
| POST | `/admin/imports/{id}/confirm` |
| GET | `/admin/imports/{id}/done` |

### Phase 04 routes

Admin (all `RequireAdmin`, all POSTs CSRF-checked):

| Method | Path |
|---|---|
| GET/POST | `/admin/providers` |
| POST | `/admin/providers/{id}/edit` and `/delete` |
| GET/POST | `/admin/product-versions` |
| POST | `/admin/product-versions/{id}/edit` and `/delete` |
| GET/POST | `/admin/courses` |
| POST | `/admin/courses/{id}/edit` and `/delete` |
| GET/POST | `/admin/exams` |
| POST | `/admin/exams/{id}/edit`, `/publish`, `/unpublish`, `/delete` |
| GET/POST | `/admin/topics` |
| POST | `/admin/topics/{id}/edit` and `/delete` |

Public (anonymous-friendly):

| Method | Path |
|---|---|
| GET | `/` (home: hero + search + vendor grid + popular exams) |
| GET | `/vendors` |
| GET | `/vendors/{provider_slug}` |
| GET | `/exams/{provider_slug}/{exam_slug}` |
| GET | `/search/exams?q=...` (HTMX partial; ILIKE; max 20 hits) |

## Logging

- structlog ContextVar-bound `request_id` per request (set by `RequestIdMiddleware`).
- Console renderer in dev (`ENV=local`), JSON renderer in prod.
- `X-Request-ID` header echoed back so external traces correlate.

## Healthcheck contract

`GET /healthz`:
- `200 {"status":"ok","db":"ok","redis":"ok"}` — both backing deps reachable.
- `503 {"status":"degraded","db":"ok|down","redis":"ok|down"}` — at least one down.
- Response includes `X-Request-ID`.
- DB ping uses `connect_timeout=3`; Redis ping uses `socket_connect_timeout=2`.

## Decision rationale (architecture)

**Why one Postgres cluster, not a separate one?**
The LXC already runs PG14 for the blog. A second cluster would double
backup ops, RAM, port management, and pg_hba complexity for negligible
isolation gain. We get strong-enough isolation via separate database +
separate role + role-level timeouts + REVOKE PUBLIC on `public` schema.

**Why server-rendered HTML (Jinja+HTMX) instead of an SPA?**
Phase 1 is a CRUD app for a known internal user set. SPA adds a build
pipeline, a router, state management, hydration mismatches — solving
problems we don't have. HTMX + Alpine give us interactive feel
(form-post → swap; toggles) without the JS framework cost.

**Why vendor htmx/alpine instead of CDN?**
SRI hash management drag at MVP, plus we want zero unexpected fetches
(privacy + offline-friendly). 92 KB of static JS is rounding error.

**Why structlog instead of stdlib logging?**
Free `request_id` binding via ContextVars, JSON output for prod log
shippers, console renderer for dev — without rolling our own formatter.

**Why pydantic-settings instead of `os.getenv`?**
Single-source typed config, `.env` autoload, fast-fail on missing vars,
discoverable surface in `Settings()`. No "where did this var get read?"
hunts later.
