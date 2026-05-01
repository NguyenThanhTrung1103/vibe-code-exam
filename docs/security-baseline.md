# Security Baseline (Phase 09)

Phase 09 hardens the app for public exposure (Phase 11). This document
captures the controls, where they live, and the residual risks accepted
for the MVP.

## Controls

| Control | Module | Notes |
|---------|--------|-------|
| Security headers (CSP, X-Frame, X-CTO, Referrer-Policy, Permissions-Policy) | `app/security/headers.py` | applied to every response |
| HSTS | `app/security/headers.py` | gated on `Settings.is_production` |
| Trusted proxy headers | `app/security/proxy.py` | installed in non-`local`/`test` envs only |
| HTML / Markdown sanitization | `app/security/sanitize.py` | bleach allow-list + `markdown-it` (`html=False`) |
| File upload validation (XLSX) | `app/security/upload_validator.py` | extension + magic bytes + size cap |
| Per-route rate limits | `app/security/rate_limits.py` | Redis sliding window, dependency-injected |
| Production-safe error pages | `app/security/error_handler.py` | active in `prod` / `staging` only |
| Request-ID propagation | `app/middleware.py` (Phase 03) | flows to logs + audit + Sentry |
| CSRF | `app/auth/csrf.py` (Phase 03) | every state-changing route |
| RBAC | `app/auth/permissions.py` (Phase 03) | distinguishes 401 vs 403 |
| Login rate limit | `app/auth/rate_limit.py` (Phase 03) | per-IP + per-identifier |

## Rate-limit policy (`app/security/rate_limits.py`)

| Endpoint | Limit |
|----------|-------|
| `POST /auth/register` | 5 / hour / IP |
| `POST /attempts/start` | 30 / minute / user |
| `POST /attempts/{id}/q/{n}/answer` | 60 / minute / user |
| `POST /questions/{id}/reports` | 30 / hour / user |
| `POST /admin/imports` | 5 / hour / admin |
| `GET /search/exams` | 60 / minute / IP |
| `GET /` (public landing) | 60 / minute / IP |

Login (`POST /auth/login`) keeps the Phase 03 dual-scope limit
(5/min/IP, 20/h/account) and is not migrated to the new factory.

## CSP (initial policy, prod)

```
default-src 'self';
img-src    'self' data:;
style-src  'self' 'unsafe-inline';
script-src 'self' 'unsafe-inline';
form-action 'self';
frame-ancestors 'none';
base-uri 'self';
```

`'unsafe-inline'` is intentional for Phase 1 to keep HTMX/Alpine inline
attributes working. Defense-in-depth comes from bleach sanitization on
import (Phase 05) and on render (Phase 09 `render_md` filter). Move to
nonce/hash CSP in Phase 2 — not a Phase 1 exit gate.

## Bleach allow-list (`app/security/sanitize.py`)

```python
ALLOWED_TAGS  = ["p","strong","em","code","pre","ul","ol","li","a",
                 "h2","h3","h4","blockquote","br","hr"]
ALLOWED_ATTRS = {"a": ["href","title","rel"], "code": ["class"]}
ALLOWED_PROTOCOLS = ["http","https","mailto"]
# bleach.linkify forces rel="noopener noreferrer nofollow" + target="_blank"
```

`markdown-it` runs with `html=False`, so raw HTML in user input is
escaped to text rather than parsed. Tests assert that no live `<script>`,
`<iframe>`, `<svg>`, `<body>`, `<style>`, `<link>`, `<meta>`, `<object>`
tag and no live event-handler attribute (`on*=`) survives. Escaped text
(e.g. `&lt;script&gt;`) is acceptable — it cannot execute.

## File upload validator (`app/security/upload_validator.py`)

`validate_xlsx_bytes(data, *, max_bytes, filename)` enforces:

1. Filename is non-empty.
2. Extension is `.xlsx` (case-insensitive).
3. Body is non-empty and ≤ `max_bytes` (`Settings.import_max_bytes`,
   default 25 MiB).
4. First 4 bytes are `PK\x03\x04` (the ZIP magic; `.xlsx` is a ZIP).

Browser-supplied `Content-Type` is **not** trusted. The Phase 05 admin
import wizard delegates to this validator.

## Trusted-proxy header policy

In `local` / `test` envs the app listens directly on `127.0.0.1:8001`;
`X-Forwarded-*` is irrelevant. In `dev` / `staging` / `prod`,
`uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware` is installed
with `trusted_hosts="127.0.0.1"`. Phase 11 binds Gunicorn to a unix
socket served by Nginx on the same loopback, so the upstream peer is
always trusted.

## Residual risks (accepted for Phase 1)

* **No 2FA** — admin password compromise is the highest-impact attack.
  Mitigations: strong-password policy, login lockout (Phase 03), audit
  log on all mutations.
* **CSP `'unsafe-inline'`** — required by HTMX/Alpine inline events.
  Mitigation: bleach + magic + tests.
* **No ClamAV** on uploads — XLSX magic check is best-effort. Phase 2
  adds an AV hook.
* **`/auth/register` is open** — flagged for Phase 12 to gate behind
  invite/admin-issued accounts before public soft-launch.

## Test surface

`tests/security/`:

* `test_headers.py` — every response carries the headers; HSTS not in dev.
* `test_sanitize.py` — bleach allow-list, link hardening, XSS payloads.
* `test_upload_validator.py` — magic + size + extension cases.
* `test_rate_limits.py` — Redis sliding window; fail-closed on outage.
* `test_csrf_coverage.py` — every mutating POST rejects without CSRF.
* `test_xss_regressions.py` — corpus of payloads neutralised end-to-end.

Real-DB tests (`EXAM_PLATFORM_TEST_REAL_DB=1`) flush all `rl:*` keys
between tests so per-route limits don't bleed across the suite.
