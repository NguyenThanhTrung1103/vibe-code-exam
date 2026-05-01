---
phase: 09
title: Security hardening & rate limiting
status: pending
effort: 2-3 days
priority: high
depends_on: [03]
parallel_ok_after: [03]
---

# Phase 09 — Security Hardening & Rate Limiting

## Context Links
- PRD §21 (security & access control), §22 (untrusted content / prompt injection prep)
- Phase 03 already shipped basic auth/CSRF/login rate limit; this phase tightens everything else

## Overview
Layer the security baseline atop the working app: HTML sanitization policies, CSP header, secure-cookie verification, rate limits across all sensitive endpoints, file-upload defenses, request-id propagation, security regression tests. Defensive hardening before public exposure in Phase 11.

## Key Insights
- Most XSS risk lives at the **render path** for imported content. Phase 05 sanitizes on import; this phase adds re-sanitization on render and a strict CSP that catches anything that slips through.
- **CSP at MVP**: pragmatic. Allow `'self'` + `'unsafe-inline'` for inline event handlers used by HTMX/Alpine where needed. No `unsafe-eval`. **MVP explicitly accepts** `'unsafe-inline'` under control (defense in depth via sanitize + CSP). **Phase 2 hardening:** move to **nonce- or hash-based `script-src` / `style-src`** where feasible — **not** a Phase 1 exit gate; do not block shipping on nonce CSP.
- **Behind Nginx:** the app must **not** trust `X-Forwarded-*` / `Host` from arbitrary clients. Only the reverse proxy (127.0.0.1 / unix socket) forwards requests; configure **Starlette/FastAPI `ProxyHeadersMiddleware`** (or equivalent) with **`trusted_hosts` / known proxy count** so `request.url.scheme`, client IP for rate limits, and secure cookies see **HTTPS** and the real client IP. Reject or ignore forwarded headers on direct unwired access. Coordinate with Phase 11 vhost headers.
- **Rate limits** use Redis sliding window (Phase 03 helper); apply consistently per-route via dependency.
- **Request ID** flows from middleware → logs → audit_logs → Sentry — single thread of investigation.
- **No 2FA at MVP** (PRD §35 #16). Document residual risk.

## Requirements
**Functional**
- All form POSTs require valid CSRF token (Phase 03 helper); add tests covering every admin route.
- All user-submitted text rendered through bleach with strict allow-list.
- File uploads pass extension allow-list + magic-number check + size cap.
- CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy headers on all responses.
- Rate limits on every mutation route (see table below).
- 429 responses include `Retry-After`.
- Force HTTPS via HSTS in prod (gated on `ENV=prod`).

**Non-functional**
- Security middleware adds <2 ms to request latency.
- Bleach sanitization <1 ms per typical question text.

## Architecture

```
app/
├── security/
│   ├── headers.py              # SecurityHeadersMiddleware
│   ├── sanitize.py             # bleach allow-list + Markdown render
│   ├── upload_validator.py     # ext + magic number + size
│   └── rate_limits.py          # named limits + dependency factory
├── middleware/
│   ├── request_id.py
│   └── error_handler.py        # safe error rendering
└── tests/security/
    ├── test_headers.py
    ├── test_sanitize.py
    ├── test_csrf.py
    ├── test_rate_limits.py
    ├── test_upload_validator.py
    └── test_xss_regressions.py
```

### Rate-limit policy table

| Endpoint | Limit |
|----------|-------|
| `POST /auth/login` | 5/min/IP, 20/hour/account |
| `POST /auth/register` | 5/hour/IP |
| `POST /attempts/start` | 30/min/user |
| `POST /attempts/{id}/q/{n}/answer` | 60/min/user |
| `POST /questions/{id}/reports` | 30/hour/user |
| `POST /admin/imports` | 5/hour/admin |
| `GET /search/exams` | 60/min/IP |
| `GET /` (public landing) | 60/min/IP |

### CSP (initial policy)
```
default-src 'self';
img-src 'self' data:;
style-src 'self' 'unsafe-inline';
script-src 'self' 'unsafe-inline';     /* relax HTMX/Alpine inline; harden later */
form-action 'self';
frame-ancestors 'none';
base-uri 'self';
```

### Bleach allow-list (for rendered Markdown content)
```python
ALLOWED_TAGS = ["p","strong","em","code","pre","ul","ol","li","a",
                "h2","h3","h4","blockquote","br","hr"]
ALLOWED_ATTRS = {"a": ["href","title","rel"], "code": ["class"]}
ALLOWED_PROTOCOLS = ["http","https","mailto"]
# `a` tags get rel="noopener noreferrer nofollow" injected.
```

## Related Code Files
**Create**
- `app/security/{headers,sanitize,upload_validator,rate_limits}.py`
- `app/middleware/{request_id,error_handler}.py`
- `tests/security/*.py`
- `docs/security-baseline.md` (project-local doc; not external)

**Modify**
- All admin form routes — apply rate-limit dependency.
- Render path everywhere — pipe markdown/explanation/question_text through `sanitize.render_markdown()`.
- `app/main.py` — install middleware in correct order: request_id → security_headers → CORS (none for MVP) → CSRF → routes.

## Implementation Steps

1. **Security headers middleware** — adds CSP, X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy strict-origin-when-cross-origin, Permissions-Policy minimal. HSTS gated on `ENV=prod`.
1b. **Trusted proxy** — install proxy header middleware so **`X-Forwarded-Proto`**, **`X-Forwarded-For`**, and **`Host`** are only honored from the trusted hop (Nginx → unix socket). Ensures `Secure` cookies, redirects, and rate-limit IP behave correctly behind TLS termination.
2. **Markdown render helper** — `render_markdown(text) -> str`: `markdown_it.MarkdownIt(...)` → `bleach.clean()` with allow-list → `bleach.linkify()` → return safe HTML. Used in templates via Jinja filter `{{ q.question_text|render_md }}`.
3. **Upload validator** — `validate_xlsx(file) -> None | raise`: ext check + first-bytes magic (zip header `PK\x03\x04`) + size cap. Wraps Phase 05 upload route.
4. **Rate-limit factory** — `RateLimit(scope: str, max: int, window_s: int)`. Dependency injected per route. Backed by Redis `INCR` + `EXPIRE`.
5. **Request-id middleware** — generate UUID v4 if not present in `X-Request-ID`; bind to structlog context; inject into audit-log writes; emit in response header.
6. **Error handler** — catches all unhandled exceptions, renders generic error page in prod (no stack traces), full debug in dev. Sentry capture pre-render.
7. **CSRF coverage test** — parametrized test iterates every admin POST route, asserts 403 without token.
8. **XSS regression test** — store payloads in question_text/options/explanation, render review page, assert no `<script>` in HTML output.
9. **Upload validator tests** — reject `.xlsx` with wrong magic, oversized files, executables renamed to `.xlsx`.
10. **CSP test** — assert response headers contain expected directives.
11. **Markdown sanitization tests** — `<script>`, `<iframe>`, `javascript:` URIs all stripped.

## Todo List
- [ ] Trusted proxy / forwarded headers (Nginx-only trust)
- [ ] SecurityHeadersMiddleware with CSP + X-Frame + X-CTO + Referrer + Permissions
- [ ] HSTS gated on ENV=prod
- [ ] Markdown render helper with bleach allow-list
- [ ] Render path uses sanitizer everywhere imported text appears
- [ ] Upload validator (ext + magic + size)
- [ ] Rate-limit dependency applied per route table
- [ ] Request ID middleware → logs → audit → Sentry
- [ ] Error handler renders safe page in prod
- [ ] CSRF parametrized test covers every admin POST
- [ ] XSS regression tests pass
- [ ] CSP test passes

## Success Criteria
- `curl -I https://exam.example.com/ | grep -i content-security-policy` returns the policy.
- Stored `<script>alert(1)</script>` in question_text renders as text (no execution); inspected DOM has no `<script>`.
- Hammering `/auth/login` hits 429 within 6 attempts/min.
- Uploading a 26 MB file returns 413; uploading `notes.txt` renamed to `notes.xlsx` returns 400.
- Admin form POST without CSRF token returns 403 in 100% of admin routes.

## Risk Assessment
- **CSP `unsafe-inline` is a known compromise** — required for HTMX/Alpine at MVP. **Mitigation path:** nonce/hash CSP in Phase 2 (see Key Insights). Residual XSS risk reduced by bleach + tests, not by CSP alone.
- **Bleach allow-list too restrictive** — admin can't add tables in explanations. Acceptable at MVP; expand if requested.
- **Magic-number check** — XLSX is a zip; some malicious zips may bypass. Phase 2 wires ClamAV hook.
- **No 2FA** — admin account compromise is the highest-impact attack. Mitigate with strong password policy + lockout.

## Security Considerations
- All defenses are **defense in depth** — sanitization at import + sanitization at render + CSP. None alone is sufficient.
- Cookie attrs (Phase 03) — re-verify in tests under prod-like settings.
- File path safety: never accept user-supplied path components. All upload paths derive from `import_id`.
- No raw HTML rendering anywhere except admin-edited content (which still goes through bleach).

## Next Steps
Phase 10 — Backup + observability + DR drill. Phase 11 — Deployment hardens at infra level (TLS, firewall, fail2ban).
