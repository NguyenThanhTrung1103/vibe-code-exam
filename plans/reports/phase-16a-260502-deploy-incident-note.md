---
title: Phase 16a Deploy — Incident Note (venv ownership / PermissionError on restart)
date: 2026-05-02
severity: SEV-2 (production-down ~5 min)
duration: 2026-05-02 03:02 UTC → 03:07 UTC (~5 min)
detected_by: scheduled post-deploy verification (`/healthz` connection refused, `journalctl` PermissionError)
recovery: chown -R + restart
status: RESOLVED + runbook hardened
---

# Phase 16a Deploy — Post-Incident Note

## Summary

Restarting `exam-platform-web.service` after the Phase 16a rsync caused uvicorn workers to crash-loop on `PermissionError` while importing `httpcore`. Root cause was a latent bug from the **earlier Phase 13 deploy**: `uv sync` had been run as `root` on the LXC, so the 7 newly-installed packages (incl. `httpcore`) landed owned `root:root` mode `0640`. The `exam-platform` service user wasn't in the `root` group, so workers couldn't read those files.

The bug stayed invisible until restart because the previously-running uvicorn workers had already cached `sentry_sdk → httpcore` imports from before `httpcore` ever existed in the venv. Restart forced a fresh import, exposed the bug, and downed the service.

Recovery was a one-line chown plus a service restart. Total downtime ~5 minutes.

## Impact

- **Production app**: unreachable for ~5 minutes (`/healthz` refused, no successful HTTP reaches the app).
- **Sibling services**: postgresql, redis-server, nginx, cloudflared, blog.service — **unaffected** (each `active` throughout).
- **Data**: zero data loss; no DB write attempted; no DB schema change; no migration ran.
- **Phase 13 + 16a code**: deployed correctly to disk; the bug was solely in venv perms.

## Root cause

Phase 13 production deploy ran:
```bash
ssh exam-lxc 'cd /srv/exam-platform && /root/.local/bin/uv sync'
```
because the only SSH user available is `root@exam-lxc` per project SSH config. `uv sync` installed:
```
+ beautifulsoup4==4.14.3
+ httpcore==1.0.9
+ httpx==0.28.1
+ lxml==6.1.0
+ soupsieve==2.8.3
+ tenacity==9.1.4
~ exam-platform==0.1.0   (editable reinstall)
```
All landed `root:root` `0640`. The systemd unit specifies `User=exam-platform`, which is not in the `root` group, so the new files were unreadable by the running service.

The pre-existing uvicorn workers had loaded everything they needed before this venv mutation, so the service ran fine until restart.

## Trigger

Phase 16a deploy required restarting `exam-platform-web.service` to register the new `/admin/questions/{id}/community` route in `app.main:create_app()`. The restart spawned fresh uvicorn workers; their cold-start `import sentry_sdk` chain reached `httpcore`, hit the perm denied, and died. uvicorn parent kept respawning workers in a tight loop.

## Recovery commands (executed)

```bash
# 1. Fix ownership recursively across the venv.
ssh exam-lxc 'chown -R exam-platform:exam-platform /srv/exam-platform/.venv'

# 2. Restart only the exam app service.
ssh exam-lxc 'systemctl restart exam-platform-web.service'
```

Total recovery time: ~10 seconds of remote work, ~5 minutes of total downtime including diagnosis.

## Verification commands (read-only, post-recovery — all passed)

```bash
# Service active.
ssh exam-lxc 'systemctl is-active exam-platform-web.service'
# Expected: active

# App reachable.
ssh exam-lxc 'curl -fsSm 5 http://127.0.0.1:8001/healthz'
# Expected: {"status":"ok","db":"ok","redis":"ok"} HTTP 200

# Phase 16a route registered (proves Phase 16a code is live).
ssh exam-lxc 'curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/admin/questions/1/community'
# Expected: 401 (was 404 pre-deploy — flip is the proof)

# Sibling services unaffected.
ssh exam-lxc 'for s in postgresql redis-server nginx cloudflared blog.service; do
  printf "%-32s %s\n" "$s" "$(systemctl is-active $s)"
done'
# Expected: 5× active

# Venv ownership clean.
ssh exam-lxc 'find /srv/exam-platform/.venv -not -user exam-platform | wc -l'
# Expected: 0
```

## Prevention rule

Documented in `docs/deployment-guide.md` (the canonical deploy runbook):

> **CRITICAL — venv ownership rule**: `uv sync` creates files owned by whoever runs it.
> The systemd unit runs uvicorn as `User=exam-platform`, so the venv must be readable
> by that user.
>
> **Preferred:** run `uv sync` as the service user
> (`sudo -u exam-platform /root/.local/bin/uv sync` or equivalent).
>
> **If `uv sync` was run as root** (e.g. via SSH `root@lxc`), you MUST run the recovery
> sequence before restarting the app:
> ```bash
> chown -R exam-platform:exam-platform /srv/exam-platform/.venv
> find /srv/exam-platform/.venv -not -user exam-platform | wc -l   # must print 0
> systemctl restart exam-platform-web.service
> ```

## Lessons

1. **Latent bugs from earlier deploys can lie in wait until restart.** Phase 13's deploy succeeded, the service kept running, but the bug surfaced later on the next restart. Future deploys should treat first-restart-after-uv-sync as a milestone.
2. **Always verify ownership matches the systemd `User=` setting** when packages are mutated.
3. **One-line emergency-recovery commands are worth memorising.** This was 10 seconds once we identified the cause; identification took 4-5 minutes from journalctl.
4. **Sibling services were untouched throughout** — boundary discipline held.

## Related

- Phase 13 deploy session: `plans/reports/phase-13-260502-0829-prod-migration-plan.md`
- Phase 16a deploy readiness: `plans/reports/phase-16a-260502-0957-deploy-readiness.md`
- Deployment runbook (now hardened): `docs/deployment-guide.md` (search for "venv ownership rule")

## Unresolved questions

1. Should the deploy script (eventually `scripts/deploy.sh` or similar) automate the `sudo -u exam-platform uv sync` invocation so this can never happen again?
2. Should systemd unit add a startup health-check that fails fast on import errors (rather than crash-loop indefinitely)?
3. Should `_editable_impl_exam_platform.pth` (which Phase 13 uv-sync briefly left root-owned) be checked specifically in any future deploy script?
