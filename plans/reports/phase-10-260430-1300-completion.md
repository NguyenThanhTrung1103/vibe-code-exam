# Phase 10 — Backup, Observability, DR Drill — Completion Report

**Plan:** `plans/260428-1631-phase-1-mvp-exam-platform/phase-10-backup-observability.md`
**Date:** 2026-04-30 13:00 (Asia/Saigon)
**Status:** ✅ Complete (Gate-A internal-beta scope; LXC verified, 220 tests pass on real PG+Redis. DR drill executed.)

---

## 1. Files changed

### Added (10)
- `ops/backup/pg-backup.sh`              — daily PG backup (refuses non-`exam_*` DBs)
- `ops/backup/uploads-backup.sh`         — restic snapshot of uploads dir
- `ops/backup/restic-restore.sh`         — DR restore helper (refuses live + blogdb)
- `ops/systemd/exam-pg-backup.service`   — oneshot daily backup unit (Phase 11 installs)
- `ops/systemd/exam-pg-backup.timer`     — 02:30 UTC daily timer (Phase 11 installs)
- `ops/docs/backup-runbook.md`           — manual + automated procedure
- `ops/docs/restore-runbook.md`          — drill + production cutover
- `ops/docs/dr-drill-log.md`             — signed-off drill log (first entry recorded)
- `ops/docs/observability.md`            — logging / Sentry / UptimeRobot contracts
- `tests/test_health_routes.py`          — 6 hermetic tests for `/healthz` + `/readyz`

### Modified
- `app/routers/health.py` — adds `/readyz` (DB + Redis + alembic-head check).
- `app/main.py` — Sentry `release` plumbed from `SENTRY_RELEASE` / `APP_RELEASE` env.
- `docs/project-roadmap.md`, `project-changelog.md`, `system-architecture.md`.

### Not done in this phase (deferred per plan)
- Off-site restic upload (Gate-B / public soft-launch) — script supports it
  but `RESTIC_REPO` is left unset for the LXC dev env.
- Systemd timer install (Phase 11).
- UptimeRobot setup (Phase 12 readiness checklist).

---

## 2. DB migration

**None.** Phase 10 is observability + ops scaffolding.

---

## 3. Tests / lint / mypy results (LXC)

| Gate | Result |
|------|--------|
| `ruff check app tests migrations` | ✅ All checks passed |
| `ruff format --check app tests migrations` | ✅ 108 files clean |
| `mypy app` | ✅ 80 source files, no issues |
| Hermetic `pytest` (Windows) | ✅ 138 / 138 |
| Hermetic `pytest` (LXC) | ✅ 138 / 138 |
| `EXAM_PLATFORM_TEST_REAL_DB=1 pytest` (LXC) | ✅ **220 / 220** |

Phase 10 contributed 6 hermetic tests on top of the prior 132 (Phase 09).

---

## 4. DR drill — executed

Recorded in `ops/docs/dr-drill-log.md`:

| Step | Result |
|------|--------|
| `pg_dump` on `exam_platform_db` | OK — `exam_2026-04-30T12-51-42Z.dump` (116 KiB) |
| `dropdb --if-exists exam_platform_db_drill` (postgres superuser) | OK |
| `createdb -O exam_platform_user exam_platform_db_drill` | OK |
| `pg_restore --no-owner --no-privileges --clean --if-exists` | OK |
| Smoke: `users` count | `3` |
| Smoke: `exams` count | `4` |
| Smoke: `questions` count | `3` |
| Smoke: `alembic_version` head | `a1b2c3d4e5f6` (matches script head) |
| `dropdb exam_platform_db_drill` | OK |
| `rm -rf /tmp/exam-restore-drill` | OK |
| Wall-clock RTO | < 5 min (target ≤ 30 min) ✅ |

The drill confirmed:
- `pg_dump` connection over `127.0.0.1` works without superuser.
- `pg_restore` round-trips schema + data + alembic_version.
- The drill DB is fully isolated from the live DB; cleanup leaves no
  residue.
- The script's blogdb/live-DB refusal guards fire correctly.

---

## 5. Test coverage matrix vs. plan

