# Docker Deployment

Portable single-host deployment for the Exam Platform. Same `Dockerfile`
works on a developer laptop, the LXC, and any future server / CI runner.

## Stack

| Service | Image | Purpose | Default port |
| --- | --- | --- | --- |
| `app` | built from `Dockerfile` | FastAPI + uvicorn | `${APP_PORT:-8000}` |
| `db` | `postgres:14-alpine` | Application database | `${DB_PORT:-5432}` |
| `redis` | `redis:7-alpine` | Rate limiting, sessions, RQ | `${REDIS_PORT:-6379}` |
| `mailhog` | `mailhog/mailhog:latest` | SMTP capture for dev | SMTP `1025`, UI `8025` |

Volumes (named, persistent across `up`/`down`):

* `exam-pgdata`     → `/var/lib/postgresql/data`
* `exam-redisdata`  → `/data` (Redis AOF)
* `exam-uploads`    → `/srv/exam-platform/uploads`

## Prerequisites

* Docker Engine 20.10+ and Docker Compose v2 (`docker compose`, not `docker-compose`)
* `cp` / `bash` (Linux/macOS) or PowerShell (Windows) for env file copying
* ~2 GB free disk for images + initial DB data

## 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`. The values that **must** change for any non-local deployment:

* `SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`
* `POSTGRES_PASSWORD` — change from the default
* `EXAM_ADMIN_PW` — set before creating the first admin
* `ENV=prod` and `DEBUG=false` for production
* `SENTRY_DSN` — paste your DSN if you want Sentry enabled

`DATABASE_URL` and `REDIS_URL` in `.env` are ignored by compose (compose
overrides them with the in-network hostnames `db` / `redis`); leave them at
the localhost defaults.

## 2. Build the image

```bash
docker compose build
```

The Dockerfile is multi-stage: stage 1 (`builder`) installs uv and project
dependencies into `/opt/venv`; stage 2 (`runtime`) is a minimal `python:3.12-slim`
that only ships `libpq5`, `curl`, `tini`, the venv, and the source. The
container runs as the unprivileged `exam` user (uid 1000).

Result image: `exam-platform:local`. ~ 280 MB.

## 3. Start the stack

```bash
docker compose up -d
```

Wait for the healthchecks to settle (~20 s):

```bash
docker compose ps
```

