# Exam Platform — Multi-format Import Runbook

Audience: operator deploying Milestone 1 to LXC `192.168.99.97` (single-user app).
Last reviewed: 2026-05-02.

## What this delivers

* Admin upload accepts `.xlsx`, `.html`/`.htm`, `.pdf`, and `.txt`.
* XLSX uploads continue to walk through the column-mapping wizard.
* HTML / PDF / TXT uploads skip mapping and go straight to preview because
  the parser-adapter emits canonical rows directly.

## Boundaries (do NOT cross)

* No GitHub push. No `git commit` unless the user explicitly approves.
* No cleanup SQL. No "real large import" without explicit approval.
* No internet fetch / scrape from the parsers — local files only.
* No changes to nginx, cloudflared, PostgreSQL config, Redis config, or blog.
* Do not restart unrelated services. Only touch
  `exam-platform-web.service`.
* Keep LAN 8001 exposure as-is.

## Preflight (on the dev box, before sync)

```bash
cd /e/Vibe\ Code/Vibe\ Code/Exam
uv run pytest                        # 294 passed, 98 real-DB skipped
uv run alembic heads                 # e4f5a6b7c8d9 (head)
```

Tests must be green. Stop here if anything is red.

## Deploy steps (on the LXC)

### 1. Backup the database

```bash
sudo -u postgres mkdir -p /var/backups/exam-platform
TS=$(date -u +%Y%m%dT%H%M%SZ)
sudo -u postgres pg_dump --format=custom \
  --file=/var/backups/exam-platform/exam_platform_db-${TS}.dump \
  exam_platform_db
sudo -u postgres pg_restore --list /var/backups/exam-platform/exam_platform_db-${TS}.dump | head
```

`pg_restore --list` must print a non-empty TOC. Record the backup path in
`docs/reports/changelog-local.md`.

### 2. Sync code

From the dev box (whichever path is canonical for your rsync setup — the
nginx/cloudflared/redis configs on the LXC are **not** in this tree, so
they cannot be touched accidentally):

```bash
rsync -av --delete \
  --exclude='.git/' --exclude='.venv/' --exclude='__pycache__/' \
  --exclude='Template Dump/' --exclude='node_modules/' \
  /e/Vibe\ Code/Vibe\ Code/Exam/ \
  exam-lxc:/opt/exam-platform/
```

### 3. Install dependencies through the project workflow

```bash
ssh exam-lxc 'cd /opt/exam-platform && uv sync --extra dev'
```

`uv sync` updates the project venv based on `uv.lock`. Do **not** invoke
global pip on the LXC.

### 4. Apply migrations

```bash
ssh exam-lxc 'cd /opt/exam-platform && uv run alembic upgrade head'
```

Expected: head reaches `e4f5a6b7c8d9`. If it does not match, abort and
restore from the backup.

### 5. Restart only the web service

```bash
ssh exam-lxc 'sudo systemctl restart exam-platform-web.service'
ssh exam-lxc 'systemctl is-active exam-platform-web.service'        # → active
```

Do **not** restart `redis`, `postgres`, `nginx`, `cloudflared`, RQ workers,
or anything else.

### 6. Smoke checks

```bash
# Health (db + redis green)
curl -fsS http://192.168.99.97:8001/healthz
# {"status":"ok","db":"ok","redis":"ok"}

# Anonymous /admin/imports → redirect to login
curl -isS http://192.168.99.97:8001/admin/imports | head -1
# HTTP/1.1 303 See Other  (Location: /auth/login...)

# Authenticated /admin/imports loads (use real admin cookie)
curl -isS -b cookies.txt http://192.168.99.97:8001/admin/imports | head -1
# HTTP/1.1 200 OK
```

### 7. Operator end-to-end check (browser)

Log in as admin → `/admin/imports` and upload each fixture from
`Template Dump/`:

| Fixture | Expected `detected_format` chip | Next page after upload |
|---|---|---|
| `import_quiz_question_ccna_online.xlsx` | `xlsx` | mapping → preview → confirm |
| `57q_efw.html` | `examtopics_html` | preview directly → confirm |
| `646b6d2013bb103e361af8674630dcb6_2.pdf` | `qblock_pdf` | preview directly → confirm |

Verify on the **Done** page that the "Review imported questions" link is
present and lands on a non-empty question detail page.