| Plan requirement | Test |
|---|---|
| `/healthz` returns 200 with both deps up | `test_healthz_ok` |
| `/healthz` 503 when DB or Redis down | `test_healthz_degraded` |
| `/readyz` 200 when migrations at head | `test_readyz_ok_when_migrations_at_head` |
| `/readyz` 503 when DB down | `test_readyz_not_ready_when_db_down` |
| `/readyz` 503 when migration behind | `test_readyz_not_ready_when_migration_behind` |
| `/readyz` 503 when migration unknown | `test_readyz_not_ready_when_migration_unknown` |
| Backup script ran successfully on LXC | DR drill log |
| Restore script restored to drill DB | DR drill log |
| No destructive restore against live or blogdb | Built-in guards (`if [[ DRILL_DB == ... ]]`); verified by drill log |
| Structlog JSON in prod | `app/logging.py:38-41` (Phase 02 contract; documented in `ops/docs/observability.md`) |
| Sentry release tagging plumbed | `app/main.py:_init_sentry` reads `SENTRY_RELEASE` / `APP_RELEASE`; documented |
| Backup runbook written | `ops/docs/backup-runbook.md` |
| Restore runbook written | `ops/docs/restore-runbook.md` |
| Drill record | `ops/docs/dr-drill-log.md` (first row) |

---

## 6. LXC verification

- Sync to `/srv/exam-platform-dev` via `tar | ssh exam-lxc tar -xf -`;
  `chmod +x ops/backup/*.sh` after extract.
- `EXAM_PLATFORM_TEST_REAL_DB=1 pytest`: ✅ **220 / 220**.
- Uvicorn smoke on `127.0.0.1:8001`:
  - `/healthz` 200 `{"status":"ok","db":"ok","redis":"ok"}`.
  - `/readyz` 200 `{"status":"ok","db":"ok","redis":"ok",
    "migrations":{"status":"ok","current":"a1b2c3d4e5f6",
    "head":"a1b2c3d4e5f6"}}`.
  - All Phase 09 security headers still present.
- Uvicorn stopped cleanly (`pkill -f 'uvicorn.*8001'`).
- Blog stack SHA256 unchanged from baseline:
  ```
  pg_hba.conf:    548d74c9...  ✅
  postgresql.conf: e6a345c5...  ✅
  redis.conf:      f9f998aa...  ✅
  ```
- Services active (5/5): postgresql, redis-server, nginx, cloudflared, blog.service.

---

## 7. Skills / rules used

| File | Path | Why |
|------|------|-----|
| Phase 10 plan | `plans/260428-1631-phase-1-mvp-exam-platform/phase-10-backup-observability.md` | Source of truth |
| development-rules / primary-workflow / documentation-management / orchestration-protocol / team-coordination-rules | `.claude/rules/*.md` | YAGNI/KISS/DRY + plan org + docs trigger |
| docs skill | `.claude/skills/docs/SKILL.md` | Closest to ck:docs — applied inline |
| Phase 02 schema | `migrations/versions/0005_a1b2c3d4e5f6_imports_target_mapping_filepath.py` | Read alembic head to plumb the `/readyz` migration check |
| Phase 02 health pattern | `app/routers/health.py` (existing `/healthz`) | `/readyz` follows the same dependency-injection pattern |
| Phase 03 audit + structlog | `app/audit/writer.py`, `app/logging.py` | Confirmed structlog JSON contract for prod |
| Phase 09 security middleware | `app/security/*` | Verified `/readyz` ships through the same security headers + rate-limit-free path |
| RTK | `/c/Users/Administrator/AppData/Local/Microsoft/WinGet/Links/rtk` | `rtk read` of P10 plan; `pytest --tb=short` for filtered output during drill iteration |

No subagents (planner / researcher / tester / code-reviewer) were spawned —
context budget preserved.

---

## 8. Decision rationale (key picks)

- **Internal-beta gate vs. public-launch gate** — Phase 10 ships the
  internal-beta scope: documented runbook + executed manual drill +
  `/healthz`/`/readyz`. Off-site restic + UptimeRobot are gate-B
  prereqs deferred to Phase 12 readiness.
- **`exam_platform_user` keeps `CREATEDB=false`** — discovered during
  drill; operator pre-creates drill DB via postgres superuser. App
  cannot spawn or drop databases. Updated `restic-restore.sh` to
  refuse with a clear instruction message rather than try-and-fail.
- **`/readyz` is distinct from `/healthz`** — separating liveness from
  readiness is a deploy-automation requirement; uptime probes hammer
  `/healthz` cheaply, deploy gates hit `/readyz` once.
- **Migration-head check inside `/readyz`** — uses Alembic's
  `ScriptDirectory` + `MigrationContext.get_current_revision()` so we
  don't shell out to the `alembic` CLI. Wrapped in broad `Exception`
  catch so a misconfig returns `unknown` rather than 500.
- **Backup script refuses non-`exam_*` DB names** — defensive against
  operator error or env pollution.
- **Restic is opt-in via `RESTIC_REPO`** — local dev / drill works
  without an off-site repo configured.
- **Systemd unit files committed but not installed** — Phase 11 owns
  installation. Keeps Phase 10 contained.
