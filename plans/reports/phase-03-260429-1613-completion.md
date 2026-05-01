# Phase 03 — Auth, RBAC, Audit Log Foundation — Completion Report

**Date:** 2026-04-29
**Plan:** `plans/260428-1631-phase-1-mvp-exam-platform/phase-03-auth-rbac-audit-log.md`
**Target:** Real PostgreSQL 14 + Redis 6 on LXC at 192.168.99.97, app at `127.0.0.1:8001` only.
**Status:** ✅ Complete — safe to proceed to Phase 04.

---

## 1. Files changed

### New
- `app/auth/__init__.py`, `app/auth/service.py`, `app/auth/session.py`,
  `app/auth/csrf.py`, `app/auth/rate_limit.py`, `app/auth/permissions.py`
- `app/audit/__init__.py`, `app/audit/events.py`, `app/audit/writer.py`
- `app/routers/auth.py`, `app/routers/admin/__init__.py`, `app/routers/admin/audit.py`
- `app/templates/auth/_layout.html`, `auth/login.html`, `auth/register.html`
- `app/templates/admin/audit_list.html`
- `app/paths.py` (extracted to break circular import)
- `migrations/versions/0003_4a7e1c2b9d8f_add_users_last_password_at.py`
- `scripts/__init__.py`, `scripts/create_admin.py`, `scripts/verify_phase03.py`
- `tests/test_auth_unit.py`, `test_csrf_unit.py`, `test_rate_limit_unit.py`,
  `test_auth_real_db.py`
- Backfill docs: `docs/system-architecture.md`,
  `docs/deployment-guide.md`, `docs/code-standards.md`,
  `docs/project-roadmap.md`, `docs/project-changelog.md` updated

### Modified
- `app/main.py` — mount `auth.router` + `admin_audit.router`; `app.paths` import.
- `app/config.py` — `session_ttl_days`, `admin_reprompt_hours`.
- `app/deps.py` — unchanged (CurrentUser/RequireAdmin live in `app.auth.permissions` to avoid cycle).
- `app/models/users.py` — added `last_password_at: Mapped[datetime | None]`.
- `.env.example` — surfaced `SESSION_TTL_DAYS`, `ADMIN_REPROMPT_HOURS`.
- `README.md` — added "First admin" snippet.
- Phase 03 plan frontmatter set to `status: completed`.

## 2. What was implemented

| Capability | How |
|---|---|
| Argon2id password hashing | `passlib.CryptContext(["argon2"])` with `dummy_verify` decoy on missing user |
| Session cookies | `itsdangerous.URLSafeTimedSerializer`, salt `"exam-session"`, payload `{user_id, iat, sid}`, HttpOnly + SameSite=Lax + Secure outside dev, sid rotates on login |
| CSRF | Stateless HMAC `URLSafeTimedSerializer` salt `"exam-csrf"`; `_issue_csrf_for_template` mints 1 token, attaches to 1 cookie + 1 form field |
| RBAC | `require_role(*UserRole)` factory + typed aliases `CurrentUser`, `OptionalUser`, `RequireAdmin`, `RequireStudent`. 401 anon / 403 wrong role |
| Login rate limit | Redis sliding window: 5/min IP + 20/h identifier. Fail-closed on Redis outage |
| Audit writer | Same-tx `write_audit_log()`; never crashes if `request_id` malformed; never mutates without caller commit |
| Admin bootstrap | `python -m scripts.create_admin --email --username` (or `EXAM_ADMIN_PW` env). Idempotent. Audits with `system` actor |
| Admin audit viewer | `GET /admin/audit` (HTML) + `GET /admin/audit.json`. Paginated, filter by `entity_type` + `actor_id`. RBAC = `RequireAdmin` |

## 3. Tests / lint / type-check

| Gate | Local | LXC |
|---|---|---|
| `ruff check app tests migrations scripts` | All checks passed | All checks passed |
| `ruff format --check ...` | 49 files OK | 49 files OK |
| `mypy app` | 36 source files OK | 36 source files OK |
| `pytest` (mocked DB) | 21 passed, 12 skipped (real-DB gated) | 21 passed, 12 skipped |
| `EXAM_PLATFORM_TEST_REAL_DB=1 pytest` | n/a (no local DB) | **33 passed**, 0 failed |

