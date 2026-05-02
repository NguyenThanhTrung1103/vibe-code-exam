---
title: Phase 13 — Production Migration Plan for `exam_platform_db`
date: 2026-05-02 08:47 (Asia/Saigon)
plan: ../260430-2233-cdea-phase-13-16a/phase-13-discussion-url-parser.md
prior_reports: phase-13-260502-0753-completion.md, phase-13-260502-0806-step-d-lxc-isolated-plan.md
host: win32 (Windows dev box) → LXC 192.168.99.97 via `exam-lxc` SSH alias
target: real `exam_platform_db` on LXC PG14 (NOT smoke, NOT blogdb)
local_commit: d043f14 (feat(community): Phase 13 ...)
status: APPROVED PLAN, EXECUTION HALTED at Step A.8 — LXC venv missing Phase 13 deps; awaiting your dep-install decision
---

# Phase 13 — Production Migration Plan

> Apply migration `0006_b1c2d3e4f5a6_phase13_community_sources.py` to `exam_platform_db` on LXC.
> Additive-only, zero downtime expected, no service touch.
> First commit `d043f14` is local-only; no GitHub push planned in this session.

## Approach

Single SSH session (root@192.168.99.97 via the `exam-lxc` alias). Migration runs from `/srv/exam-platform` using the same `.venv` that uvicorn uses, reading `DATABASE_URL` from `/srv/exam-platform/.env`. App stays running. The migration is purely additive (4 enums, 1 table, 6 indexes, 1 column with `DEFAULT 0`) so no `AccessExclusiveLock` long enough to harm in-flight requests.

## Execution sequence

### A. Pre-flight (read-only) — observed 2026-05-02 08:36 ICT

| # | Check | Expected | Actual |
|---|---|---|---|
| A.1 | local HEAD = `d043f14` | yes | ✅ `d043f14af0a2d17ff1160a9c86ff04d96df12c3f` |
| A.1 | working tree clean | yes | ✅ empty `git status --short` |
| A.2 | LXC user / paths | root, /srv/exam-platform writable, .env protected | ✅ `uid=0(root) gid=0(root) groups=0(root)`; /srv/exam-platform = `drwxr-x--- 10 root exam-platform`; .env = `-rw-r----- 1 root exam-platform`; .venv = `drwxr-xr-x 5 exam-platform exam-platform` |
| A.3 | 6 services active | yes | ✅ postgresql, redis-server, nginx, cloudflared, blog.service, exam-platform-web.service all `active` |
| A.4 | /healthz | HTTP 200, db ok, redis ok | ✅ `HTTP 200 {"status":"ok","db":"ok","redis":"ok"}` |
| A.5 | DATABASE_URL points at exam_platform_db | yes | ✅ `postgresql+psycopg://exam_platform_user:***REDACTED***@127.0.0.1:5432/exam_platform_db` |
| A.6 | DBs present | blogdb, exam_platform_db | ✅ both |
| A.7 | prod alembic current | `a1b2c3d4e5f6 (head)` | ✅ `a1b2c3d4e5f6 (head)` |
| **A.8** | **Phase 13 deps importable on LXC venv** | bs4, lxml, tenacity, httpx all importable | **❌ `ModuleNotFoundError: No module named 'bs4'`** |

**Step A halted at A.8.** Per Decision #5 of the prod plan: *"If this fails, stop before migration and report."*

#### A.8 details

- LXC venv at `/srv/exam-platform/.venv` was provisioned before Phase 13 added bs4/lxml/tenacity/httpx to `pyproject.toml`'s `[project] dependencies`.
- `from app import models` (alembic-needed import only) succeeds — alembic itself does NOT pull bs4.
- `import app.main` succeeds **today** because the running app is still on the pre-Phase-13 commit.
- `app/services/community_dump_parser.py` is the only module that imports bs4. After rsync deploys it, anyone who triggers an HTML-paste community-import path would crash on import.
- pyproject.toml/uv.lock declare these as runtime deps. Latent bug regardless of Phase 13.

#### A.8 unblock options (your call)

