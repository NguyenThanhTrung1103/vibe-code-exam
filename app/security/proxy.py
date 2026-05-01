"""Trusted-proxy header handling (Phase 09 — coordinates with Phase 11 Nginx).

Behind Nginx + unix socket the upstream IP is always the local socket
peer; Uvicorn's built-in `ProxyHeadersMiddleware` reads `X-Forwarded-*`
only from `forwarded_allow_ips`. We default to `127.0.0.1` so direct
internet connections (which won't exist behind Nginx) cannot spoof
`X-Forwarded-Proto=https` to bypass HSTS or `X-Forwarded-For` to dodge
rate limits.

Local dev (no proxy) leaves the headers alone — no behaviour change.
"""

from __future__ import annotations

from fastapi import FastAPI
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import Settings, get_settings


def install_proxy_headers(app: FastAPI, settings: Settings | None = None) -> None:
    """Install ProxyHeadersMiddleware in non-local environments."""
    s = settings or get_settings()
    if s.is_local:
        return
    # Trust the loopback Nginx hop only. Phase 11 binds Gunicorn to a unix
    # socket — the resulting peer IP is loopback, so this allowlist is correct.
    app.add_middleware(
        ProxyHeadersMiddleware,
        trusted_hosts="127.0.0.1",
    )


__all__ = ["install_proxy_headers"]