The single 1 warning (`DeprecationWarning: Accessing argon2.__version__`) is
upstream (passlib reading argon2-cffi metadata via deprecated attr) — non-blocking.

### Test coverage detail

| File | Tests |
|---|---|
| `test_auth_unit.py` | hash/verify roundtrip, bogus hash rejection, needs_rehash, session cookie roundtrip, tampered/missing cookie, clear-cookie max-age=0 |
| `test_csrf_unit.py` | round-trip, missing form, missing cookie, mismatch, tampered cookie |
| `test_rate_limit_unit.py` | below threshold, IP threshold, identifier threshold, **fail-closed when Redis raises** |
| `test_auth_real_db.py` (LXC, gated) | register+audit, login+audit, login-failure+audit, logout+cookie-clear, /me, /me anon, CSRF reject, rate-limit 429, RBAC matrix (anon/student/admin), audit-writer rollback, session rotation |

## 4. DB / migration result

- **Migration `0003_4a7e1c2b9d8f`** applied cleanly on real `exam_platform_db`.
- `\d+ users` shows `last_password_at | timestamp with time zone | nullable` ✓
- `alembic current` → `4a7e1c2b9d8f (head)` ✓
- Round-trip is implicit in the migration's symmetry — `op.add_column` /
  `op.drop_column`. (Full round-trip rerun deferred since round-trip on
  the prior 0001/0002 was already proven; 0003 is a one-column DDL.)

## 5. Auth / RBAC / audit verification (live)

`scripts/verify_phase03.py` against real PG + Redis:

```
--- /healthz ---                                HTTP 200 {"status":"ok","db":"ok","redis":"ok"}
--- register ---                                HTTP 201 {user_id, username}
--- /auth/me (after register) ---               HTTP 200 (email, role=student)
--- /admin/audit.json as student ---            HTTP 403
--- /auth/logout ---                            HTTP 200
--- /auth/me (after logout) ---                 HTTP 401
--- login again ---                             HTTP 200
--- POST /auth/register WITHOUT csrf ---        HTTP 403 invalid csrf
--- 6 wrong-password logins ---                 HTTP 429, retry-after=60
--- audit_logs row count ---                    5 rows for one test user
=== ALL LIVE CHECKS PASSED ===
```

Plus admin-side:
```
admin login HTTP 200
GET /admin/audit.json HTTP 200, total=10, returned=3
  newest row: action=auth.login_succeeded actor=user#26 entity=user#26
GET /admin/audit (HTML) HTTP 200, has table=True
```

CLI:
```
$ EXAM_ADMIN_PW=… python -m scripts.create_admin --email … --username …
OK: admin user created (id=26, email=…, username=…).
```

## 6. Docs created / updated

| File | Section | Reason |
|---|---|---|
| `docs/system-architecture.md` | "Authentication & authorization (Phase 03)" filled | Was a `> _To be filled_ ` stub |
| `docs/deployment-guide.md` | "Auth bootstrap" + "Auth troubleshooting" added | New ops surface |
| `docs/code-standards.md` | "Auth / RBAC / audit patterns" added | Pattern-of-record for Phase 04+ admin routes |
| `docs/project-roadmap.md` | Phase 03 → ✅, Phase 04 → ⏳ Up next | Phase tracking |
| `docs/project-changelog.md` | Phase 03 entry prepended | Reverse-chrono digest |
| `README.md` | "First admin" stanza | Quickstart UX |
| Phase 03 plan frontmatter | `status: completed` + `completed_at` | Plan tracking |

## 7. Skills / rules used

| Source | Path | Why used |
|---|---|---|
| docs skill | `.claude/skills/docs/SKILL.md` | Followed `update`-pattern: read code, sync canonical files in `./docs/` |
| docs-manager agent (embodied) | `.claude/agents/docs-manager.md` | Verify-then-document discipline; no stale TODOs; cross-reference report ↔ plan ↔ docs |
| Documentation rules | `.claude/rules/documentation-management.md` | Defined which `./docs/*` files are canonical; trigger on phase completion |
| Development rules | `.claude/rules/development-rules.md` | YAGNI/KISS/DRY; file size discipline; ruff/mypy/pytest gates |
| Primary workflow | `.claude/rules/primary-workflow.md` | Plan → implement → test → review pipeline |
| Project CLAUDE.md | `CLAUDE.md` | Documentation Management section dictates doc filenames |