| # | Approach | Risk | Recommendation |
|---|---|---|---|
| 1 | `pip install` direct: `ssh exam-lxc 'cd /srv/exam-platform && /srv/exam-platform/.venv/bin/pip install beautifulsoup4 lxml tenacity httpx'` | Bypasses uv.lock; possible drift | Quick fix only |
| 2 | `uv sync` after rsync: `ssh exam-lxc 'cd /srv/exam-platform && uv sync'` | Reconciles to uv.lock; canonical | **Recommended** |
| 3 | Skip dep install (alembic doesn't strictly need them) | Knowingly latent bug | Not recommended |
| 4 | Abort prod deploy until later | Phase 13 stays committed-but-undeployed | Acceptable |

### B. Save plan file — DONE

This file: `plans/reports/phase-13-260502-0829-prod-migration-plan.md`. Not committed.

### C. Rsync (PENDING — blocked behind A.8)

Excludes (per your safety list):
```
.git/
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.opencode/
.claude/skills/
uploads/
app/uploads/
logs/
*.log
.env
.env.*
release-manifest.json
```

Dry run first:
```bash
rsync -avzn \
  --exclude=.git/ --exclude=.venv/ --exclude=__pycache__/ \
  --exclude=.pytest_cache/ --exclude=.mypy_cache/ --exclude=.ruff_cache/ \
  --exclude=.opencode/ --exclude=.claude/skills/ \
  --exclude=uploads/ --exclude=app/uploads/ --exclude=logs/ \
  --exclude='*.log' --exclude=.env --exclude='.env.*' \
  --exclude=release-manifest.json \
  ./ exam-lxc:/srv/exam-platform/
```

Live (only after dry-run review):
```bash
rsync -avz \
  [same excludes] \
  ./ exam-lxc:/srv/exam-platform/
```

`--delete` NOT used. If dry-run shows deletion of `.env`, `.venv`, `uploads`, `logs`, blog files, or any LXC config — STOP.

### D. Backup (PENDING)

```bash
ssh exam-lxc 'sudo mkdir -p /var/backups/exam-platform && sudo chown postgres:postgres /var/backups/exam-platform && sudo chmod 0700 /var/backups/exam-platform'

ssh exam-lxc 'sudo -u postgres pg_dump \
  --format=custom --compress=9 --jobs=1 --no-acl --no-owner \
  --file=/var/backups/exam-platform/exam_platform_db-pre-phase13-$(date -u +%Y%m%dT%H%M%SZ).dump \
  exam_platform_db'

ssh exam-lxc 'BAK=$(ls -t /var/backups/exam-platform/exam_platform_db-pre-phase13-*.dump | head -1); ls -lh "$BAK"; sudo -u postgres pg_restore --list "$BAK" | head -5'
```

Backup retained 7+ days per Decision #4. NOT cleaned without explicit approval.

### E. Guard chain (PENDING)

5 string assertions on DATABASE_URL + server-side `current_database()` + `alembic current` matches `a1b2c3d4e5f6`. Any failure → STOP before migration.

### F. Migration (PENDING)

```bash
ssh exam-lxc 'cd /srv/exam-platform && /srv/exam-platform/.venv/bin/alembic upgrade head 2>&1 | tee /tmp/phase13-upgrade-$(date -u +%Y%m%dT%H%M%SZ).log'
```

Expected last line: `Running upgrade a1b2c3d4e5f6 -> b1c2d3e4f5a6, phase13-community-sources` then exit 0. App **NOT** restarted (Decision #6).

### G. Post-migration verification (PENDING) — read-only ONLY (Decision #8)

| Check | Expected |
|---|---|
| `alembic current` | `b1c2d3e4f5a6 (head)` |
| `community_discussion_sources` columns | 29 |
| `questions.row_version` | `integer NOT NULL DEFAULT 0` |
| 4 community enums | exist with expected ordered values |
| 6 indexes (3 partial) | present |
| 5 constraints (1 PK, 1 UNIQUE, 1 CHECK, 2 FK) | present |
| `community_discussion_sources` rowcount | 0 |
| `questions` rowcount | unchanged from pre-migration snapshot |
| `min(row_version), max(row_version)` | (0, 0) |
| /healthz | 200 ok |
| 6 services active | all active |

NO mutating tests run on prod (Decision #8).

### H. Final local gates (PENDING)

Will run only if local code changed during execution. The plan-file save in Step B is markdown-only inside `plans/reports/` — does NOT trigger ruff/mypy/pytest.

## Read-only vs write summary

| Step | Op | Read-only | Write |
|---|---|---|---|
| A | systemctl, psql, curl, alembic current | ✅ | |
| B | save plan markdown locally | | ✅ (Windows FS, plans/reports/) |
| C | rsync dry-run | ✅ | |
| C | rsync live | | ✅ (LXC FS, /srv/exam-platform/) |
| D | mkdir + chown + pg_dump + ls | mkdir/chown + dump = ✅ write | ✅ |
| E | guard chain | ✅ | |
| F | alembic upgrade head | | ✅ (DDL on exam_platform_db only) |
| G | verification | ✅ | |
| H | local gates if needed | ✅ | |

Cluster-level writes touch only:
- `/var/backups/exam-platform/` (dump file) — new directory.
- `/srv/exam-platform/` (rsync, excluded .env / .venv / uploads / logs).
- `exam_platform_db` schema (alembic upgrade — additive).

NO write to: blogdb, blog role, /srv/blog-website, nginx, cloudflared, postgresql.conf, pg_hba.conf, redis config, blog.service.

## Risk assessment + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Backup corrupt | Low | High | `pg_restore --list` validates archive |
| Migration partial fail | Very low | Medium | Alembic transactional DDL auto-rollback |
| Rsync overwrites `.env` | Critical if happens | Critical | `--exclude=.env` + dry-run review |
| Rsync clobbers LXC-local edits | Low | Medium | `-n` dry-run lists every change first |
| App stalls on AccessExclusiveLock | Very low | Low | sub-second on additive migration |
| LXC venv missing deps after migration | **Confirmed (A.8)** | Latent runtime crash | Dep-install option needed before proceeding |

## Rollback plan

| Severity | Use | Command outline |
|---|---|---|
| Migration aborted mid-tx | Nothing — already auto-rolled back to `a1b2c3d4e5f6` | n/a |
| Migration committed but app breaks | `alembic downgrade -1` (safe — Phase 16a not yet writing data) | `ssh exam-lxc 'cd /srv/exam-platform && /srv/exam-platform/.venv/bin/alembic downgrade -1'` |
| Schema corruption | `pg_restore` from backup | stop app → drop+create exam_platform_db → pg_restore — explicit approval required |

## Phase 16a readiness gate

- ✅ Phase 13 code committed (d043f14, local).
- ⏸ Phase 13 migration applied to real exam_platform_db (this plan, currently halted at A.8).
- ⏸ d043f14 pushed to origin/master (deferred per Decision #3).
- Phase 16a writes to/from `community_discussion_sources` — table must exist on prod first.

**Phase 16a does NOT begin until A.8 resolved + Steps C–G complete green.**

## GitHub push timing (Decision #3)

Not pushed. To revisit AFTER successful prod migration. If push proceeds before migration: failed migration would already be visible on remote with no clean undo path. Push-after = safer.

## Decisions summary (your input)

| # | Decision | Status |
|---|---|---|
| 1 | rsync (not push) | accepted |
| 2 | exam-lxc alias, root | accepted, verified A.2 |
| 3 | no GitHub push | accepted |
| 4 | retain backup 7+ days | accepted |
| 5 | dep-check halt rule | **honored — currently halting at A.8** |
| 6 | leave services running | accepted |
| 7 | save plan to `plans/reports/phase-13-260502-0829-prod-migration-plan.md` | DONE (this file) |
| 8 | no prod-mutating tests | accepted |

## Skills / rules used

| File | Path | Why |
|---|---|---|
| Root `CLAUDE.md` | `E:\Vibe Code\Vibe Code\Exam\CLAUDE.md` | Privacy-block + commit conventions (no commits this turn) |
| Project `CLAUDE.md` | `E:\Vibe Code\Vibe Code\Exam\.claude\CLAUDE.md` | Project standards |
| `development-rules.md` | `E:\Vibe Code\Vibe Code\Exam\.claude\rules\development-rules.md` | Honor "stop on failure" rule literally; no auto-fix without approval |
| `primary-workflow.md` | `E:\Vibe Code\Vibe Code\Exam\.claude\rules\primary-workflow.md` | Verify-each-step gate cadence |
| `documentation-management.md` | `E:\Vibe Code\Vibe Code\Exam\.claude\rules\documentation-management.md` | Plan saved to `plans/reports/` |
| `orchestration-protocol.md` | `E:\Vibe Code\Vibe Code\Exam\.claude\rules\orchestration-protocol.md` | No subagents — single-host flow |
| `git/SKILL.md` | `E:\Vibe Code\Vibe Code\Exam\.claude\skills\git\SKILL.md` | Pre-deploy git sanity (HEAD + clean tree) |
| `databases/SKILL.md` | `E:\Vibe Code\Vibe Code\Exam\.claude\skills\databases\SKILL.md` | `references/postgresql-administration.md` covers pg_dump pattern adopted in Step D |

No project-specific Alembic / production-deploy / blue-green skill exists. Closest applicable: `databases/`. Honest acknowledgment.

## RTK status

Hook NOT installed → passthrough only. 0% actual savings this turn. Pre-flight outputs (~80 lines) are small enough that RTK savings would be minimal here regardless. Safety-critical outputs (DATABASE_URL guard, current_database, alembic current, /healthz, service-active matrix, dep-check failure) all kept verbatim per the plan's explicit non-compress list.

## Unresolved questions

1. **Pick Option 1, 2, 3, or 4 for A.8 (LXC venv dep mismatch).** I recommend Option 2 (`uv sync` on LXC after rsync). Without your decision, Steps C–G remain blocked.
2. After dep install, do you want me to re-verify A.8 before proceeding to C, or treat it as resolved?
3. Once A.8 is resolved and migration succeeds: confirm whether to (a) commit this plan file as `docs(plans): prod migration plan for Phase 13` immediately, or (b) hold all commits including the plan file until you also approve a push window.

---

**End of plan. Step A.8 halted; awaiting dep-install decision.**
