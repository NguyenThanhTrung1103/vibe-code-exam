# Privacy Policy (Beta)

**Last updated:** 2026-04-30 — Internal-beta draft. Counsel review
required before Phase 12 Gate B.

## What we collect

| Category | Examples | Why |
|----------|----------|-----|
| Account data | email, username, hashed password (Argon2) | authentication |
| Attempt data | exam selected, answers given, score, timestamps | the product |
| Audit log | who did what, when, IP at login | security + abuse forensics |
| Request logs | URL, status, request id, IP | diagnostics + rate-limit enforcement |
| Sentry diagnostics | exception type, stack trace, request id (no body) | error monitoring (Sentry) |
| Cookies | signed session cookie, CSRF cookie | authentication + CSRF |

We deliberately do **NOT** collect:

* Real names beyond what you put in `username`.
* Tracking pixels or cross-site cookies.
* Marketing analytics (no Google Analytics, no Mixpanel, no Hotjar).
* Payment information (no payments at MVP).

## How we use it

* **Operate the Service** — answer authentication, render attempts,
  scoring, review.
* **Security** — rate limit abuse, investigate intrusions, comply with
  legal process.
* **Improvement** — aggregate usage patterns to fix slow pages and
  broken questions.

We do **not** sell your data. We do not share it with advertisers.

## Cookies

Two cookies, both first-party, both `Secure` in prod, both
`HttpOnly`:

* `exam_session` — signed session token; lifetime ≤ 7 days.
* `exam_csrf` — anti-CSRF token; lifetime 4 hours per page load.

## Third-party processors

| Processor | Data |
|-----------|------|
| Sentry (error monitoring) | exception type, stack trace, request id; **no PII**, **no request body**. Disabled if `SENTRY_DSN` is unset. |
| Off-site backup (restic to S3-compatible object storage) | encrypted at rest with restic AES-256. Operator holds the key. |

## Data retention

| Category | Retention |
|----------|-----------|
| Account + attempt data | until you delete your account or beta is reset |
| Audit log | 12 months rolling |
| Backups | 7 daily / 4 weekly / 6 monthly |
| Sentry events | 30 days (Sentry default) |

## Your rights

You may:

* Request a copy of your data (export coming Phase 2).
* Delete your account — email **support@exam.example.com**.
* Object to specific processing — same address.

## Cross-border transfer

Backups are stored at the operator's chosen object-storage region.
Specifics published before public soft-launch.

## Security

* Argon2 password hashing.
* CSRF protection on every state-changing route.
* Rate limits on auth, registration, attempts, reports, and uploads.
* Strict CSP, HSTS-in-prod, hardened security headers.
* Daily encrypted backups, drilled at least once before launch.

We don't promise impossibilities ("no breach can ever happen") but we
do commit to disclosing material incidents within 72 h.

## Changes

Announced on the public footer + by email if material.

## Contact

Privacy: **privacy@exam.example.com** (placeholder).
