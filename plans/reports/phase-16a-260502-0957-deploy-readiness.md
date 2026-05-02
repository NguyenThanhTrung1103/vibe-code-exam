---
title: Phase 16a — Deploy-Readiness Verification
date: 2026-05-02 09:57 (Asia/Saigon)
purpose: Confirm Phase 16a code is committed locally but not yet on LXC; propose safe deploy plan
prior: phase-13-260502-0829-prod-migration-plan.md (Phase 13 prod-deploy reference)
status: VERIFIED — deploy not yet executed (pending operator approval at 10:04)
---

# Phase 16a — Deploy-Readiness Verification

## Result

| Question | Answer |
|---|---|
| Phase 16a code present on LXC? | **NO** |
| Running service serving Phase 16a? | **NO** |
| LXC at commit `81c2d74`? | **NO — rsync-based, no `.git/` dir on prod** (only `.gitignore`); production code matches `d043f14` snapshot from Phase 13 deploy at 08:21 |

## Evidence (verbatim)

| Probe | Result |
|---|---|
| Local `git log` shows `81c2d74` | ✅ present locally |
| `/srv/exam-platform/app/routers/admin/community_sources.py` | **MISSING** |
| `/srv/exam-platform/app/templates/admin/questions/community_tab.html` | **MISSING** |
| `app/main.py` grep `admin_community_sources` | no match — router not imported / not included |
| Route path grep `{question_id}/community` across `app/` | no match |
| `edit.html` grep `Community` | no match — tab strip absent |
| `/srv/exam-platform/.git` directory | absent — only `.gitignore` (rsync artefact) |
| `systemctl is-active` × 6 services | all `active` |
| `GET /healthz` | `HTTP 200 {"status":"ok","db":"ok","redis":"ok"}` |
| `GET /admin/questions/1/community` | `HTTP 404` ← route not registered |
| `GET /admin/questions/1/edit` (control) | `HTTP 401` ← route exists, RBAC kicks in |

The 404→401 contrast is the empirical proof — FastAPI returns 404 for unknown paths *before* any RBAC dependency.

## Why Phase 16a isn't on prod (timeline)

- 2026-05-02 ~08:21 — Phase 13 prod deploy. rsync delivered `d043f14`; alembic upgrade head ran; service untouched.
- 2026-05-02 ~09:29 — Phase 16a committed locally as `81c2d74`. AFTER the rsync. Never deployed.

## Boundaries respected

- ❌ No DB queries (no SELECT, no DDL, no DML)
- ❌ No `.env` cat / no secrets printed
- ❌ No `systemctl restart` / `start` / `stop` / `reload`
- ❌ No nginx / cloudflared / postgresql.conf / pg_hba.conf / redis config / blog.service touched
- ❌ No blog / blogdb / /srv/blog-website touched
- ❌ No GitHub push
- ❌ No code modification on either side

## Proposed deploy plan (approved by operator at 10:04 — see follow-up report)

Mirrors Phase 13 deploy. Smaller delta. Steps:

1. Pre-deploy snapshot — tar `/srv/exam-platform/app/{main.py,routers,templates}` to `/var/backups/exam-platform/pre-phase16a-<TS>.tar.gz`.
2. Stage on LXC `/tmp/exam-phase16a-stage/` via tar over SSH.
3. LXC-local rsync dry-run (no --delete, Phase-13 exclude list).
4. Review dry-run; abort if forbidden paths affected.
5. LXC-local live rsync.
6. Cleanup `/tmp/exam-phase16a-stage`.
7. **`systemctl restart exam-platform-web.service`** (only this service; ~3–5 sec downtime).
8. Verify: healthz 200, `/community` flips 404→401, `/edit` stays 401, all 6 services active.
9. No `uv sync` (Phase 16a adds zero new runtime deps).

## Skills/rules used

- `.claude/rules/development-rules.md` — KISS (don't repeat probes; minimal deploy)
- `.claude/rules/primary-workflow.md` — verify-before-extend
- `.claude/skills/git/SKILL.md` — local commit check
- `.claude/rules/documentation-management.md` — report saved to `plans/reports/`

## Open items

1. Service-restart approval — needed for new route registration.
2. Pre-deploy snapshot — for fast rollback.
3. Plan/report markdown sync — Phase 13 deploy synced; consistent to do same.
4. Untracked Gate-A1 markdown — committed separately as `20d1e86` before deploy.
