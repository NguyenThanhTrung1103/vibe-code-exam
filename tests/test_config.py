"""Config loading from env."""

from __future__ import annotations

from app.config import Settings


def test_settings_defaults_resolve(monkeypatch) -> None:
    # Clear any user-set vars so we observe library defaults.
    for key in ("ENV", "DEBUG", "LOG_LEVEL", "SENTRY_DSN", "SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.env == "local"
    assert s.is_local is True
    assert s.is_production is False
    assert s.sentry_dsn is None


def test_settings_env_override(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    s = Settings(_env_file=None)
    assert s.env == "prod"
    assert s.is_production is True
    assert s.log_level == "WARNING"
