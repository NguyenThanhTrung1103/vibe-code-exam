---
phase: 01
title: Project scaffolding & local dev environment
status: completed
completed_at: 2026-04-29
effort: 2 days
priority: high
depends_on: []
---

# Phase 01 — Project Scaffolding & Local Dev Environment

## Context Links
- PRD §29 (tech stack), §30.1 (Phase 1 modules)
- Plan overview: `plan.md`
- Decision: FastAPI + PostgreSQL 14 + Redis + RQ + Jinja2 + HTMX + Alpine.js. Co-tenant on existing Ubuntu LXC.

## Overview
Set up the FastAPI project skeleton, dependency management, local Docker Compose for dev, linting/formatting/secret-scan pre-commit hooks, structured logging, basic Sentry wiring, and a healthcheck route. Goal: any subsequent phase can `git pull && uvicorn app.main:app --reload` and start working.

## Key Insights
- Co-tenant deployment means production app code lives at `/srv/exam-platform/`; we mirror that locally as `app/`.
- Jinja + HTMX is uncommon in Python tutorials — budget 1 day of HTMX onboarding (`hyperscript` not needed at MVP; Alpine handles client-side state).
- Use `pyproject.toml` (PEP 621) with `uv` or `pip-tools`. Avoid `requirements.txt`-only — lockfiles are non-negotiable.
- `python-decouple` or `pydantic-settings` for env management; do not use `os.getenv` scattered.
- Sentry SDK initialized at app startup; gated by `SENTRY_DSN` env.

## Requirements
**Functional**
- Local dev runs via `docker compose up` (Postgres + Redis + app + Mailhog).
- App runs via `uvicorn app.main:app --reload` outside Docker too.
- `/healthz` returns `{"status":"ok","db":"ok","redis":"ok"}` (200) or 503 if any dependency down.
- Pre-commit hooks block commits with secrets, lint errors, or unformatted code.

**Non-functional**
- Lockfile committed (`uv.lock` or `requirements.lock`).
- All env vars documented in `.env.example`.
- App boots in <2 s on local dev.

## Architecture

```
exam-platform/
├── app/
│   ├── __init__.py
│   ├── main.py                       # FastAPI factory + middleware
│   ├── config.py                     # pydantic-settings
│   ├── db.py                         # SQLAlchemy engine + session
│   ├── deps.py                       # FastAPI dependencies
│   ├── logging.py                    # structlog setup
│   ├── routers/                      # http routes
│   ├── services/                     # business logic
│   ├── models/                       # SQLAlchemy models (Phase 02)
│   ├── schemas/                      # Pydantic I/O schemas
│   ├── templates/                    # Jinja templates
│   ├── static/                       # CSS, HTMX, Alpine
│   ├── workers/                      # RQ jobs (Phase 02+ uses)
│   └── utils/
├── migrations/                       # Alembic (Phase 02)
├── tests/
├── scripts/                          # CLI utilities
├── docker-compose.yml                # local dev only
├── pyproject.toml
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
└── README.md
```

## Related Code Files
**Create**
- `pyproject.toml`, `uv.lock`
- `.env.example`, `.gitignore`, `.pre-commit-config.yaml`, `.editorconfig`
- `app/main.py`, `app/config.py`, `app/db.py`, `app/logging.py`, `app/deps.py`
- `app/routers/health.py`
- `app/templates/base.html`, `app/templates/_layout/*`
- `app/static/css/base.css`, `app/static/js/htmx.min.js`, `app/static/js/alpine.min.js`
- `docker-compose.yml`
- `tests/conftest.py`, `tests/test_health.py`
- `README.md`

## Implementation Steps

1. **Initialize repo.** `git init`, add `.gitignore` (Python, venv, IDE, `.env`, `*.log`, `.pytest_cache`, `dist/`).
2. **Create `pyproject.toml`** with deps:
   - `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`
   - `sqlalchemy>=2.0`, `psycopg[binary]`, `alembic`
   - `pydantic-settings`
   - `redis`, `rq`
   - `structlog`, `sentry-sdk[fastapi]`
   - `passlib[argon2]`, `itsdangerous`
   - `bleach`, `markdown-it-py`
   - `openpyxl`
   - dev: `pytest`, `pytest-asyncio`, `httpx`, `ruff`, `black`, `mypy`, `pre-commit`, `gitleaks`
