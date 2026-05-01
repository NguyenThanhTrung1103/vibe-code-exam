---
phase: 03
title: Auth, RBAC, audit log foundation
status: completed
completed_at: 2026-04-29
effort: 3-4 days
priority: high
depends_on: [02]
---

# Phase 03 — Auth, RBAC, Audit Log Foundation

## Context Links
- PRD §10 (audit log), §21 (RBAC matrix, security baseline)
- Models from Phase 02: `users`, `audit_logs`

## Overview
Implement session-cookie auth (admin + student only — no instructor at MVP), an RBAC dependency injectable into routes, the `audit_log_writer` helper used by every mutation in later phases, password hashing with Argon2, CSRF on admin forms, login rate-limit, and a CLI command to bootstrap the first admin.

## Key Insights
- **Session cookies, not JWTs.** SPA isn't in MVP scope; cookies + CSRF is simpler and SEO-friendly.
- **Audit log writer must be impossible to forget.** Every admin-side DB mutation must call **`audit_log_writer.write()` in the same SQLAlchemy session transaction** as the data change. Service methods may be named **`create_*`, `update_*`, `delete_*`, etc.** — there is **no** requirement for a single generic function named `mutate()` for all entities. Optional: a small internal helper to diff `old_value`/`new_value` if it reduces duplication. Phases 04+ must not commit a mutation without an audit row when the action is auditable.
- **RBAC matrix from PRD §21.1** is the source of truth. Encode as constants, not strings sprinkled across routes.
- **Login rate limit** uses Redis (already provisioned in Phase 01). Sliding window per IP + per username.
- **No 2FA at MVP** — flagged as decision pending in PRD §35; defer.
- **Student registration** is open (no email verification at MVP); admin-only registration is invite-link based.

## Requirements
**Functional**
- Routes: `GET/POST /auth/register`, `GET/POST /auth/login`, `POST /auth/logout`, `GET /auth/me`.
- Admin creation via CLI: `python -m scripts.create_admin --email x@y --username admin`.
- Decorator `@require_role("admin")` returns 403 (not 401) if logged in but wrong role; 401 if not logged in.
- Every admin mutation writes to `audit_logs` in the same transaction as the change.
- Login rate limit: 5/min per IP, 20/hour per account; lockout returns 429 with `Retry-After`.

**Non-functional**
- Argon2id hashing via `passlib`.
- Session cookie: `Secure`, `HttpOnly`, `SameSite=Lax`, signed with `SECRET_KEY`.
- Session TTL: 7 days; admin role re-prompts at 24h since last password input (track `last_password_at` on user).
- All audit writes synchronous in the request transaction — no fire-and-forget.

## Architecture

```
app/
├── auth/
│   ├── __init__.py
│   ├── service.py            # register_user, authenticate, hash_password, verify_password
│   ├── session.py            # cookie signing/parsing
│   ├── rate_limit.py         # Redis sliding window
│   ├── csrf.py               # itsdangerous CSRF tokens
│   └── permissions.py        # RBAC matrix + decorators
├── audit/
│   ├── __init__.py
│   ├── writer.py             # write_audit_log()
│   └── events.py             # AuditAction enum (typed event catalog)
├── routers/
│   ├── auth.py
│   └── admin/audit.py        # admin viewer (read-only, paginated)
├── templates/auth/
│   ├── login.html
│   ├── register.html
│   └── _layout.html
└── deps.py                   # current_user, require_role
```

### Audit event catalog (initial — extends in later phases)
```python
class AuditAction(str, Enum):
    USER_REGISTERED = "user.registered"
    USER_ROLE_CHANGED = "user.role_changed"
    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    LOGOUT = "auth.logout"
    # extended by Phase 04+: provider.created, exam.published, etc.
```

### `audit_log_writer.write()` signature
```python
def write(
    session: Session,
    *,
    actor_type: ActorType,         # "user" | "ai" | "system"
    actor_id: int | None,
    action: AuditAction,
    entity_type: str,
    entity_id: int | None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    reason: str | None = None,
    request_id: str | None = None,
) -> None:
    # appends an audit_logs row; caller is responsible for committing.
```

