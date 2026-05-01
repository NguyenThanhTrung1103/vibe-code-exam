"""Liveness + readiness routes.

* `/healthz` (Phase 02) — cheap. DB SELECT 1 + Redis PING.
* `/readyz`  (Phase 10) — same plus "alembic head matches current revision".

Distinct semantics: uptime probes hammer `/healthz`; deploy / readiness
gates hit `/readyz` once after rollout.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.deps import RedisDep, SessionDep

router = APIRouter(tags=["health"])

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _ping_db(session: Session) -> str:
    try:
        session.execute(text("SELECT 1"))
        return "ok"
    except SQLAlchemyError:
        return "down"


def _ping_redis(client: Redis) -> str:
    try:
        return "ok" if client.ping() else "down"
    except (RedisError, OSError):
        return "down"


def _migration_state(session: Session) -> tuple[str, str | None, str | None]:
    """Return (`status`, `current_rev`, `head_rev`).

    * `ok` — DB revision equals alembic head.
    * `behind` — DB revision is older than head.
    * `unknown` — couldn't read alembic config or DB; treated as "not ready".
    """
    try:
        cfg = AlembicConfig(str(_ALEMBIC_INI))
        script = ScriptDirectory.from_config(cfg)
        head = script.get_current_head()
        bind = session.connection()
        ctx = MigrationContext.configure(bind)
        current = ctx.get_current_revision()
    except Exception:  # noqa: BLE001 — readiness check must never raise
        return "unknown", None, None
    if current and head and current == head:
        return "ok", current, head
    return "behind", current, head


@router.get("/healthz", summary="Liveness + dependency check")
def healthz(session: SessionDep, redis: RedisDep) -> JSONResponse:
    db_status = _ping_db(session)
    redis_status = _ping_redis(redis)
    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
    body = {"status": overall, "db": db_status, "redis": redis_status}
    status_code = 200 if overall == "ok" else 503
    return JSONResponse(body, status_code=status_code)


@router.get("/readyz", summary="Readiness + migration-head check")
def readyz(session: SessionDep, redis: RedisDep) -> JSONResponse:
    db_status = _ping_db(session)
    redis_status = _ping_redis(redis)
    mig_status, current, head = _migration_state(session)
    overall = (
        "ok" if db_status == "ok" and redis_status == "ok" and mig_status == "ok" else "not_ready"
    )
    body = {
        "status": overall,
        "db": db_status,
        "redis": redis_status,
        "migrations": {"status": mig_status, "current": current, "head": head},
    }
    status_code = 200 if overall == "ok" else 503
    return JSONResponse(body, status_code=status_code)
