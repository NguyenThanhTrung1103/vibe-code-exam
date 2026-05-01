"""SQLAlchemy 2.0 engine, session, and FastAPI session dependency.

Phase 01 only sets up the engine plumbing — schema lands in Phase 02 (Alembic).
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.base import Base  # re-export for backwards compatibility

__all__ = ["Base", "engine", "SessionLocal", "get_session"]


def _build_engine() -> Engine:
    settings = get_settings()
    connect_args: dict[str, object] = {}
    # psycopg honours `connect_timeout` (libpq). Short timeout keeps /healthz
    # responsive when the database is unreachable in dev.
    if settings.database_url.startswith(("postgresql", "postgres")):
        connect_args["connect_timeout"] = 3
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        echo=settings.debug and not settings.is_production,
        connect_args=connect_args,
    )


engine: Engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped DB session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
