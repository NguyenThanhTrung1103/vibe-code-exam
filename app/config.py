"""Application settings loaded from environment via pydantic-settings.

All env vars are documented in `.env.example`. Never call `os.getenv` directly
in business code — read everything through `Settings`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvName = Literal["local", "dev", "staging", "prod", "test"]


class Settings(BaseSettings):
    """Strongly-typed runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment / runtime
    env: EnvName = Field(default="local", description="Deployment environment label.")
    debug: bool = Field(default=True, description="Enable verbose error pages locally.")
    log_level: str = Field(default="INFO", description="Root log level.")

    # HTTP server
    app_host: str = Field(default="127.0.0.1")
    app_port: int = Field(default=8000)

    # Datastores — connection strings only, no parsing into parts
    database_url: str = Field(
        default="postgresql+psycopg://exam_platform_user:exam_platform_pw@localhost:5432/exam_platform_db",
        description="SQLAlchemy URL for the application Postgres database.",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Sessions / security
    secret_key: str = Field(
        default="change-me-before-prod",
        description="Used to sign session cookies and CSRF tokens.",
    )
    session_cookie_name: str = Field(default="exam_session")
    session_ttl_days: int = Field(default=7, description="Session cookie lifetime.")
    admin_reprompt_hours: int = Field(
        default=24,
        description="Admin must re-enter password if `last_password_at` older than this.",
    )

    # Observability
    sentry_dsn: str | None = Field(default=None, description="Empty/None disables Sentry.")

    # Phase 05 — Excel import pipeline
    uploads_dir: Path = Field(
        default=Path("/srv/exam-platform/uploads"),
        description="Base directory for admin-uploaded files (outside any public path).",
    )
    import_max_bytes: int = Field(
        default=25 * 1024 * 1024, description="Max bytes per uploaded XLSX (25 MB)."
    )
    import_max_rows: int = Field(
        default=5000, description="Max data rows accepted from one workbook."
    )
    import_near_duplicate_threshold: float = Field(
        default=0.55,
        description=(
            "pg_trgm similarity threshold for non-blocking near-duplicate "
            "warnings during import. Higher = stricter (fewer warnings). "
            "Default 0.55 catches typos + paraphrases without flooding."
        ),
    )

    @property
    def is_local(self) -> bool:
        return self.env in ("local", "test")

    @property
    def is_production(self) -> bool:
        return self.env == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor — call from FastAPI deps or module-level singletons."""
    return Settings()
