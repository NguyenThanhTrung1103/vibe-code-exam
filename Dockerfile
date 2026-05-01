# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

# System deps for psycopg + healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/exam-platform

# Install uv (fast, deterministic resolver/installer)
RUN pip install --no-cache-dir "uv>=0.5"

# Copy lockfile + manifest first for caching
COPY pyproject.toml uv.lock README.md ./

# Production install (no dev extras inside the runtime image)
RUN uv sync --frozen --no-dev

# Copy app source
COPY app ./app
COPY scripts ./scripts

ENV PATH="/srv/exam-platform/.venv/bin:${PATH}"

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=4 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