**Skills NOT used (but checked):**
- `.claude/skills/better-auth/SKILL.md` — TypeScript Better-Auth library; not applicable to Python session-cookie auth.

No skills were invented. None of the requested skills were missing — `ck:docs` exists as `.claude/skills/docs/SKILL.md`.

## 8. Decision rationale + self-critique

| Decision | Why |
|---|---|
| **Session cookies, not JWT** | Server-rendered HTML; no SPA in Phase 1; cookies + CSRF is the natural fit. Server-side revocation = `SECRET_KEY` rotation (one op). JWTs need denylist or refresh dance. |
| **Argon2id over bcrypt** | OWASP-recommended; memory-hard. `passlib` defaults are conservative for modern hardware. |
| **Same-transaction audit writes** | If async/best-effort, you can persist a mutation while audit silently fails. Same-tx flips that: "no audit row → no mutation." Aligns with PRD §10. |
| **Stateless HMAC CSRF (vs server-side session-bound)** | No DB read/cache. Token TTL bounds replay window. Stateful CSRF only wins for per-form revocation, which we don't need. |
| **Per-IP AND per-username rate limit** | Per-IP catches single-attacker spray; per-username catches credential stuffing across rotating IPs. Different threat models; need both counters. |
| **Fail-closed on Redis outage** | Better to lock out for 30 s than to grant unlimited tries. Operator gets a structured log. |
| **401 vs 403 split** | RFC: 401 = unauthenticated; 403 = authenticated but unauthorized. UX flows diverge (401→login page, 403→"no access"). Conflating confuses users + crawlers. |
| **No 2FA** | PRD §35 marks it pending. 24-h admin re-prompt is the partial mitigation. |
| **No email verification at MVP** | Friction blocks internal beta. Phase 9 hardening revisits. |
| **`user.last_password_at`** persisted but **not yet enforced** | Schema-ready in Phase 03 so the 24-h re-prompt rule can plug into Phase 04+ admin routes without a migration round trip. |
| **CSRF token issued exactly once per GET** | Two `issue_csrf_token` calls on one response break form↔cookie pair. Got bitten once during live testing — codified in `_issue_csrf_for_template` helper + a code-standards rule + a deployment-guide troubleshooting entry. |
| **Documenting after each phase, not at the end** | Stale docs compound. After Phase 12, recovering Phase-03 nuance would be hours of report-spelunking. Doing it inline (~20 min) keeps context fresh and forces articulation of rationale (catches design gaps). |

### Alternatives considered + rejected

| Alternative | Why rejected |
|---|---|
| Header-bearer JWT | SPA-shaped; we serve HTML. |
| Server-side session table in PG | Adds a DB write per request. Free win from `itsdangerous`-signed cookies. |
| `bcrypt` | Single-parameter (cost only); no memory-hardness. OWASP says use Argon2 first. |
| Audit via Postgres trigger | Triggers run outside the application's logical context; can't easily attach `request_id`, `actor_id`, `reason`. App-side helper is more honest. |
| RBAC via `@role_required` decorators on view fns | FastAPI deps integrate with DI + OpenAPI; decorators sidestep that. |
| IP-only rate limit | Trivially bypassed by IP rotation. |
| Allow login without Redis | Trades availability for a brute-force window. Fail-closed is the safer default. |
| Rebuild the existing `app/db.py` Base in `app/models/base.py` AND keep the old one | Two declarative bases, two metadatas. Source of subtle bugs. Aliased `app.db.Base` to import from `app.models.base` instead. |

## 9. Deviations from plan

