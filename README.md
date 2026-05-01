# Exam Platform

Phase 1 MVP — exam practice platform. FastAPI + PostgreSQL 14 + Redis + RQ + Jinja2 + HTMX + Alpine.js.

See `plans/260428-1631-phase-1-mvp-exam-platform/` for the active plan.

## Local development (3 commands)

```bash
uv sync --extra dev
cp .env.example .env
uv run uvicorn app.main:app --reload
```

> Full setup, runtime tooling, HTMX patterns and verification steps live below in this file.

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (`pip install uv`)
- Docker Desktop (Windows) or Docker Engine (Linux). On Windows enable WSL2 backend.
- Git

## Quickstart

```bash
# 1. Install Python deps (creates .venv, installs dev tools too)
uv sync --extra dev

# 2. Bootstrap env
cp .env.example .env

# 3. Start the app (db/redis optional locally — /healthz reports their state)
uv run uvicorn app.main:app --reload
```

App listens on `http://127.0.0.1:8000`. Healthcheck:

```bash
curl http://127.0.0.1:8000/healthz
```

Returns `{"status":"ok","db":"<state>","redis":"<state>"}`. `200` if all green, `503` if any backing dependency is down.

## Local stack via Docker Compose

For a full local environment (Postgres 14 + Redis 7 + Mailhog + app):

```bash
docker compose up --build
```

- App → http://127.0.0.1:8000
- Mailhog UI → http://127.0.0.1:8025
- Postgres → localhost:5432 (user `exam_platform_user`, db `exam_platform_db`)
- Redis → localhost:6379

## Running tests / lint / type-check

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```

## First admin (Phase 03)

```bash
EXAM_ADMIN_PW='your-strong-password' \
  uv run python -m scripts.create_admin \
  --email admin@example.com --username admin
```

Idempotent. Audit-logged. See `docs/deployment-guide.md` for `SECRET_KEY`
rotation and auth troubleshooting.

## Catalog (Phase 04)

After bootstrapping an admin and applying migrations, the catalog admin
lives at `/admin/{providers,product-versions,courses,exams,topics}` and
the public site at `/`, `/vendors`, `/vendors/{slug}`,
`/exams/{provider_slug}/{exam_slug}`, and `/search/exams?q=…`. See
`docs/system-architecture.md` § Catalog for the data model, slug rules,
soft-delete behaviour, and visibility filters; see
`docs/code-standards.md` § Catalog patterns for the admin-CRUD recipe.

## Pre-commit hooks

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Hooks: ruff (lint+format), mypy (loose at MVP), gitleaks (secret scan).

## Project layout

```
exam-platform/
├── app/
│   ├── main.py              # FastAPI factory + middleware
│   ├── config.py            # pydantic-settings
│   ├── db.py                # SQLAlchemy engine + session
│   ├── deps.py              # FastAPI dependencies
│   ├── logging.py           # structlog setup
│   ├── routers/             # http routes (health, …)
│   ├── services/            # business logic (Phase 03+)
│   ├── models/              # SQLAlchemy models (Phase 02+)
│   ├── schemas/             # Pydantic I/O schemas
│   ├── templates/           # Jinja templates
│   ├── static/              # CSS, HTMX, Alpine
│   ├── workers/             # RQ jobs (Phase 02+)
│   └── utils/
├── migrations/              # Alembic (Phase 02)
├── tests/
├── scripts/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md
```

## HTMX + Alpine cheatsheet

We render server-side HTML and progressively enhance with HTMX (server requests) and Alpine (local UI state).

**Form post → partial swap**

```html
<form hx-post="/practice/answer"
      hx-target="#answer-feedback"
      hx-swap="innerHTML">
  <button type="submit">Submit</button>
</form>
<div id="answer-feedback"></div>
```

**Inline boost (link → fetch + swap)**

```html
<a href="/exam/123" hx-boost="true">Go to exam</a>
```

**Alpine-driven local toggle (no server round trip)**

```html
<div x-data="{ open: false }">
  <button @click="open = !open">Show details</button>
  <div x-show="open">…explanation…</div>
</div>
```

Reference patterns: form post → server returns the partial → HTMX swaps it into `hx-target` using `hx-swap` strategy (`innerHTML`, `outerHTML`, `beforeend`, …).

## Configuration

All env vars are documented in `.env.example`. Read by `app/config.py` (pydantic-settings) — never call `os.getenv` directly inside business code.

## Logging

`structlog` JSON renderer in production, console renderer in dev (`ENV=local`). A `request_id` is injected by middleware and bound to every log record.

## Sentry

If `SENTRY_DSN` is set, Sentry is initialized at startup. Empty/unset → Sentry disabled (no network call).

## Reverse proxy note

In production (Phase 09/11) the app sits behind Nginx with `ProxyHeadersMiddleware` enabled and trusted-host configuration. Locally we run uvicorn directly, so proxy header trust is off by default.

## Troubleshooting

- `psycopg` build errors on Windows → ensure VS C++ Build Tools or use the bundled `psycopg[binary]` wheel (already pinned).
- `docker compose up` fails on Windows → enable WSL2 backend in Docker Desktop settings.
- Port conflicts → adjust `APP_PORT`/`DB_PORT`/`REDIS_PORT` in `.env`.