## Rollback

### Migration-only rollback

```bash
ssh exam-lxc 'cd /opt/exam-platform && uv run alembic downgrade c2d3e4f5a6b7'
ssh exam-lxc 'sudo systemctl restart exam-platform-web.service'
```

`c2d3e4f5a6b7` is the revision *before* `attempts.guest_token` and
`imports.detected_format`. Drops both columns.

### Full database rollback (last resort)

```bash
ssh exam-lxc 'sudo systemctl stop exam-platform-web.service'
ssh exam-lxc 'sudo -u postgres pg_restore --clean --if-exists \
  --dbname=exam_platform_db /var/backups/exam-platform/<dumpfile>.dump'
ssh exam-lxc 'sudo systemctl start exam-platform-web.service'
```

This wipes any data created since the backup. Only use if the
migration-only rollback fails.

## Logs and diagnostics

* Web service logs:
  `journalctl -u exam-platform-web.service -e --no-pager | tail -200`
* Healthcheck:
  `curl -fsS http://192.168.99.97:8001/healthz`
* Recent imports:
  Admin → `/admin/imports` → "Recent imports" table at the bottom shows the
  detected_format chip, status, and total / failed counts.

## Manual deploy (copy-paste)

Use when the operator runs the deploy themselves on the LXC. Each block is
self-contained — paste verbatim and read the output before moving on.

> Replace `<DUMP>` with the actual filename emitted in step 1 if you skip
> the `TS=` shell variable. Replace `/path/from/dev/exam-platform/` with
> wherever you sync from on the dev box.

### 1. Backup `exam_platform_db` (custom format)

```bash
sudo -u postgres mkdir -p /var/backups/exam-platform
TS=$(date -u +%Y%m%dT%H%M%SZ)
sudo -u postgres pg_dump --format=custom \
  --file=/var/backups/exam-platform/exam_platform_db-${TS}.dump \
  exam_platform_db
ls -lh /var/backups/exam-platform/exam_platform_db-${TS}.dump
sudo -u postgres pg_restore --list \
  /var/backups/exam-platform/exam_platform_db-${TS}.dump | head -20
echo "BACKUP_PATH=/var/backups/exam-platform/exam_platform_db-${TS}.dump"
```

`pg_restore --list` should print a non-empty TOC. Record the BACKUP_PATH
value in `docs/reports/changelog-local.md`.

### 2. Sync code from the dev box

Run on the **dev box** (Windows PowerShell with rsync via WSL or scp):

```bash
# rsync (WSL/git-bash style)
rsync -av --delete \
  --exclude='.git/' --exclude='.venv/' --exclude='__pycache__/' \
  --exclude='Template Dump/' --exclude='node_modules/' \
  /e/Vibe\ Code/Vibe\ Code/Exam/ \
  <user>@192.168.99.97:/opt/exam-platform/
```

If rsync is not available, alternative is to tar-and-scp:

```bash
tar --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    --exclude='Template Dump' --exclude='node_modules' \
    -C "/e/Vibe Code/Vibe Code/Exam" -czf /tmp/exam-platform.tgz .
scp /tmp/exam-platform.tgz <user>@192.168.99.97:/tmp/
ssh <user>@192.168.99.97 'sudo rm -rf /opt/exam-platform.bak && \
  sudo mv /opt/exam-platform /opt/exam-platform.bak && \
  sudo mkdir -p /opt/exam-platform && \
  sudo tar -xzf /tmp/exam-platform.tgz -C /opt/exam-platform && \
  sudo chown -R <run-user>:<run-user> /opt/exam-platform'
```

### 3. Install dependencies via the project workflow

On the **LXC**:

```bash
cd /opt/exam-platform
uv sync --extra dev   # uses uv.lock; no global pip
```

### 4. Apply migrations

```bash
cd /opt/exam-platform
uv run alembic current     # record this — should be c2d3e4f5a6b7 or earlier
uv run alembic upgrade head
uv run alembic current     # should now print: e4f5a6b7c8d9 (head)
```

### 5. Verify schema (read-only)