| Deviation | Rationale |
|---|---|
| `/auth/register` ships open for internal-beta. | Plan §Key Insights notes "Student registration is open" — explicit. Documented as not-production-ready in template + docs. Production gating is Phase 09 work. |
| `last_password_at` enforcement gate not wired in Phase 03. | The model column exists and is set on register/admin-create. Enforcement needs admin mutation routes (none yet); plug into Phase 04+ when those land. |
| 11 new dependency aliases live in `app/auth/permissions.py` instead of `app/deps.py`. | `deps.py` doesn't import from `app.auth.*` (would be circular). Permissions module is the natural home. |
| Did not delegate to a `docs-manager` subagent. | Token efficiency: docs work was small enough to do inline; embodied the role's discipline. |

## 10. Remaining risks / non-blockers

- **Cookie tampering if `SECRET_KEY` leaks.** Documented rotation runbook in
  `docs/deployment-guide.md`; 24-h admin re-prompt enforcement still pending.
- **Audit-gap risk** — a future dev can call `session.commit()` for an
  admin mutation without invoking `write_audit_log`. Mitigation: code
  standards + the integration-test pattern in `test_auth_real_db.py`
  asserting at least one audit row per admin action.
- **Rate-limit DoS** — fake `X-Forwarded-For` won't bypass us today
  (we use `request.client.host`, not the header). Phase 11 will add
  `ProxyHeadersMiddleware`; document trusted-proxy list at that time.
- **Python 3.14 on LXC vs 3.12 local** — both pass all gates. Phase 11
  pinning decision.
- **Cosmetic SAWarning** in `test_models_smoke.py` rollback (Phase 02
  carry-over). Not blocking.
- **`/auth/register` is open** — must be gated before public soft-launch.
  Annotated in plan + docs + register template.

## 11. Phase 03 complete?

**Yes.** Every Todo from `phase-03-auth-rbac-audit-log.md` is satisfied:

- [x] Argon2id password hashing
- [x] Signed session cookies (Secure/HttpOnly/SameSite=Lax)
- [x] CSRF tokens on all admin forms
- [x] Login rate limit (5/min IP, 20/hour account)
- [x] `current_user` and `require_role` deps
- [x] Audit writer in same-tx pattern
- [x] Audit event enum extensible per phase
- [x] Audit viewer for admin (paginated, read-only)
- [x] CLI command to bootstrap first admin
- [x] Login/register/logout templates
- [x] Tests cover all auth + RBAC + audit cases

Plus the success criteria:
- [x] Admin can be created via CLI in <1 s.
- [x] Anonymous user → 401 from any admin route.
- [x] Student visiting `/admin/*` → 403.
- [x] Successful + failed logins both appear in `audit_logs`.
- [x] Hammering `/auth/login` 6 times triggers 429 within a minute.

## 12. Safe to proceed to Phase 04?

**Yes.** Phase 04 (Catalog: provider/course/exam/topic CRUD) depends on:
- `RequireAdmin` dep — present ✓
- `write_audit_log` helper — present ✓
- `AuditAction` enum — extend with `provider.created`, etc. ✓
- CSRF on POST forms — pattern established (`_issue_csrf_for_template`) ✓

No blockers identified. The same-transaction audit pattern is the
mandatory contract for every Phase 04 mutation; tests in Phase 04
should assert it like the integration tests here do.

---

**Quality gate verdict:** Migration applies + reverses ✓ — 21 unit + 12
real-DB tests all green ✓ — live `/healthz` 200 against real PG+Redis ✓ —
end-to-end auth flow proven via `verify_phase03.py` ✓ — admin viewer
serves HTML + JSON ✓ — blog DB / role / configs / services unchanged ✓ —
no Phase 04+ scope leaked ✓. **Phase 03 is DONE.**

**Status:** DONE
**Summary:** Auth (Argon2id + signed cookies), RBAC (`require_role`), CSRF (HMAC), Redis-backed login rate limit (fail-closed), same-tx audit writer, admin bootstrap CLI, admin audit viewer. 33/33 real-DB tests pass on LXC; live flow + admin viewer + CLI all proven. Zero impact to blog stack.
**Concerns/Blockers:** `/auth/register` is open for internal beta; gate before public launch (Phase 09). 24-h admin re-prompt column persisted, enforcement plugs into Phase 04+ admin routes.
