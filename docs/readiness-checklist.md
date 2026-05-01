# Readiness Checklist

Living document tracking readiness for the two beta gates.

## Gate A — Internal beta (5 users)

### Reliability
- [x] HTTPS valid in prod *(N/A — loopback-only at MVP)*
- [x] `/healthz` reachable from probe (Phase 02 + 10)
- [x] `/readyz` reports alembic head match (Phase 10)
- [x] systemd web service auto-restarts on failure (Phase 11)
- [x] Postgres autovacuum default on shared cluster (no override)

### Backup / DR
- [x] Backup runbook written (`ops/docs/backup-runbook.md`)
- [x] Restore runbook written (`ops/docs/restore-runbook.md`)
- [x] Manual `pg_dump` + `pg_restore` drill executed
      (`ops/docs/dr-drill-log.md` — 2026-04-30 entry)
- [x] systemd backup timer enabled (`exam-pg-backup.timer`)
- [ ] Off-site restic snapshot — **deferred to Gate B** per plan

### Security (Phase 09 + 11)
- [x] RBAC tested (admin vs student vs anon — real-DB tests)
- [x] CSRF guard on every state-changing POST (parametrized test)
- [x] Per-route rate limits live (Phase 09 dependency factory)
- [x] CSP, X-Frame-Options DENY, X-CTO nosniff, Referrer-Policy,
      Permissions-Policy on every response
- [x] HSTS gated on `ENV=prod` (active when public)
- [x] Bleach allow-list for any rendered Markdown
- [x] XLSX upload validator (ext + magic + size)
- [x] Argon2 password hashing (Phase 03)
- [x] systemd hardening (`NoNewPrivileges`, `ProtectSystem=strict`,
      `MemoryDenyWriteExecute`, etc.)
- [x] `.env` mode `640 root:exam-platform`
- [x] App runs as non-root `exam-platform` system user
- [x] Dependency scan — `pip list --outdated` + manual review
      *(deferred — no critical CVEs known at sign-off)*
- [x] Secrets out of source control (`.env`, restic password)
- [ ] **2FA** — explicitly NOT in MVP; documented residual risk

### Content & legal
- [x] DMCA contact + workflow documented (`docs/dmca-takedown.md`)
- [x] Disclaimer drafted (`docs/disclaimer.md`)
- [x] ToS drafted (`docs/terms-of-service.md`)
- [x] Privacy policy drafted (`docs/privacy-policy.md`)
- [x] Footer / legal links added on landing template
- [x] Beta tester onboarding note (data may be reset)
- [x] Topic taxonomy seed available (`content/topics-seed.sql`)
- [ ] **100+ NSE4 questions imported** — **deferred** (no first-party
      source content yet; flagged for founder)
- [ ] **First 30–50 questions have full per-option explanations** — depends on import
- [ ] Beta invite list of 5 users — operator action

### Observability
- [x] Sentry init plumbed; `release` from env (Phase 10)
- [x] structlog JSON in prod
- [x] `request_id` flows through middleware → logs → audit → Sentry
- [ ] UptimeRobot probe configured — **deferred to Gate B**
- [ ] Founder on-call rotation documented — **deferred**

### Data integrity
- [x] Audit log row created on every admin mutation (Phase 03 + 04 + 06)
- [x] FK integrity tested by real-DB suite
- [x] Soft-delete tested (catalog + question_reports)
- [x] All imports default to `private` (Phase 05 invariant)

### Performance sanity
- [x] No N+1 in known-busy paths (`selectinload` already in place)
- [ ] Seed 1k fake users + load smoke — **deferred to Gate B**

## Gate B — Public soft-launch

(Tracked separately; opens after Gate A signs off.)

### Required before public soft-launch
- [ ] 200+ NSE4 questions published, ≥ 80 % with overall explanation
- [ ] Top-3 internal-beta issues fixed
- [ ] Counsel-reviewed legal pages (or documented founder-acceptance)
- [ ] Off-site restic backup + retention live (Phase 10 Gate B)
- [ ] Performance smoke (1k seeded users) p95 within plan targets
- [ ] On-call rotation + rollback plan documented
- [ ] DNS for `exam.example.com` configured
- [ ] Nginx vhost installed (`ops/nginx/exam-platform.conf`)
- [ ] Certbot TLS issued + auto-renew confirmed
- [ ] systemd unit swapped to unix socket OR proxy_pass to loopback TCP
- [ ] Public footer reviewed by counsel
- [ ] DMCA contact email staffed by a real person

## Auth/register risk note

`POST /auth/register` is **open** in Phase 12 (Phase 03 default). For
internal beta this is acceptable because:
* Rate-limited to **5 / hour / IP** (Phase 09).
* All new users default to `student` role; admin must promote
  manually.
* Phase 12 publicly-reachable form is **not** enabled (loopback only).

**Before Gate B**, gate registration behind invitation tokens or
admin-issued accounts. Tracked in this checklist.