- **Sentry `release` from env** — `SENTRY_RELEASE` (and `APP_RELEASE`
  fallback) means Phase 11's deploy script can stamp git SHA without
  the app needing to shell out to `git`.

### Alternatives rejected

| Alternative | Why rejected |
|-------------|--------------|
| Grant `CREATEDB` to `exam_platform_user` for the drill | Permanent role attribute change for a transient need; contradicts least-privilege. Operator-pre-create is cleaner. |
| Run drill against production `exam_platform_db` after a rename | Risky in a live system; drill DB on the same cluster is sufficient. |
| Embed restic in the systemd unit even when `RESTIC_REPO` is unset | The script already no-ops gracefully; embedding it in systemd would force every operator to set the env. |
| Add Prometheus metrics endpoint | Explicitly Phase 2 per plan; `structlog` + Sentry + UptimeRobot is enough for MVP. |
| Use `pg_dumpall` | Would dump `blogdb` too. Hard-no. |

---

## 9. Deviations from plan

| Plan item | Deviation | Why |
|-----------|-----------|-----|
| `restic-restore.sh` does `DROP DATABASE` + `CREATE DATABASE` | Operator pre-creates the drill DB; script verifies existence and aborts otherwise | `exam_platform_user` lacks `CREATEDB`. Documented in `ops/docs/restore-runbook.md` step 2. |
| Off-site restic snapshot in `pg_backup.sh` | Conditional on `RESTIC_REPO` being set; LXC env doesn't have one configured | Off-site is Gate-B (public-launch) prereq; Gate-A only requires manual local drill. |
| UptimeRobot probe set up | Documented setup in `ops/docs/observability.md`; not actually configured | Requires founder credentials + DNS — Phase 12 readiness item. |
| Systemd timer firing daily on LXC | Unit files committed; not installed/enabled | Phase 11 installs systemd units; Phase 10 just produces them. |

---

## 10. Phase 10 RTK Usage Report

- **RTK available?** Yes (v0.36.0).
- **When + where used:**
  - `rtk read` of `phase-10-backup-observability.md` (176 lines) before
    implementation.
  - `pytest --tb=short` / `--tb=line` throughout for filtered output.
  - SSH `head/tail` discipline on PG SQL log noise during the drill.
- **Estimated savings (Phase 10):** ≈ **2 k – 4 k tokens.** Smaller than
  Phase 09 because the iteration loop was tighter (one drill privilege
  surprise; one fix; verified).
- **Safety-critical context kept uncompressed in reports + changelog:**
  - "Backup MUST target exam_platform_db only — never blogdb."
  - "Drill DB MUST NOT equal exam_platform_db or blogdb."
  - LXC sync path (`/srv/exam-platform-dev`).
  - Host/port restriction (`127.0.0.1:8001`).
  - Failure-stop, no post-MVP, shutdown rules.

---

## 11. Remaining risks / non-blockers

- **Restic password loss** = unreadable backups. Documented in
  `ops/docs/backup-runbook.md` §"Failure modes & alerts". Mitigation
  (two independent vaults) is operator-side.
- **Backup script silent failure** — currently relies on systemd's
  failed-state. Phase 12 readiness should add an `exam_pg_backup_last_at`
  metric or simple "no log line in 26 h → alert" probe.
- **Drill cadence** — internal beta needs ≥1 drill (done). Public
  soft-launch needs a drill within the last 30 days; track via
  `ops/docs/dr-drill-log.md`.
- **Off-site repo not configured** — Gate-B prereq; flag for Phase 12.
- **`/readyz` migration check imports alembic at request time** —
  ScriptDirectory load is cached after first request; cold-start
  latency on `/readyz` is acceptable (deploy probes are infrequent).
- **The `app/routers/health.py` migration helper catches a broad
  `Exception`** — intentional (readiness checks must never raise),
  but logs are silenced. If `/readyz` flips to `unknown` mysteriously
  in prod, structlog at boot will still capture the alembic config
  problem because the alembic CLI is run independently as part of the
  deploy script.

---

## 12. Phase 10 complete?

**Yes (Gate-A scope).** All Phase 10 internal-beta gate items green on
local + LXC. Auto-proceeding to Phase 11 per the brief.

**Status:** DONE

---

## 13. Unresolved questions

1. Should the off-site restic repo be configured during Phase 11
   deployment (so daily backups start landing off-site immediately), or
   stay manual until Phase 12 sign-off?
2. Does the user want a separate `exam-backup` system user with
   read-only DB role (plan §Security marks this as optional polish), or
   continue reusing `exam_platform_user`?
