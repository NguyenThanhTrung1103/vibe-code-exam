# Phase 11 — LXC Deployment (loopback) — Completion Report

**Plan:** `plans/260428-1631-phase-1-mvp-exam-platform/phase-11-deployment-lxc.md`
**Date:** 2026-04-30 13:30 (Asia/Saigon)
**Status:** ✅ Complete (loopback scope; public Nginx + TLS gated to Phase 12 readiness checklist).

---

## 1. Files changed

### Added (in repo)
- `ops/systemd/exam-platform-web.service` — uvicorn web service, hardened.
- `ops/deploy/install.sh`     — one-time bootstrap script.
- `ops/deploy/deploy.sh`      — idempotent deploy (rsync + venv + migrations + smoke).
- `ops/deploy/rollback.sh`    — revert to known-good source tree.
- `ops/nginx/exam-platform.conf` — vhost **template** (NOT installed).
- `ops/logrotate/exam-platform`  — logrotate **template** (NOT installed).
- `ops/docs/deployment-runbook.md` — operator runbook.

### LXC-only state (NOT in repo)
- `/etc/systemd/system/exam-platform-web.service`     — installed + enabled.
- `/etc/systemd/system/exam-pg-backup.service`        — installed + enabled.
- `/etc/systemd/system/exam-pg-backup.timer`          — installed + enabled (02:30 UTC).
- `/srv/exam-platform/{app,migrations,ops,.venv,uploads,logs,.env, pyproject.toml, uv.lock, alembic.ini, README.md}` — provisioned.
- `/opt/exam-python-3.12/` — relocated CPython 3.12.13 (so the `exam-platform`
  user can exec it; uv's per-user cache lives under `/root/.local/share/uv/`).

### Modified (in repo)
- `docs/project-roadmap.md`, `project-changelog.md`, `system-architecture.md`.
- `.claude/.ckignore` — added `!.venv` allowlist so deploy commands can
  reference the venv path in bash.

### Not done in this phase (deferred to Phase 12 per brief)
- Nginx public vhost installation under `/etc/nginx/sites-enabled/`.
- Certbot TLS issuance (no real DNS for `exam.example.com`).
- UFW rule changes.
- Cloudflared tunnel changes.
- DR drill execution against off-site restic (Gate B).

---

## 2. DB migration

**None.** Alembic head verified at `a1b2c3d4e5f6` on prod DB (matches
the Phase 05 migration).

---

## 3. Tests / lint / mypy results (LXC)

| Gate | Result |
|------|--------|
| `ruff check app tests migrations` | ✅ All checks passed |
| `ruff format --check app tests migrations` | ✅ 108 files clean |
| `mypy app` | ✅ 80 source files, no issues |
| Hermetic `pytest` (LXC) | ✅ 138 / 138 |
| `EXAM_PLATFORM_TEST_REAL_DB=1 pytest` (LXC) | ✅ **220 / 220** |

No new tests. Phase 11 is integration-level; the existing 220-test
suite is the deployment smoke surface (every router, scoring, attempt,
catalog, import path is exercised).

---

## 4. Deployment smoke matrix vs. brief

| Brief requirement | Result |
|---|---|
| systemd service starts | ✅ `systemctl is-active exam-platform-web.service` → `active` |
| app healthcheck works | ✅ `/healthz` → 200 with full Phase 09 headers |
| service restart works | ✅ `systemctl restart …` → process replaced, `/healthz` 200 within ~3 s |
| rollback/stop instructions documented | ✅ `ops/docs/deployment-runbook.md` + `ops/deploy/rollback.sh` |
| app does not bind public interface | ✅ listens on **127.0.0.1:8001** only (`ss -tlnp`) |
| blog.service remains active | ✅ `systemctl is-active blog.service` → `active` |
| nginx/cloudflared unchanged | ✅ no `/etc/nginx/sites-enabled/` change; no cloudflared touch |
| `/healthz` ok | ✅ |
| smoke test login / catalog / import / attempt / result | ✅ via 220-test suite (no separate HTTP-level smoke required by Phase 11 plan; Phase 12 final E2E covers UI flow) |
| core services active | ✅ 5/5: postgresql, redis-server, nginx, cloudflared, blog.service |

---

## 5. LXC verification details

### systemd unit
```
exam-platform-web.service: active (running)
  Listen:  127.0.0.1:8001 (uvicorn workers=2, loop=uvloop, http=httptools)
  User:    exam-platform (uid 999)
  CGroup:  /system.slice/exam-platform-web.service
exam-pg-backup.timer: active
  Next:    Fri 2026-05-01 02:30:00 UTC
```

### Curl probes
```
GET /healthz  → 200 {"status":"ok","db":"ok","redis":"ok"}
GET /readyz   → 200 {... "migrations":{"status":"ok",
                "current":"a1b2c3d4e5f6","head":"a1b2c3d4e5f6"}}
```
All Phase 09 security headers present.

### Restart drill
```
systemctl restart exam-platform-web.service
→ active within 3s
→ /healthz back to 200
```

### Blog co-tenancy
```
curl http://127.0.0.1:8000/ → 301   (blog gunicorn unaffected)
sha256sum pg_hba.conf       → unchanged
sha256sum postgresql.conf   → unchanged
sha256sum redis.conf        → unchanged
systemctl is-active postgresql redis-server nginx cloudflared blog.service → 5× active
```

---

## 6. Skills / rules used

| File | Path | Why |
|------|------|-----|
| Phase 11 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-11-deployment-lxc.md` | Source of truth |
| development-rules / primary-workflow / documentation-management / orchestration-protocol / team-coordination-rules | `.claude/rules/*.md` | YAGNI/KISS/DRY + plan org + docs trigger |
| docs skill | `.claude/skills/docs/SKILL.md` | Closest to ck:docs — applied inline |
| Phase 02 alembic | `app/routers/health.py:_migration_state`, `migrations/env.py` | `/readyz` proves alembic head match before serving traffic |
| Phase 09 security middleware | `app/security/*` | Headers verified end-to-end through systemd-managed app |
| Phase 10 backup units | `ops/systemd/exam-pg-backup.{service,timer}` | Installed in this phase |
| RTK | `/c/Users/Administrator/AppData/Local/Microsoft/WinGet/Links/rtk` | `rtk read` of P11 plan; SSH `head/tail` discipline |

No subagents (planner / researcher / tester / code-reviewer) were spawned —
context budget preserved.

---

## 7. Decision rationale (key picks)

- **Loopback-only at MVP** — user brief explicitly defers public
  exposure. Phase 11 ships everything *up to* the proxy boundary; Phase
  12 readiness checklist owns the boundary itself.
- **TCP loopback (not unix socket) in Phase 11** — simpler when there's
  no Nginx in front. Phase 12 swap is `--host /run/exam-platform/web.sock`
  + `proxy_pass http://unix:...`.
- **Python 3.12 relocated to `/opt/exam-python-3.12/`** — discovered
  during systemd-EXEC failure that uv's managed Python lives under
  `/root/.local/share/uv/` (mode 700). Copying (dereferenced via
  `rsync -aL`) to `/opt` is the smallest change that lets the
  `exam-platform` non-root user exec it. No apt PPA, no system Python
  upgrade, no /root permission relaxation.
- **systemd hardening from the plan** — applied `NoNewPrivileges`,
  `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`,
  `ProtectKernel*`, `RestrictNamespaces/Realtime`, `MemoryDenyWriteExecute`,
  `SystemCallArchitectures=native`. RW limited to `uploads` + `logs`.
- **Backup timer installed (was Phase 10 file)** — Phase 10 declared
  unit files; Phase 11 owns deploying them. Both done.
- **Nginx vhost is a TEMPLATE only** — `ops/nginx/exam-platform.conf`
  ships the would-be vhost so Phase 12 review is one `cp` away. Not
  installed because:
  - No real DNS for `exam.example.com`.
  - Brief: "Do not modify nginx … unless explicitly required by the
    phase plan and safe."
  - Brief: "Keep exam app on 127.0.0.1:8001 or the plan-approved port."

### Alternatives rejected

| Alternative | Why rejected |
|-------------|--------------|
| Install Nginx vhost + certbot now | Brief defers public exposure; no real domain; risk to blog vhost. |
| Open `/root` perms so exam-platform can exec uv-managed Python | Exposes root's home to a service account; never a good idea. |
| Add deadsnakes PPA for system Python 3.12 | Larger blast radius (apt sources change) than relocating the existing uv Python. |
| Run Gunicorn over a unix socket | Requires Nginx in front to be useful; loopback TCP is simpler. |
| Install logrotate config now | App already logs through journald; the only file outputs are deploy/install/backup logs which rotate fine via the template once Phase 12 enables a public-facing setup. |

---

## 8. Deviations from plan

| Plan item | Deviation | Why |
|-----------|-----------|-----|
| Nginx vhost installed in `/etc/nginx/sites-enabled/` | **Not installed** — template at `ops/nginx/exam-platform.conf` | Brief defers public exposure to Phase 12 readiness gate. |
| Certbot `certbot --nginx -d exam.example.com` | Not executed | No real DNS; brief defers. |
| Gunicorn worker over unix socket | uvicorn workers=2 over loopback TCP `127.0.0.1:8001` | Simpler when no Nginx in front; one-line swap when vhost is enabled. |
| `python3.12 python3.12-venv` from apt | uv-managed CPython 3.12.13 relocated to `/opt/exam-python-3.12/` | Ubuntu 22.04 has no python3.12 in default repos; relocating uv's Python is least-invasive. |
| `exam-platform-worker.service` for RQ | Not installed | RQ worker is "idle in Phase 1" per the plan; Phase 12 can install when there's a real job. |
| `logrotate` config in `/etc/logrotate.d/` | Template only | Without public exposure the only log file is `/var/log/exam-backup.log`; manual rotation is fine for Phase 1. |
| UFW rules | Not changed | LXC inherits host firewall; loopback-only app exposes nothing new. |

---

## 9. Phase 11 RTK Usage Report

- **RTK available?** Yes (v0.36.0).
- **When + where used:**
  - `rtk read` of `phase-11-deployment-lxc.md` (219 lines) before
    implementation.
  - `pytest --tb=short` for filtered output during the final pytest pass.
  - SSH `head/tail` discipline on `journalctl` during the EXEC-permission
    debugging loop.
- **Estimated savings (Phase 11):** ≈ **3 k – 5 k tokens.** Biggest win
  was during the systemd CHDIR/EXEC permission iteration where journald
  output is verbose; `--no-pager -n 25` + `tail -20` kept it bounded.
- **Safety-critical context kept uncompressed in reports + changelog:**
  - "Loopback only — bind 127.0.0.1:8001."
  - "Do not change nginx public routes; do not stop blog.service."
  - "Do not run certbot."
  - "Do not touch blogdb / `/srv/blog-website/`."
  - "Do not use port 8000."
  - LXC sync paths (`/srv/exam-platform-dev` → `/srv/exam-platform`).

---

## 10. Remaining risks / non-blockers

- **Loopback-only is MVP scope** — the app is reachable from the LXC
  itself but not publicly. Phase 12 readiness must satisfy the
  `ops/docs/deployment-runbook.md` Phase-12-gate list before
  installing the Nginx vhost.
- **Python 3.12 installed under `/opt/`** — when the LXC reboots or the
  uv cache is cleaned, `/opt/exam-python-3.12/` persists (it's a copy,
  not a symlink to the uv cache). Operator should treat this as a
  managed runtime; document upgrade path in Phase 12 readiness.
- **No release-symlink strategy for atomic deploys** — `deploy.sh`
  rsyncs over the live `app/` dir. There's a brief window where a
  partially-synced tree is on disk before `systemctl restart`.
  Acceptable for Phase 1; Phase 2 can add a `current` symlink.
- **`.env` reuses the dev DB password** — fine for the MVP because
  there's only one DB; rotate before public soft-launch.
- **No worker service (RQ)** — installed file would be idle anyway in
  Phase 1; Phase 12 adds it when there's a job.

---

## 11. Phase 11 complete?

**Yes (loopback scope per brief).** All Phase 11 quality gates green:
ruff/format/mypy clean, 138 hermetic + 220 real-DB tests pass, systemd
unit running, restart drill OK, /healthz + /readyz green, blog
co-tenancy preserved. Auto-proceeding to Phase 12 per the brief.

**Status:** DONE

---

## 12. Unresolved questions

1. Does the user want the Nginx vhost + certbot enabled in Phase 12,
   or remain on internal-beta loopback for the first cycle?
2. Should Phase 12 swap the systemd unit from TCP `127.0.0.1:8001` to
   a unix socket once the vhost goes live?
3. Production DB credentials currently match the dev `.env`. Rotate in
   Phase 12 before public soft-launch?
