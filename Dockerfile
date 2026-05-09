# syntax=docker/dockerfile:1.7
#
# Exam Platform — production-ready image
#
# Stage layout:
#   * builder  — installs uv + project deps into /opt/venv (cacheable layer)
#   * runtime  — copies the venv + source, drops privileges, runs uvicorn
#
# Build:   docker build -t exam-platform:local .
# Run:     docker run --rm -p 8000:8000 --env-file .env exam-platform:local
# Compose: docker compose up --build app
#
# The image is the same artifact for web + worker. The compose `command:`
# overrides the entrypoint when running RQ workers, so no second image.

# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# psycopg builds against libpq; build-essential needed for any sdist wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Pin uv (matches our developer toolchain).
RUN pip install --no-cache-dir "uv>=0.5"

WORKDIR /build

# Lock + manifest first so dependency layer caches across source-only edits.
COPY pyproject.toml uv.lock README.md ./

# Production-only install (no dev extras inside runtime image).
RUN uv sync --frozen --no-dev

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    APP_HOME=/srv/exam-platform

# libpq5 + curl (curl is used by HEALTHCHECK).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — never run the web server as root.
RUN groupadd --system --gid 1000 exam \
    && useradd  --system --uid 1000 --gid exam --home-dir ${APP_HOME} --shell /usr/sbin/nologin exam

# Copy the venv built in stage 1.
COPY --from=builder /opt/venv /opt/venv

WORKDIR ${APP_HOME}

# Copy source. Order: lowest-churn first so most rebuilds reuse the venv layer.
COPY --chown=exam:exam pyproject.toml uv.lock alembic.ini README.md ./
COPY --chown=exam:exam migrations ./migrations
COPY --chown=exam:exam scripts ./scripts
COPY --chown=exam:exam app ./app

# Uploads directory referenced by Settings.uploads_dir; must be writable.
RUN install -d -o exam -g exam ${APP_HOME}/uploads

USER exam

EXPOSE 8000

# Probe /healthz — the same endpoint our LXC deploy uses.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# tini reaps zombies and forwards signals to uvicorn cleanly.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command runs the web server. Override in compose for the RQ worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