```bash
sudo -u postgres psql exam_platform_db -c "\d imports"
sudo -u postgres psql exam_platform_db -c "\d attempts"
sudo -u postgres psql exam_platform_db -c "
  SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
  WHERE (table_name='imports'  AND column_name IN ('title','detected_format'))
     OR (table_name='attempts' AND column_name IN ('user_id','guest_token'))
  ORDER BY table_name, column_name;
"
sudo -u postgres psql exam_platform_db -c "
  SELECT conname, pg_get_constraintdef(oid)
  FROM pg_constraint
  WHERE conrelid = 'attempts'::regclass AND conname='ck_attempts_owner';
"
sudo -u postgres psql exam_platform_db -c "
  SELECT indexname, indexdef
  FROM pg_indexes
  WHERE tablename='attempts' AND indexname='ix_attempts_guest_token';
"
```

Expected:
- `imports.title` VARCHAR, NULLABLE.
- `imports.detected_format` VARCHAR(32), NULLABLE.
- `attempts.user_id` BIGINT, NULLABLE.
- `attempts.guest_token` VARCHAR(64), NULLABLE.
- `ck_attempts_owner` → `((user_id IS NOT NULL) OR (guest_token IS NOT NULL))`.
- `ix_attempts_guest_token` partial index `WHERE guest_token IS NOT NULL`.

### 6. Restart only the web service

```bash
sudo systemctl restart exam-platform-web.service
sleep 1
sudo systemctl is-active exam-platform-web.service     # → active
sudo systemctl status exam-platform-web.service --no-pager | head -10
```

### 7. Smoke test

```bash
# Healthcheck — db + redis green
curl -fsS http://192.168.99.97:8001/healthz
echo

# Anonymous /admin/imports → 303 to /auth/login
curl -isS http://192.168.99.97:8001/admin/imports | head -2

# Authenticated upload page (use a real admin cookie file)
# curl -isS -b cookies.txt http://192.168.99.97:8001/admin/imports | head -2

# Upload page advertises multi-format
curl -fsS -b cookies.txt http://192.168.99.97:8001/admin/imports | \
  grep -E 'accept=|Recent imports|Format' | head -5
```

### 8. Record results in the changelog

Edit `docs/reports/changelog-local.md` § "LXC deploy" with:
- BACKUP_PATH value from step 1.
- `alembic current` output before and after.
- Schema verification results (paste 4 short lines).
- `systemctl is-active` output.
- `/healthz` JSON.

### 9. Do **not** run a real (non-fixture) import unless the operator
explicitly approves. Stop here.

## Vietnamese XLSX dumps with a combined answer list

For Vietnamese Excel dumps with a combined answer list column, map it
to `combined_options`. `option_a` and `option_b` are **not** required
separately — the parser splits the combined cell on `;` / `；` /
newline into `option_a..option_f` during the parse step.

The mapping page on `/admin/imports/<id>/mapping` reflects this rule:
when `combined_options` is mapped, the Required-fields card no longer
flags `option_a` / `option_b` red and instead shows
"satisfied by combined_options" against each. A green banner
"Combined options column detected. It will be split into Option A..F
during parsing." appears at the top of the card.

A valid mapping is therefore:

1. `question_text` is mapped, **and**
2. `correct_answer` is mapped, **and**
3. **either** `option_a` and `option_b` are mapped individually,
   **or** `combined_options` is mapped.

Vietnamese alias notes:

* `Câu hỏi` → `question_text`
* `Danh sách đáp án (...)` → `combined_options`
* `Đáp án đúng (...)` → `correct_answer`
* `Giải thích đáp án` → `explanation`
* `Mô tả thêm` → `reference` (was `explanation`; the alias was changed
  on 2026-05-04 to remove the silent collision with
  `Giải thích đáp án`)
* `Tags` → `tags`

If two columns auto-map to the same canonical field, the mapping page
now shows a yellow warning listing the conflicting headers; pick a
single owner per canonical field to avoid silent overwrites.

### question_type aliases recognised by the importer

Excel dumps may use `question_type=choice`. The importer infers
`single` / `multiple` based on the resolved `correct_answer` count.
The full alias table the validator accepts:

| Cell value (case-insensitive, hyphens / spaces collapsed) | Stored as |
|---|---|
| `single`, `single_choice`, `one_choice`, `radio`         | `single` |
| `multiple`, `multi`, `multiple_choice`, `multi_choice`, `checkbox`, `checkboxes` | `multiple` |
| `true_false`, `truefalse`, `boolean`, `bool`, `tf`        | `true_false` |
| `choice` or blank                                         | inferred from `correct_answer` count (≥ 2 → `multiple`, else `single`) |

