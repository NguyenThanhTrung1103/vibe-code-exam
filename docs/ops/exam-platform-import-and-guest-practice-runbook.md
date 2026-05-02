# Import + Guest Practice — Operations Runbook

**Audience:** Operator / on-call.
**Scope:** LXC `192.168.99.97`, systemd unit `exam-platform-web.service`, DB `exam_platform_db`.
**Last updated:** 2026-05-02 (Milestone 1 deploy).

This runbook covers ONLY Milestone 1 (multi-format admin import). Milestone 2 (guest practice) ships dormant — see "Guest practice — currently dormant" below.

---

## 1. Pre-deploy checklist (run on dev workstation)

```bash
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run pytest -q
```

All four must be green. **If pytest is red, do not deploy.**

Then locally:

```bash
uv run alembic upgrade head
uv run alembic current   # expect: e4f5a6b7c8d9 (head)
```

Smoke-verify the schema:

```bash
psql -h 127.0.0.1 -U exam_user -d exam_platform_dev -c "\d imports"  | grep -E "title|detected_format"
psql -h 127.0.0.1 -U exam_user -d exam_platform_dev -c "\d attempts" | grep -E "guest_token|user_id"
```

Expected:
- `imports.title` — `character varying(255)`, nullable
- `imports.detected_format` — `character varying(32)`, nullable
- `attempts.guest_token` — `character varying(64)`, nullable
- `attempts.user_id` — `bigint`, **nullable** (relaxed by 0008)

---

## 2. Deploy to LXC `192.168.99.97`

Sequence is **strict**: code → deps → migrations → restart → health.

```bash
# 1) sync code from controller workstation
rsync -avz --delete --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  ./ root@192.168.99.97:/opt/exam-platform/

# 2) install deps (note: pdfminer.six is new in this slice)
ssh root@192.168.99.97 'cd /opt/exam-platform && uv sync --frozen'

# 3) migrate exam_platform_db
ssh root@192.168.99.97 'cd /opt/exam-platform && uv run alembic upgrade head'
ssh root@192.168.99.97 'cd /opt/exam-platform && uv run alembic current'   # expect: e4f5a6b7c8d9

# 4) restart ONLY the app
ssh root@192.168.99.97 'systemctl restart exam-platform-web.service'
ssh root@192.168.99.97 'systemctl is-active exam-platform-web.service'     # expect: active

# 5) health
ssh root@192.168.99.97 'curl -fsS http://127.0.0.1:8001/healthz'
# expect JSON with db=ok redis=ok
ssh root@192.168.99.97 'curl -fsS http://127.0.0.1:8001/readyz'
# expect alembic head matches the current revision
```

**Do NOT** restart `nginx`, `cloudflared`, `postgresql`, `redis`. They are unaffected.

---

## 3. Post-deploy smoke (admin UI, 5 minutes)

In a browser:

1. `GET /auth/login` → 200, login as admin.
2. `GET /admin/imports` → 200, lists prior imports.
3. Click **Upload**. Upload a small XLSX with 3 rows (canonical English headers). Confirm `detected_format = xlsx` is shown on the done page.
4. Repeat with one Vietnamese-header XLSX (e.g. `câu_hỏi`, `đáp_án_đúng`). Confirm rows are mapped correctly via the alias map.
5. Repeat with one combined-options XLSX (single cell with `A. ... ; B. ...`). Confirm the preview splits into option_a / option_b.
6. (Optional) Upload a small saved ExamTopics-style HTML page with one question. Confirm `detected_format = examtopics_html` and the row appears in preview.
7. (Optional) Upload a `.txt` with `QUESTION 1` / `A.` / `B.` / `Answer:` / `Explanation:`. Confirm `detected_format = qblock_text`.
8. On `/admin/imports/{id}/done`, click **Review imported questions** — should land on `/admin/questions?source_import_id={id}` with the imported rows.

**Do not** run a "real" import (full-bank dump) without operator approval.

---

## 4. Roll back

If smoke fails OR `/healthz` returns non-200:

```bash
# 1) restore code
ssh root@192.168.99.97 'cd /opt/exam-platform && git fetch && git checkout <previous-good-sha>'
ssh root@192.168.99.97 'cd /opt/exam-platform && uv sync --frozen'

# 2) downgrade DB three steps if schema is the suspect
ssh root@192.168.99.97 'cd /opt/exam-platform && uv run alembic downgrade -3'   # back through 0009→0008→0007→prior

# 3) restart app
ssh root@192.168.99.97 'systemctl restart exam-platform-web.service'
ssh root@192.168.99.97 'curl -fsS http://127.0.0.1:8001/healthz'
```

Each migration's `downgrade()` is a `drop_column`/`drop_constraint`. Safe on rows that never used the column (which is the case at deploy time — nobody is using guest_token).

---

## 5. Common failures and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| `/healthz` returns `db=err` | Alembic migration didn't run | re-run `alembic upgrade head` and tail `journalctl -u exam-platform-web -n 50` |
| `/healthz` returns `redis=err` | redis-server is down (independent service) | `systemctl status redis-server` — operator must investigate redis separately. Do NOT auto-restart redis from this runbook. |
| Upload returns 500 on PDF | `pdfminer.six` wheel missing | re-run `uv sync --frozen`; the adapter raises `RuntimeError("pdfminer.six is required …")` with a clear message |
| Detector returns `detected_format = NULL` for a known-good XLSX | Wrong file extension OR not a real XLSX (zip-magic check) | Inspect the file with `unzip -l` — should list `xl/workbook.xml`. If the file is a `.xls` (legacy binary), reject — out of scope. |
| HTML adapter returns zero rows | Page wasn't saved with the question DOM | The user saved a thumbnail/index page, not the actual question page. Ask them to use "Save Page As → Web Page, complete" on the per-question URL. |
| Confirm fails with "No rows were staged" | Mapping step never ran | Open `/admin/imports/{id}/mapping`, finish the mapping, then re-confirm. |

---

## 6. Guest practice — currently dormant

The `attempts.guest_token` column AND `app/auth/guest.py` ship with this deploy but are **not reachable**.

What this means in practice:

- A user **cannot** practise without being logged in. All practice routes still require `CurrentUser`.
- No HTTP code path issues an `exam_guest_token` cookie.
- The DB column is present but unused; existing rows have `user_id` populated and the CHECK constraint `ck_attempts_owner` is satisfied.
- A future Milestone 2 deploy will wire the cookie helper into `routers/practice.py`, add a public review route, and lift the auth gate for published exams. **Operator approval required** before that ships.

If anything in production tries to set `attempts.guest_token` today, that is a bug — please report.

---

## 7. Boundaries (operator standing instruction, 2026-05-02)

When deploying via this runbook, **do not**:

- push to GitHub
- auto-commit (operator approves commits manually)
- run a real (large) import without explicit approval
- run cleanup SQL
- fetch / scrape any internet resource
- touch `nginx`, `cloudflared`, `postgresql`, `redis`, blog services
- restart any service other than `exam-platform-web.service`

---

## Unresolved questions

- We assume `/opt/exam-platform/` as the deploy root on LXC. Confirm with prior phase reports if different.
- We assume `uv sync --frozen` on LXC. If LXC uses a pinned venv path (`.venv` outside repo), document the venv-recovery runbook reference.