## Related Code Files
**Create**
- `app/auth/service.py`, `session.py`, `rate_limit.py`, `csrf.py`, `permissions.py`
- `app/audit/writer.py`, `events.py`
- `app/routers/auth.py`
- `app/routers/admin/audit.py`
- `app/deps.py` (extend with `current_user`, `require_role`)
- `app/templates/auth/login.html`, `register.html`, `_layout.html`
- `scripts/create_admin.py`
- `tests/test_auth.py`, `test_audit.py`, `test_rbac.py`

## Implementation Steps

1. **Password service** — `hash_password(plain) -> str`, `verify_password(plain, hashed) -> bool` via `passlib.hash.argon2`.
2. **Session cookie service** — sign payload `{"user_id": ..., "exp": ...}` with `itsdangerous.URLSafeTimedSerializer`. Set/clear cookie helpers.
3. **CSRF service** — issue token at `GET` for any form route, validate on `POST`. Store token in session payload OR per-form HMAC; pick HMAC (stateless).
4. **Rate limit middleware** — Redis `INCR` with `EXPIRE` per `(scope, key)`. Wrap login endpoint.
5. **`current_user` dependency** — parse cookie, fetch user, return `None` on bad/expired.
6. **`require_role(role)` dependency** — composes `current_user`; raises 401 if anonymous, 403 if wrong role.
7. **Auth routes** — register (student only), login, logout, "me." HTMX-friendly responses.
8. **Audit writer** — same-transaction insert. JSONB `old_value`/`new_value` diffs.
9. **Audit viewer** — admin-only paginated table; filter by `entity_type`, `actor_id`, date range. Read-only.
10. **CLI: `scripts/create_admin.py`** — prompts for email/username/password (or env), creates admin user. Audit-log entry: `actor_type='system'`, `action='user.registered'`.
11. **Tests**:
    - registration creates user + audit log
    - login + logout flow
    - rate limit triggers 429 after threshold
    - `require_role("admin")` returns 401 anon, 403 student, 200 admin
    - audit writer captures old/new diff correctly
    - CSRF rejection on form POST without token

## Todo List
- [ ] Argon2id password hashing
- [ ] Signed session cookies (Secure/HttpOnly/SameSite=Lax)
- [ ] CSRF tokens on all admin forms
- [ ] Login rate limit (5/min IP, 20/hour account)
- [ ] `current_user` and `require_role` deps
- [ ] Audit writer in same-tx pattern
- [ ] Audit event enum extensible per phase
- [ ] Audit viewer for admin (paginated, read-only)
- [ ] CLI command to bootstrap first admin
- [ ] Login/register/logout templates
- [ ] Tests cover all auth + RBAC + audit cases

## Success Criteria
- Admin can be created via CLI in <30 seconds.
- Anonymous user is redirected to `/auth/login` from any admin route.
- Student visiting `/admin/*` gets 403.
- Every successful or failed login appears in `audit_logs`.
- Hammering `/auth/login` 6 times triggers 429 within a minute.

## Risk Assessment
- **Cookie tampering** if `SECRET_KEY` leaks. Mitigate: rotation runbook + 24h admin re-prompt.
- **Audit gap** — if a future dev calls `session.commit()` without calling `audit_log_writer.write()` for an admin mutation, the audit log misses the event. Mitigate: code review checklist + integration test that asserts every admin route writes ≥1 audit row where required.
- **Rate-limit DoS** — if attacker sends fake `X-Forwarded-For`, they evade per-IP. Mitigate: trust only the proxy's set header; document in deployment phase.

## Security Considerations
- No password hints, no security questions.
- Generic error message on login failure ("Invalid credentials") — don't reveal whether email exists.
- Force HTTPS in prod (header check); reject session cookie on plain HTTP except in dev.
- Argon2 params: tuned via `passlib` defaults; document upgrade path.
- Session fixation prevention: rotate session id on login.

## Next Steps
Phase 04 — Catalog CRUD now uses `require_role("admin")` and `audit_log_writer` for every mutation.