Anything outside this set still surfaces a clear
`question_type 'X' not in [...]` error so unknown values are not
silently mis-classified.

### correct_answer normalisation

The validator accepts the following correct-answer shapes (mixed
shapes within one cell are also fine — `,` / `;` / newline split
first, then per-entry resolution):

* Letter labels `A`..`F` (case-insensitive); single or multi via
  comma/semicolon/newline.
* Contiguous multi-letter answers `AC` / `BD` / `ACE` (no
  separator) are expanded into individual labels.
* Numeric labels `1`..`6` map to `A`..`F`. `1;3` → `A,C`,
  `4;6` → `D,F`, etc.
* Verbatim option text (case-fold) — the cell text is matched
  against each parsed option text.

A correct_answer that references a label with no matching option
(e.g. `E` when only `A`..`D` exist, or numeric `7` when the row
only carries 6 options) is a legitimate row-level error and stays
in the `error` bucket.

### Storage cap raised to A–F (six options)

`combined_options` and discrete `option_a`..`option_f` are now both
honoured end-to-end (validator + question_service +
attempt_service). The previous A–E cap rejected legitimate
six-option questions.

## Common issues

* **`detected_format` chip is blank** — the detector returned None. Either
  the file extension is wrong, or the content doesn't match any known
  signature. Re-save the HTML page in "complete" mode, or check the PDF
  starts with `%PDF-`.
* **PDF parses to 0 rows** — pdfminer returned empty text. The PDF is
  either image-only (scanned) or password-protected. No fallback —
  out of Milestone 1 scope.
* **Confirm refuses with "No rows were staged for this import"** — the
  parser produced zero canonical rows. Check the preview page for
  per-row errors; this is usually a fixture mismatch, not a service
  failure.

## How to review a dump that was already imported / duplicate rows

When you upload a dump and the preview page reports rows in the
`duplicates` bucket, the questions almost certainly live in the bank
already from a previous import. The wizard does **not** re-create them —
that is by design (idempotent confirm). Use this flow to find and review
the existing questions:

1. Open `/admin/imports`. The **Recent imports** table at the bottom of
   the page lists the latest 20 imports with their ID, dump title,
   filename, detected format, and status.
2. Locate the previous import for this dump by matching any of:
   * **Title** — admin-supplied label entered at upload time.
   * **Filename** — the original `.xlsx` / `.html` / `.pdf` / `.txt`.
   * **Detected format** — `xlsx` / `examtopics_html` / `qblock_pdf` /
     `qblock_text`.
   * **Import ID** — if you already know it (e.g. from an earlier session
     or the changelog).
3. Click **Review questions** on that row. This opens
   `/admin/questions?source_import_id=<id>` filtered to the live
   questions imported by that dump. The page shows a context header
   listing the import title, filename, detected format, and live count,
   plus **Back to imports** and **Back to import #N** links.
4. If the row shows **No imported questions** instead of the button,
   that import never produced live questions (every row was staged but
   none were confirmed, or all questions have been retired). Open the
   import via **Open import** to check the per-row staging state.

### Manual URLs for the current local imports

The seed/sync done on 2026-05-02 produced three imports whose live
questions are reachable at:

```
/admin/questions?source_import_id=137   # 37 questions  (XLSX)
/admin/questions?source_import_id=138   # 57 questions  (saved HTML)
/admin/questions?source_import_id=139   # 164 questions (PDF, qblock)
```

Bookmark these for the canonical review entry-points.

### When the exact previous import cannot be determined

The dedup step matches duplicates by **content hash**, not by import id,
so the preview page does not know which earlier import a duplicate row
came from. The duplicate banner therefore points you at:

* the search-by-title / filename / format flow on `/admin/imports`, and
* the per-exam fallback `/admin/questions?exam_id=<id>` for the target
  exam, which lists every question regardless of source import.

If the duplicate set spans multiple previous imports, expect to follow
both links.

### What this flow does **not** do

* No DELETE / UPDATE / re-import. The duplicate banner is read-only
  navigation, not a destructive action.
* No cleanup SQL. Deduping pre-existing questions is a separate runbook
  (`plans/reports/gate-a1-260502-cleanup.sql`) and is gated on operator
  approval.
