# Observability (Phase 10)

## Logging

- **Format:** structlog. Console renderer in dev/local/test, **JSON** in
  `prod` (and `staging`). Configured in `app/logging.py`.
- **Sink:** stdout. systemd's `journald` captures it (Phase 11). No file
  rotation logic in the app.
- **Per-request fields:** `request_id`, `path`, `method` (bound by
  `RequestIdMiddleware`).
- **Levels:** root = `Settings.log_level` (default `INFO`); third-party
  loggers inherit unless explicitly demoted.

## Sentry

- Initialised in `app.main._init_sentry` only when `SENTRY_DSN` is set.
- `release` is read from `SENTRY_RELEASE` (or `APP_RELEASE`) at startup;
  Phase 11 deploy script stamps the git SHA.
- `environment` = `Settings.env`.
- `send_default_pii=False` — never ship request bodies / cookies.
- Phase 09 production error handler runs **after** Sentry's ASGI
  capture, so traceback fidelity is preserved before the user sees the
  generic error page.

## Health endpoints

| Path | Purpose | What it checks |
|------|---------|----------------|
| `/healthz` | liveness — uptime probes | DB `SELECT 1`, Redis `PING` |
| `/readyz`  | readiness — deploy gates | the above PLUS alembic head match |

`/healthz` should be hit every 1–5 minutes by an external probe
(UptimeRobot recommended). `/readyz` is for deploy automation
(Phase 11) and the readiness checklist (Phase 12).

## UptimeRobot (Gate B prep)

1. Create a monitor:
   - Type: HTTP(s)
   - URL: `https://exam.example.com/healthz`
   - Interval: 5 minutes
   - Alert contacts: founder email + (later) Slack/PagerDuty.
2. Status page (free tier): expose `/healthz` so beta testers see green.
3. Document the monitor URL in this file once created.

## What's explicitly NOT in MVP

- Prometheus / Grafana — Phase 2.
- WAL archiving for PITR — Phase 2.
- Real-user monitoring (RUM) — Phase 2.
- Dashboards — Phase 2; Sentry's built-in views suffice for MVP.
