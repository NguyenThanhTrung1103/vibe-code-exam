"""FastAPI application factory.

Run locally with: `uvicorn app.main:app --reload`.
"""

from __future__ import annotations

import sentry_sdk
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sentry_sdk.integrations.fastapi import FastApiIntegration
from starlette.middleware.gzip import GZipMiddleware

from app.config import Settings, get_settings
from app.logging import configure_logging, get_logger
from app.middleware import RequestIdMiddleware
from app.paths import STATIC_DIR, TEMPLATES_DIR
from app.routers import attempts, auth, health, practice, reports
from app.routers.admin import audit as admin_audit
from app.routers.admin import community_sources as admin_community_sources
from app.routers.admin import courses as admin_courses
from app.routers.admin import exams as admin_exams
from app.routers.admin import imports as admin_imports
from app.routers.admin import product_versions as admin_product_versions
from app.routers.admin import providers as admin_providers
from app.routers.admin import question_reports as admin_question_reports
from app.routers.admin import questions as admin_questions
from app.routers.admin import topics as admin_topics
from app.routers.public import exams as public_exams
from app.routers.public import home as public_home
from app.routers.public import legal as public_legal
from app.routers.public import search as public_search
from app.routers.public import vendors as public_vendors
from app.security.error_handler import install_error_handlers
from app.security.headers import SecurityHeadersMiddleware
from app.security.proxy import install_proxy_headers
from app.security.sanitize import render_markdown


def _init_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return
    # Phase 10 — release tag plumbed from env so deploy script (Phase 11)
    # can stamp every event with the git SHA. Falls back to None gracefully.
    import os

    release = os.environ.get("SENTRY_RELEASE") or os.environ.get("APP_RELEASE") or None
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        release=release,
        integrations=[FastApiIntegration()],
        send_default_pii=False,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    _init_sentry(settings)

    log = get_logger("startup")
    log.info("app_create", env=settings.env, debug=settings.debug)

    app = FastAPI(
        title="Exam Platform",
        version="0.1.0",
        debug=settings.debug,
    )

    # Middleware order: outermost first. Request-ID needs to wrap everything;
    # SecurityHeadersMiddleware runs *inside* it so the headers it sets see
    # the final response. ProxyHeadersMiddleware (when installed) runs first
    # in non-local envs so X-Forwarded-* are normalized before any IP-based
    # rate limit reads `request.client.host`.
    install_proxy_headers(app, settings)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    # Production-safe error handlers (no-op in dev/local/test).
    install_error_handlers(app, settings)

    # Static + templates
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    # Phase 09 — register `render_md` filter for safe Markdown rendering.
    templates.env.filters["render_md"] = render_markdown
    app.state.templates = templates

    # Routers — public first, then auth, then admin (order is cosmetic).
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(public_home.router)
    app.include_router(public_vendors.router)
    app.include_router(public_exams.router)
    app.include_router(public_search.router)
    app.include_router(public_legal.router)
    app.include_router(admin_audit.router)
    app.include_router(admin_providers.router)
    app.include_router(admin_product_versions.router)
    app.include_router(admin_courses.router)
    app.include_router(admin_exams.router)
    app.include_router(admin_topics.router)
    app.include_router(admin_imports.router)
    app.include_router(admin_questions.router)
    app.include_router(admin_community_sources.router)
    app.include_router(admin_question_reports.router)
    app.include_router(practice.router)
    app.include_router(attempts.router)
    app.include_router(reports.router)

    return app


app = create_app()
