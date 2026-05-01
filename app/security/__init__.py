"""Phase 09 — security hardening package.

Sub-modules:
* `headers`           — SecurityHeadersMiddleware (CSP, X-Frame, HSTS-in-prod, …)
* `sanitize`          — bleach-backed Markdown render helper
* `upload_validator`  — extension + magic + size validation for uploads
* `rate_limits`       — per-route Redis sliding-window rate-limit dependency
* `error_handler`     — production-safe exception handlers
* `proxy`             — install ProxyHeadersMiddleware behind Nginx (Phase 11)
"""