`db`, `redis`, and `app` should all show `(healthy)`. If `app` flips to
`unhealthy`, see [Troubleshooting](#troubleshooting).

## 4. Run database migrations

**Migration model — read this before deploying:**

* The app **never** creates or alters tables at runtime. `app/db.py` only
  builds an engine; it does **not** call `Base.metadata.create_all(...)`.
  The schema is owned exclusively by Alembic (`migrations/versions/`).
* Migrations are an **explicit deployment step**, not part of container
  boot, so a failing migration cannot loop-restart the app.
* The first ten migrations (`0001` → `0010`) are required: they create
  the schema, register Postgres ENUM types, install the `pg_trgm`
  extension (used by the import near-duplicate index), and seed a
  baseline catalog (1 provider "Fortinet", 1 product "FortiOS 7.4",
  1 course/exam "NSE4" stub, 5 source domains). Migration `0002` is
  idempotent (`ON CONFLICT DO NOTHING` / `WHERE NOT EXISTS`), so re-runs
  on an existing DB are safe and never duplicate seed rows.
* `alembic.ini` does **not** hardcode a database URL — `migrations/env.py`
  reads it from `app.config.Settings`, which itself reads `DATABASE_URL`
  from `.env`. There is no risk of pointing alembic at a different DB
  than the app.

### Fresh database

```bash
docker compose up -d                              # Postgres + Redis + app boot
docker compose exec app alembic upgrade head     # creates schema + seeds
docker compose exec -e EXAM_ADMIN_PW="$ADMIN_PW" app \
  python -m scripts.create_admin --email admin@example.com --username admin
curl -fsS http://localhost:8000/readyz             # 200 once schema == head
```

`docker compose up` does **not** create the application schema — Postgres
just runs its own initdb to create the empty `${POSTGRES_DB}` database
(default name `exam_platform_db`). All tables, ENUM types, indexes, and
seed rows come from `alembic upgrade head`.

### Existing database (upgrading an already-deployed instance)

Before applying new migrations on a populated database:

1. **Take a backup** (see §9):
   ```bash
   docker compose exec -T db \
     pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     | gzip > exam-db-pre-upgrade-$(date +%Y%m%d-%H%M).sql.gz
   ```
2. **Inspect the diff** between current head and target head:
   ```bash
   docker compose exec app alembic current    # what's applied
   docker compose exec app alembic heads      # what's available
   docker compose exec app alembic history    # human-readable list
   ```
3. **Apply** the upgrade:
   ```bash
   docker compose exec app alembic upgrade head
   ```
4. **Verify** the app reports `migrations.status: ok` on `/readyz`:
   ```bash
   curl -sS http://localhost:8000/readyz | python -c \
     "import json,sys; print(json.load(sys.stdin)['migrations'])"
   ```
5. If something goes wrong, restore from the backup (§9 Restore) and
   investigate before retrying.

### Authoring new migrations

```bash
docker compose exec app alembic revision --autogenerate -m "describe change"
```

Always review the generated SQL — autogenerate misses constraint renames,
ENUM membership changes, and server defaults. Re-run on a throwaway DB
before committing.

## 5. Create the first admin

```bash
docker compose exec -e EXAM_ADMIN_PW='YourStrongPassword!' app \
  python -m scripts.create_admin --email admin@example.com --username admin
```

The script is idempotent — re-running with the same email is safe.

## 6. Health and smoke

```bash
curl http://localhost:8000/healthz   # → {"status":"ok",...}
curl http://localhost:8000/readyz    # → 200 once db + redis are reachable
curl -sI http://localhost:8000/practice | head -1   # → HTTP/1.1 200 OK
```

Open in a browser:

* http://localhost:8000/                      — homepage
* http://localhost:8000/practice              — practice catalog
* http://localhost:8000/admin                 — admin (login required)
* http://localhost:8025                       — MailHog UI

## 7. Logs

```bash
docker compose logs -f app          # follow web logs
docker compose logs --since 10m db  # last 10 min of db logs
docker compose logs --tail=200      # last 200 lines, all services
```

The app logs in JSON when `ENV=prod` and console-rendered when `ENV=local`
(see `app/logging.py`). Each request has a `request_id` bound to every log
record for correlation.

## 8. Restart / stop / clean

```bash
# Restart only the app (e.g. after pulling a new image tag)
docker compose restart app

# Stop everything but keep volumes (data preserved)
docker compose down

# Stop + remove volumes (THIS DROPS THE DATABASE)
docker compose down -v

# Rebuild after Dockerfile/source changes
docker compose up -d --build app
```

## 9. Backup & restore the Postgres volume

### Backup (on the host running compose)

```bash
docker compose exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  | gzip > exam-db-$(date +%Y%m%d-%H%M).sql.gz
```

`-T` disables TTY allocation so the redirect captures stdout cleanly.

### Restore

```bash
gunzip -c exam-db-YYYYMMDD-HHMM.sql.gz \
  | docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

### Volume snapshot (alternative — full file-level copy)

```bash
docker run --rm \
  -v exam_exam-pgdata:/from \
  -v "$PWD":/to \
  alpine tar -czf /to/exam-pgdata-$(date +%Y%m%d).tar.gz -C /from .
```

(The volume name is `<projectdir>_exam-pgdata`; check with `docker volume ls`.)

## 10. Deploying on a new server

```bash
git clone <repo-url> exam-platform
cd exam-platform
cp .env.example .env
# Edit .env — at minimum: SECRET_KEY, POSTGRES_PASSWORD, EXAM_ADMIN_PW, ENV, DEBUG
docker compose up -d --build
docker compose exec app alembic upgrade head
docker compose exec -e EXAM_ADMIN_PW="$ADMIN_PW" app \
  python -m scripts.create_admin --email admin@example.com --username admin
```

For production behind a reverse proxy (nginx, Caddy, Traefik, Cloudflare):

* Terminate TLS at the proxy.
* Forward `Host`, `X-Forwarded-Proto`, `X-Forwarded-For` headers to the
  container — uvicorn is started with `--proxy-headers --forwarded-allow-ips *`
  in the Dockerfile so it trusts those.
* Bind the app port to `127.0.0.1:8000` on the host (edit `docker-compose.yml`
  → `ports: ["127.0.0.1:8000:8000"]`) so only the proxy can reach it.

### Production hardening checklist

By default the compose file is **safe by construction** for the data plane:
`db`, `redis`, and `mailhog` ports are bound to `127.0.0.1` (loopback only)
via `EXPOSE_HOST=127.0.0.1` in `.env.example`. The LAN cannot reach
Postgres or Redis. Other compose services reach them through the internal
network using the `db` / `redis` hostnames regardless of host binding.

Before flipping to production:

* [ ] `ENV=prod`, `DEBUG=false` in `.env`
* [ ] `SECRET_KEY` rotated to a fresh `secrets.token_urlsafe(48)` value
* [ ] `POSTGRES_PASSWORD` changed from the default
* [ ] `EXPOSE_HOST=127.0.0.1` confirmed (the default — do **not** set it to
      `0.0.0.0` unless you intentionally need external DB access and have a
      firewall in front)
* [ ] `app` service either bound to `127.0.0.1:8000:8000` (reverse proxy on
      same host) or to a dedicated interface; never expose `0.0.0.0:8000`
      directly to the internet without a TLS-terminating proxy
* [ ] `mailhog` removed or kept loopback-only; not pointed at by SMTP-using
      code in prod (use a real SMTP relay)
* [ ] Reverse proxy forwards `X-Forwarded-Proto: https` so cookies set as
      Secure resolve correctly
* [ ] Postgres backups scheduled (see §9)
* [ ] Sentry DSN set so production errors get reported
* [ ] Log volume / rotation configured at the host or Docker daemon level
      (`docker compose logs` is fine for ad-hoc; for retention use a
      driver like `json-file` with `max-size`, or ship logs to Loki/ELK)

## 11. CI/CD-ready notes

The image is the only artefact you need. A typical pipeline:

```yaml
# .gitlab-ci.yml (sketch — not committed yet)
stages: [test, build, deploy]

test:
  stage: test
  image: python:3.12-slim
  services:
    - postgres:14-alpine
    - redis:7-alpine
  variables:
    POSTGRES_USER: exam_platform_user
    POSTGRES_PASSWORD: exam_platform_pw
    POSTGRES_DB: exam_platform_db
    DATABASE_URL: postgresql+psycopg://exam_platform_user:exam_platform_pw@postgres:5432/exam_platform_db
    REDIS_URL: redis://redis:6379/0
    EXAM_PLATFORM_TEST_REAL_DB: "1"
  script:
    - pip install uv && uv sync --extra dev
    - uv run alembic upgrade head
    - uv run ruff check . && uv run ruff format --check .
    - uv run pytest

build:
  stage: build
  image: docker:27
  services: [docker:27-dind]
  script:
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"
  only: [main]

deploy:
  stage: deploy
  script:
    - ssh "$DEPLOY_HOST" "cd /srv/exam-platform && \
        docker compose pull app && \
        docker compose up -d --wait db redis && \
        docker compose up -d app && \
        docker compose exec -T app alembic upgrade head && \
        curl -fsS http://127.0.0.1:8000/readyz"
  only: [main]
```

**Why this exact ordering matters:**

1. `pull` first so the new image is local before any container shuffle.
2. `up -d --wait db redis` brings backends to `healthy` *before* the app
   starts, so the app's first `/healthz` probe succeeds.
3. `up -d app` (re)creates the app container with the new image. At this
   point the app responds 200 on `/healthz` (db+redis ok) but `/readyz`
   may report `migrations.status: behind` if the new image ships
   migrations the DB hasn't applied yet.
4. `alembic upgrade head` advances the schema. Idempotent — running
   against an already-current DB is a no-op.
5. `curl /readyz` confirms `db=ok`, `redis=ok`, `migrations.status=ok`
   before the deploy job exits green.

For first-time deploy on a fresh server, add one more step **before** the
ssh block: `docker compose exec -e EXAM_ADMIN_PW=... app python -m
scripts.create_admin --email ... --username ...`. Skip on subsequent
deploys (the script refuses to overwrite an existing user, exit code 3).

GitHub Actions equivalent: same shape — `services:` for postgres/redis, build with
`docker/build-push-action@v6`, deploy via SSH. Worth adding once the team is
ready; not needed for first-pass portability.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `app` stuck `unhealthy` | DB not migrated yet | `docker compose exec app alembic upgrade head` |
| `app` crashloops with `secret_key=change-me-before-prod` warning | `.env` missing or default | Set `SECRET_KEY` in `.env`, restart |
| `pg_isready` repeatedly fails | Volume corruption from prior init with different password | `docker compose down -v` (drops DB), reset `.env`, `up -d` |
| Cannot reach `:8000` from another machine | Compose binds to `0.0.0.0:8000` by default; check host firewall | `sudo ufw allow 8000/tcp` (or whatever) |
| Stale image after edit | Build cache | `docker compose build --no-cache app` |

## Limitations / future work

* No `worker` service yet — `app/workers/` is empty. Add when RQ jobs land.
* No nginx in compose — TLS termination is expected to be external (matches
  the LXC's nginx + cloudflared topology). Add a `proxy:` service if a
  self-contained TLS deployment is needed.
* Backups are manual cron-style; an `ofelia` or `pg_back` sidecar could
  automate them.
* Alembic is run by hand on deploy. A small `entrypoint.sh` could optionally
  run migrations before uvicorn — left out for safety (a failed migration
  shouldn't loop-restart the app container).