3. **Lockfile.** `uv pip compile` or `pip-compile` → commit.
4. **Write `app/config.py`** with `Settings(BaseSettings)`: `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `SESSION_COOKIE_NAME`, `SENTRY_DSN`, `ENV`, `DEBUG`, `LOG_LEVEL`. Read from `.env`.
5. **Write `app/db.py`**: SQLAlchemy 2.0 engine, sessionmaker, `get_session()` FastAPI dep.
6. **Write `app/logging.py`**: structlog JSON renderer in prod, console in dev. Inject request_id via middleware.
7. **Write `app/main.py`**: factory `create_app() -> FastAPI`, middleware (request_id, GZip, error handler), Sentry init. **Stub for production:** document where **`ProxyHeadersMiddleware`** (or trusted proxy settings) will be enabled when behind Nginx (full config in Phase 09/11) — local `uvicorn` without proxy may leave it off or use a dev-only trusted list.
8. **Write `/healthz`** (router) — pings DB + Redis; returns 503 if either fails.
9. **Write base Jinja template** with HTMX + Alpine via local static files (no CDN — avoids SRI complexity at MVP).
10. **Author `.pre-commit-config.yaml`** with hooks: ruff, black, mypy (loose at MVP), gitleaks.
11. **Write `docker-compose.yml`** with services: `db` (Postgres 14), `redis` (Redis 7), `app` (build from Dockerfile), `mailhog` (for password-reset emails later).
12. **Write minimal `Dockerfile`** (Python 3.12-slim, install deps, COPY app, run uvicorn).
13. **Write `tests/conftest.py`** with FastAPI TestClient fixture.
14. **Write `tests/test_health.py`** asserting 200 from `/healthz` with mocked DB/Redis.
15. **Write `README.md`** — local setup in 3 commands.
16. **Document HTMX patterns** for the team in `README.md` (form post → partial response, `hx-target`, `hx-swap`).
17. **Run pre-commit on full repo**, fix until green.

## Todo List
- [ ] Repo initialized, `.gitignore` and `.editorconfig` committed
- [ ] `pyproject.toml` + lockfile committed
- [ ] `app/config.py` reads from `.env` via pydantic-settings
- [ ] `app/db.py` exposes `get_session`
- [ ] `app/main.py` runs with `uvicorn app.main:app --reload`
- [ ] `/healthz` returns 200 with DB+Redis OK
- [ ] Sentry init gated by `SENTRY_DSN`
- [ ] Base Jinja layout + HTMX + Alpine wired (local static)
- [ ] `docker-compose.yml` brings up db + redis + app
- [ ] Pre-commit hooks installed and passing
- [ ] `tests/test_health.py` passes
- [ ] README has 3-command local setup

## Success Criteria
- `docker compose up` → `/healthz` returns 200 within 30 s on a clean machine.
- `pytest` passes locally.
- Pre-commit blocks `git commit` if `.env` is staged with values.
- A fresh dev runs the app in <10 min from clone.

## Risk Assessment
- **HTMX onboarding** — devs new to HTMX may resist. Mitigate by including 2-3 worked examples in README.
- **Dependency drift** — without lockfile, `pip install` produces different envs. Lockfile committed mitigates.
- **Docker on Windows dev box** — WSL2 backend required. Document in README.

## Security Considerations
- **Reverse proxy (later):** Phase 09/11 require correct handling of **`X-Forwarded-Proto`**, **`X-Forwarded-For`**, and **`Host`** when the app sits behind Nginx — only trust headers from the proxy, not from browsers directly.
- `.env` in `.gitignore`; `.env.example` only.
- `gitleaks` pre-commit blocks secret commits.
- Default `SECRET_KEY` in `.env.example` is `change-me-before-prod`.
- No CDN scripts (HTMX/Alpine local) — eliminates supply-chain SRI concerns at MVP.

## Next Steps
Phase 02 — Database migrations and Postgres co-tenant setup. Once `app/db.py` connects, Alembic baseline + first migration land.
