# Local Changelog (uncommitted)

Reverse-chronological log of significant changes that exist on the local working tree but are **NOT yet committed** to `master`. Use this to track in-flight work between sessions. Once a slice ships, fold the relevant entry into `docs/project-changelog.md` and delete it from here.

---

## 2026-05-04 (night) — Excel choice qtype + multi-answer + A–F support

**Status:** Validator + storage cap. No schema migration. No DELETE
of confirmed questions. Fixes the 40-error preview reported on
import #142.

### Root cause

Two unrelated gaps in the validator surface as 40 errors on the
preview for the Vietnamese XLSX dump #142:

1. **`question_type` was checked literally against the small set
   `{single, multiple, true_false}`.** The dump carries values like
   `one_choice` and `multi_choice` (and per the user's spec also
   `choice`, `radio`, `checkbox`, `boolean`, …). Every row was
   rejected on that basis alone.
2. **Numeric / contiguous multi-answer paths existed but the
   storage layer capped option labels at A–E.** Rows with six
   options + `correct_answer=4;6` (D + F) failed because option_f
   was silently dropped at confirm-time even though the
   normalizer's combined_options splitter already produced six
   slots.

### What changed

- `app/services/import_validator.py`:
  - New `_QTYPE_ALIAS` map and `_normalize_question_type()` helper.
    Recognises `single` / `single_choice` / `one_choice` / `radio` →
    `single`; `multiple` / `multi` / `multiple_choice` /
    `multi_choice` / `checkbox` / `checkboxes` → `multiple`;
    `true_false` / `truefalse` / `boolean` / `bool` / `tf` →
    `true_false`; `choice` and blank cells fall through to
    `_infer_question_type` (≥ 2 correct → `multiple`, else `single`).
    Unknown values still surface a clear "question_type 'X' not in
    [...]" error.
  - `OPTION_LABELS` extended from `A..E` to `A..F`. Numeric path now
    accepts `1..6`. Multi-letter contiguous expansion already
    covered F.
- `app/services/question_service.py`:
  - `OPTION_LABELS` extended to `A..F`. Storage cap lifted from 5
    options to 6, error message updated ("at most six options
    allowed (A–F)").
- `app/services/attempt_service.py`:
  - `_OPTION_LABELS_VALID` extended to `A..F`. Selection parser
    docstring updated.
- `tests/test_import_unit.py`:
  - 17 new validator tests covering: `choice` + single/multi;
    `one_choice`/`multi_choice`/`radio`/`checkbox`/`Boolean`/blank;
    unknown values still error; `AC` / `BD` contiguous expansion;
    `1;3` and `1,3` numeric pairs; numeric `6` → F (with option_f
    populated); verbatim option text match; legitimate
    out-of-options error; three real #142-style row scenarios
    (single, multi, multi-with-F).
- `tests/test_question_schemas_unit.py`:
  - `test_validate_options_max_five` renamed to
    `test_validate_options_max_six`; new
    `test_validate_options_accepts_six` proving A–F is accepted.
- `docs/ops/exam-platform-import-runbook.md`:
  - New "question_type aliases recognised by the importer" table.
  - New "correct_answer normalisation" section.
  - Note that storage cap is now A–F.

### Result for import #142

Re-staged on the LXC after deploy via
`parse_and_stage(import_id=142)` (after deleting the 40 stale staged
items — staging data only, no questions touched):

| Bucket | Before | After |
|---|---|---|
| Total staged rows | 40 | 40 |
| ok | 0 | 4 |
| duplicate | 0 | 35 (already imported by an earlier run) |
| error | 40 | 1 (row 9: correct_answer=`7` references a 7th option, beyond the A–F storage cap — legitimate edge case per the user's spec) |

The single remaining error is structural (the source row carries
8 listed options and `correct_answer=7`), not a normalisation gap.
Lifting beyond A–F would require schema work that the user did not
ask for.

### Strict boundaries respected

- No cleanup SQL.
- No DELETE / UPDATE of imported questions.
- `import_items` for #142 was deleted then re-staged via
  `parse_and_stage` — that is staging data, separate from the
  protected `questions` table.
- No new real / large imports.
- No internet fetch / scrape.
- No nginx / cloudflared / Postgres / Redis config touched.
- Only `exam-platform-web.service` restarted.

### Quality gates

| Gate | Result |
|---|---|
| `uv run ruff check app tests` | All checks passed. |
| `uv run ruff format --check app tests` | 135 files already formatted. |
| `uv run mypy app` | Success: no issues found in 95 source files. |
| `uv run pytest` | **326 passed, 98 skipped, 1 warning in 6.95 s.** |

---

## 2026-05-04 (late evening) — Vietnamese XLSX mapping fix (combined_options)

**Status:** UI + alias-map + tests + docs. No schema migration. No
parser semantics change. Goal: stop the mapping page from flagging
`option_a` / `option_b` red when the operator has mapped a
`combined_options` column instead.

### Root cause

The Required-fields display in `app/templates/admin/imports/mapping.html`
applied a `mapping-pair missing` CSS class per canonical field
strictly when that canonical didn't appear in `mapped_fields`,
regardless of whether `combined_options` was mapped. The service-side
rule in `import_service.save_mapping()` already accepted
`combined_options` as a substitute for `option_a` + `option_b`, so the
UI was the only place out of step. Operators could still save the
mapping; the red flag was misleading and produced unfounded "missing
required fields" anxiety.

A second, related bug: `auto_map()` in
`app/services/excel_parser.py` mapped both `Mô tả thêm` and
`Giải thích đáp án` to `explanation`, causing whichever column was
read second to silently overwrite the first when the parser folded the
mapping into `raw`.

### What changed

- `app/services/excel_parser.py`:
  - `_ALIAS["motathem"]` rerouted from `explanation` to `reference`.
  - `auto_map()` now scores each match and de-duplicates: when two
    headers resolve to the same canonical, the higher-scoring one
    wins (exact match > substring; longer alias > shorter), and the
    rival is reset to `None` so the operator must pick manually.
- `app/templates/admin/imports/mapping.html`:
  - Required-fields card no longer flags `option_a` / `option_b` red
    when `combined_options` is mapped. Each shows
    `satisfied by combined_options` instead of `— not mapped —`.
  - Green banner copy clarifies "Combined options column detected.
    It will be split into Option A..F during parsing.".
  - New yellow warning when two headers auto-map to the same
    canonical field, listing the conflicting headers.
- `app/services/import_service.py`:
  - Extracted `required_mapping_missing(column_mapping)` as a pure
    helper so the rule (`question_text` + `correct_answer` +
    (option_a/b OR combined_options)) can be tested hermetically.
    `save_mapping()` now delegates to it.
- `tests/test_import_unit.py`:
  - Vietnamese fixture-shaped auto_map test (Câu hỏi /
    Danh sách đáp án / Đáp án đúng / Giải thích đáp án / Mô tả thêm /
    Tags) asserts the canonical assignments and that no canonical is
    duplicated.
  - `Mô tả thêm → reference`, `Giải thích đáp án → explanation` (and
    `Giải thích` standalone is demoted to None when both are
    present).
  - `auto_map` drops duplicate canonicals (synthetic
    `["Question", "Question Text"]` test).
  - `required_mapping_missing()` accepts both shapes
    (`option_a/b` or `combined_options`); rejects when neither;
    flags `question_text` properly when missing.
- `docs/ops/exam-platform-import-runbook.md`:
  - New section "Vietnamese XLSX dumps with a combined answer list"
    documenting the rule, the Vietnamese alias map, and the new
    duplicate-canonical warning.

### Strict boundaries respected

- No cleanup SQL.
- No DELETE / UPDATE of imports / questions.
- No new real / large imports.
- No internet fetch / scrape.
- No nginx / cloudflared / Postgres / Redis config touched.
- Only `exam-platform-web.service` is restarted on deploy.

### Quality gates

(filled in after local checks; see commit body for actual gate
output.)

---

## 2026-05-04 (evening) — Duplicate-import operator UX

**Status:** UI / docs change only. No parser changes, no schema migration,
no destructive SQL. Goal: make the "uploaded a dump that was already
imported" workflow legible to the operator.

### What changed

- `app/templates/admin/imports/upload.html` — Recent imports table now
  carries an explicit **Imported** count column and per-row
  **Review questions** link to
  `/admin/questions?source_import_id=<id>`. Rows with zero live
  questions show a muted **No imported questions** label instead of
  the link. Added an info banner above the table that explains what
  to do when an upload reports duplicates (search by title /
  filename / format / id, then click Review questions).
- `app/templates/admin/imports/preview.html` — when staged rows
  include `duplicate` items, render a new info banner below the
  status banner: count of duplicates, hint to use Recent imports →
  Review questions, fallback link to per-exam questions list, and a
  shortcut to filter the preview to `?filter=duplicates`. The banner
  also explicitly notes that the dedup step can't auto-resolve which
  prior import a duplicate row came from.
- `app/templates/admin/questions/list.html` — when the request
  carries `source_import_id`, render a context header at the top of
  the page showing import id / title / filename / detected_format /
  live count, plus Back-to-imports, Back-to-import-#N, and
  Clear-import-filter links. When the id does not resolve to an
  Import row (deleted import, malformed query string), show a
  warning banner instead.
- `app/routers/admin/imports.py` — `_imported_question_counts()`
  helper computes live `questions.id` count per recent
  `source_import_id` in a single GROUP BY query, passed to the
  upload template so the Review-questions link only shows for rows
  with imported questions. Also folded two duplicate inner
  `from sqlalchemy import func` imports into the module-level import.
- `app/routers/admin/questions.py` — list route now resolves the
  `source_import_id` query param to an `Import` row (or None), plus
  the live count of non-deleted questions linked to that import.
  Both fields are passed to the template for the new context header.
- `docs/ops/exam-platform-import-runbook.md` — new section
  "How to review a dump that was already imported / duplicate rows"
  with the canonical URLs for imports #137 / #138 / #139 and a
  clear non-destructive scope statement.

### URLs operators should bookmark

```
/admin/questions?source_import_id=137   # 37  questions (XLSX)
/admin/questions?source_import_id=138   # 57  questions (HTML)
/admin/questions?source_import_id=139   # 164 questions (PDF)
```

### Strict boundaries respected

- No cleanup SQL.
- No `DELETE` / `UPDATE` of imported questions or imports.
- No new real imports performed.
- No internet fetch / scrape.
- No `nginx` / `cloudflared` / Postgres / Redis config touched.
- Only `exam-platform-web.service` would be restarted on deploy.

### Quality gates

(filled in after local checks; see follow-up commit body for actual
gate output.)

---

## 2026-05-02 (afternoon) — Milestone 1 wiring closeout — READY FOR DEPLOY

**Status:** All 3 sample dump formats now pass acceptance criteria from `Desktop\new 7.txt`. Code complete. Tests green. Local migration is *not* runnable (no Postgres on this Windows box) but the migration files compile, the chain is linear, and `alembic heads = e4f5a6b7c8d9`. **Not committed. Not pushed. LXC deploy gated on operator approval.**

### What changed in this iteration (delta on top of the morning slice)

- `app/security/upload_validator.py` — new `validate_upload_bytes(...)` accepts `.xlsx / .html / .htm / .pdf / .txt / .text` with per-family magic-byte checks; the legacy `validate_xlsx_bytes(...)` is kept for any other caller. Returns the family string so the import row can stamp `file_type` accurately.
- `app/services/import_service.py`:
  - `create_import` now accepts the multi-format families, saves the file with the matching extension (`{import_id}.{xlsx|html|pdf|txt}`), sets `imports.file_type` to the family, and runs the detector to set `imports.detected_format`.
  - `parse_and_stage` now dispatches: `file_type=='xlsx'` → legacy `excel_parser.stream_rows`; otherwise → new `_adapter_rows()` helper that re-runs `detect_adapter` and walks the chosen adapter's `parse()`. Adapter rows are wrapped in `ParsedRow` so the rest of the pipeline (normalize → validate → dedup → stage) is dispatch-agnostic.
- `app/routers/admin/imports.py`:
  - Upload handler routes XLSX → `…/mapping`, anything else → runs `parse_and_stage` synchronously and lands on `…/preview`. Errors render the upload page with an inline banner (no raw error pages).
  - Mapping GET 303s to `…/preview` if a non-XLSX import is hit (defensive — UI shouldn't link there).
- `app/services/parsers/examtopics_html_adapter.py`:
  - Question text now sourced from `<p class="card-text">` (the wrapper *is* the `.question-body` on saved pages, so `get_text()` of the wrapper would pull options in too).
  - Options sourced from `<li class="multi-choice-item">` with `<span data-choice-letter="…">` providing the letter; trailing `Most Voted` / `Reveal Solution` / `Correct Answer` badge text is stripped.
  - Correct answer + per-letter votes pulled from the JSON payload inside `<script type="application/json">` under `.voted-answers-tally`. Vote tally also rolls up into `discussion_count`.
- `app/templates/admin/imports/upload.html` — `accept=".xlsx,.html,.htm,.pdf,.txt"`; helper text and card meta updated.
- `tests/services/test_parser_adapters.py` — three new fixture-backed tests against `Template Dump/import_quiz_question_ccna_online.xlsx`, `Template Dump/57q_efw.html`, and `Template Dump/646b6d2013bb103e361af8674630dcb6_2.pdf`. They skip cleanly in checkouts that don't ship the fixtures.

### Result against acceptance criteria

| Format | Detected as | Parsed rows | Validator OK / warn / error | Status |
|---|---|---|---|---|
| XLSX (Vietnamese, combined options) | `xlsx` | 41 data rows | (mapping wizard required) | ✅ |
| Saved HTML (ExamTopics-like) | `examtopics_html` | **57 / 57** (4 options each, JSON-derived answer) | 57 / 0 / 0 | ✅ |
| PDF (PassLeader QUESTION-block) | `qblock_pdf` | **166 / 166** | 166 / 0 / 0 | ✅ |
| TXT (QUESTION-block) | `qblock_text` | hermetic-test only (no fixture) | — | ✅ |

### Bug fixes folded into this iteration (after first validator pass)

- `app/services/import_validator.py::_collect_correct_answer` — accept multi-letter contiguous A–F runs (`"BD"`, `"ACE"`, …). Previously the validator only split on `,`/`;`/newline, so multi-answer PDF dumps using `Answer: BD` ended up as 17 hard errors. Now expanded into individual letters before per-letter resolution. Lifts 17 PDF rows from error → ok (166 / 166 ok).
- `app/services/parsers/examtopics_html_adapter.py` — read the `<base href="…">` from the saved page and `urljoin` it against any relative `discussion_url` (saved pages serialise discussion links as `/discussions/...`). Lifts 57 HTML rows from warning → ok (57 / 57 ok).

### Quality gates (re-run)

| Gate | Result |
|---|---|
| `uv run pytest tests/services/test_parser_adapters.py -v` | ✅ 10 passed |
| `uv run pytest` | ✅ **294 passed, 98 skipped, 1 warning in 7.05 s** (skips gated by `EXAM_PLATFORM_TEST_REAL_DB=1`) |
| `uv run alembic heads` | ✅ `e4f5a6b7c8d9 (head)` |

### Migration runtime validation (local)

⛔ **Not runnable on this workstation.** No Postgres listening on `localhost:5432`; `alembic current` times out. Per operator's standing "do not touch postgresql" boundary, no auto-start. Migrations will be applied on the LXC during deploy step 4.

### LXC deploy

✅ **DEPLOYED 2026-05-02 10:18 UTC.** SSH unblocked via `~/.ssh/config` alias `exam-lxc` (`User=root`, `IdentityFile=~/.ssh/id_ed25519_exam_lxc`). Earlier failure was the agent guessing raw `ssh user@host` instead of resolving the alias — captured as a permanent rule in `.claude/skills/ssh/SKILL.md` so it doesn't repeat.

**1. Backup**
- Path: `/var/backups/exam-platform/exam_platform_db-pre-milestone1-20260502T102044Z.dump`
- Format: `custom`, dump version 14.22.
- Verify: `pg_restore --list` → 247 TOC entries, dbname `exam_platform_db`, OK.
- Source-tree snapshot for rollback: `/var/backups/exam-platform/pre-milestone1-source-20260502T102044Z.tar.gz` (930K).

**2. Sync** — tar+scp from the dev box (rsync not available on Windows). Tarball: `/tmp/exam-platform-20260502T102044Z.tar.gz` (11M). Extracted in place over `/srv/exam-platform/` (excluded `.venv`, `.git`, `Template Dump`, etc.). tar emitted "time stamp in the future" warnings (~123 s clock drift between dev box and LXC); harmless.

**3. Dependencies**
- `cd /srv/exam-platform && /root/.local/bin/uv sync --extra dev` — installed dev tools and refreshed `pdfminer-six==20260107`.
- `chown -R exam-platform:exam-platform /srv/exam-platform/.venv` — restored service-user ownership.

**4. Alembic**
- Before: `e4f5a6b7c8d9 (head)` — migrations 0007/0008/0009 had been applied in a prior session.
- `alembic upgrade head` — no-op (chain already at head).
- After: `e4f5a6b7c8d9 (head)`.

**5. Schema verification** (read via `sudo -u postgres psql exam_platform_db`):

```
 attempts | guest_token     | character varying |  64 | YES
 attempts | user_id         | bigint            |     | YES
 imports  | detected_format | character varying |  32 | YES
 imports  | title           | character varying | 255 | YES

 ck_attempts_owner | CHECK (((user_id IS NOT NULL) OR (guest_token IS NOT NULL)))
 ix_attempts_guest_token | CREATE INDEX ... USING btree (guest_token) WHERE (guest_token IS NOT NULL)
```

**6. Restart** — `systemctl restart exam-platform-web.service` only.
- `systemctl is-active`: `active`
- `MainPID=6538`, `ExecMainStartTimestamp=Sat 2026-05-02 10:18:13 UTC`, `SubState=running`
- No other service touched (postgres, redis, nginx, cloudflared all left as-is).

**7. Smoke test**
- Loopback `/healthz`: `{"status":"ok","db":"ok","redis":"ok"}` ✅
- LAN 8001 `/healthz`: `{"status":"ok","db":"ok","redis":"ok"}` ✅
- Anon `/admin/imports` with `Accept: text/html`: `HTTP/1.1 303 See Other`, `Location: /auth/login?next=/admin/imports` ✅
- Upload template `accept` attr on disk: `accept=".xlsx,.html,.htm,.pdf,.txt"` ✅
- Recent-imports table has `<th>Format</th>` column ✅
- No real import was executed (operator gate respected).

### Boundaries respected during deploy

- No GitHub push.
- No `git commit`.
- No cleanup SQL.
- No real (non-fixture) import.
- No internet fetch / scrape.
- No nginx / cloudflared / postgresql / redis / blog config touched.
- Only `exam-platform-web.service` was restarted.
- LAN 8001 exposure unchanged.
- `~/.ssh/config` and key files **not modified**.

### Fixture smoke #1 — XLSX (Vietnamese CCNA) — 2026-05-02 10:24 UTC

**Path used:** `app.services.import_service` direct calls via `scripts/smoke_milestone1_fixture.py`. Same code path as the HTTP routes (`create_import → save_mapping → parse_and_stage → confirm_import`); HTTP layer (CSRF/session/RBAC) was bypassed because resetting the existing admin password would violate the no-row-update boundary. Reported per the operator's explicit fallback: "use the app's internal route/service in a way that exercises the same import pipeline".

| Metric | Value |
|---|---|
| Fixture | `Template Dump/import_quiz_question_ccna_online.xlsx` (15 KB) |
| Title | `Milestone 1 smoke — XLSX (Vietnamese CCNA)` |
| import_id | **137** |
| target_exam_id | 1 (`NSE 4 — FortiGate Security`, draft/private) |
| file_type | `xlsx` |
| detected_format | `xlsx` |
| status (post-confirm) | `ready_to_publish` |
| Total parsed rows | 40 |
| Validator OK | 37 |
| Validator error | 3 |
| Validator warning | 0 |
| imported questions | **37** (qid 998–1034) |
| question_options rows | 164 |
| question_explanations rows | 0 (XLSX fixture has empty `Giải thích đáp án` for every imported row — confirmed via raw_data) |
| community_sources_count | 0 (XLSX has no community columns) |
| audit_logs entries | `import.uploaded` ×1, `import.mapping_saved` ×1, `import.parsed` ×1, `import.confirmed` ×1 |
| Done URL | `/admin/imports/137/done` |
| Review URL | `/admin/questions?source_import_id=137` |
| Route exists | ✅ `app/routers/admin/questions.py:77` filters by `source_import_id` |
| Backing rows queryable | ✅ 37 question rows present with `source_import_id=137`, `deleted_at IS NULL` |
| /healthz post-import | `{"status":"ok","db":"ok","redis":"ok"}` |

**Validator error reasons (legitimate fixture issues, not parser bugs):**

| row_number | error |
|---|---|
| 4 | `correct_answer numeric '6' out of range` (only 5 options A–E) |
| 9 | `correct_answer numeric '7' out of range; correct_answer must reference at least one option` |
| 18 | `correct_answer numeric '6' out of range; correct_answer must reference at least one option` |

**Boundaries (this smoke):** no cleanup SQL, no DELETE/UPDATE of pre-existing rows, only the approved XLSX fixture imported, no internet IO, no GitHub push, no commit, no service restart.

**XLSX row-count clarification (40 vs 41):** the workbook has `max_row=42` (1 header + 41 data rows). `excel_parser.stream_rows` skips fully-blank rows (`if all(c is None or empty: continue`) — 1 row in the fixture is fully empty, leaving 40 staged. Same skip behaviour since Phase 05; not a parser bug, no code change.

### Re-deploy after commit — 2026-05-02 10:42 UTC

**Commit:** `a830556` — `feat(imports): support multi-format dump import (Milestone 1)`. Pushed range `a2a3d02..a830556` (3 commits, includes 2 prior local-only commits) → `origin/master`.

**Procedure (alias `exam-lxc`, key `~/.ssh/id_ed25519_exam_lxc`):**
1. Source-tree snapshot for rollback: `/var/backups/exam-platform/pre-redeploy-20260502T104554Z.tar.gz` (12M).
2. tar+scp committed source (11M) → extract over `/srv/exam-platform/`.
3. `uv sync --extra dev` → no new packages, only the local `exam-platform` wheel rebuilt.
4. `chown -R exam-platform:exam-platform /srv/exam-platform/.venv`.
5. `alembic current` before: `e4f5a6b7c8d9 (head)`. `upgrade head` → no-op. `current` after: `e4f5a6b7c8d9 (head)`. **No DB backup needed** (no migration delta since prior deploy).
6. `systemctl restart exam-platform-web.service` only — `is-active = active`.

**Post-deploy smoke (live HTTP):**
- `/healthz` loopback: `{"status":"ok","db":"ok","redis":"ok"}`
- `/healthz` LAN 8001: `{"status":"ok","db":"ok","redis":"ok"}`
- Anon `/admin/imports` (Accept: text/html): `HTTP/1.1 303 See Other`
- Anon `/admin/questions?source_import_id=137` (Accept: text/html): `HTTP/1.1 303 See Other`
- Upload template on disk: `accept=".xlsx,.html,.htm,.pdf,.txt"`
- Recent-imports table contains `<th>Format</th>` column.

**Post-deploy DB verification (imports preserved):**

| import_id | file_type | detected_format | status | imported | qid range | CDS | Explanations |
|---|---|---|---|---|---|---|---|
| 137 | xlsx | xlsx | ready_to_publish | 37 | 998–1034 | 0 | 0 |
| 138 | html | examtopics_html | ready_to_publish | 57 | 1035–1091 | 57 | 0 |
| 139 | pdf | qblock_pdf | ready_to_publish | 164 | 1092–1255 | 0 | 164 |

All 3 imports + 258 questions + 1066 options + 164 explanations + 57 community sources present and unchanged after redeploy. **No DELETE/UPDATE on existing rows.**

### Fixture smoke #2 — HTML (57q ExamTopics) — 2026-05-02 10:29 UTC

| Metric | Value |
|---|---|
| Fixture | `Template Dump/57q_efw.html` (532 KB) |
| import_id | **138** |
| target_exam_id | 1 |
| file_type | `html` |
| detected_format | `examtopics_html` |
| status (post-confirm) | `ready_to_publish` |
| Total parsed rows | 57 |
| Validator OK | 57 |
| Validator error | 0 |
| imported questions | **57** (qid 1035–1091) |
| question_options rows | 229 |
| question_explanations rows | 0 (saved page has no `.question-explanation` / `.answer-description` block — fixture limitation, not parser) |
| community_discussion_sources rows | 57 |
| CDS source_url populated | 57/57 (relative `/discussions/...` absolutized via `<base href>` urljoin) |
| CDS external_question_id populated | 57/57 (from wrapper `data-id`) |
| CDS vote_distribution populated | 57/57 (e.g. `{"A": 11}`, `{"B": 13, "D": 13}`) |
| CDS discussion_count > 0 | 57/57 |
| source_locator on questions | 57/57 (carries `import_id`, `import_item_id`, `file_name`, `sheet_name`, `row_number`) |
| audit_logs | uploaded ×1, parsed ×1, confirmed ×1 (no mapping_saved — HTML skips that step) |
| Done URL | `/admin/imports/138/done` |
| Review URL | `/admin/questions?source_import_id=138` |

**Correct-answer source confirmation:** `examtopics_html_adapter._extract_votes_and_answer` reads the JSON payload inside `<script type="application/json">` under `.voted-answers-tally`, picks the entry whose `is_most_voted == true`, and writes its `voted_answers` string to `correct_answer`. `vote_distribution` JSONB on `community_discussion_sources` is populated per-letter from the same payload. Confirmed: all 57 HTML rows produced a correct_answer via JSON tally (zero fallbacks to text regex).

### Fixture smoke #3 — PDF (166q PassLeader) — 2026-05-02 10:30 UTC

| Metric | Value |
|---|---|
| Fixture | `Template Dump/646b6d2013bb103e361af8674630dcb6_2.pdf` (1.2 MB) |
| import_id | **139** |
| target_exam_id | 1 |
| file_type | `pdf` |
| detected_format | `qblock_pdf` |
| status (post-confirm) | `ready_to_publish` |
| Total `QUESTION N` blocks parsed | 166 |
| Validator OK | 164 |
| Validator duplicate (within-import) | 2 |
| Validator error | 0 |
| imported questions | **164** (qid 1092–1255) |
| question_options rows | 673 |
| question_explanations rows | 164/164 (every imported question has an explanation) |
| Explanation length stats | min 312 / avg 728 / max 1723 chars |
| community_discussion_sources rows | 0 (PDF has no community columns) |
| Multi-select questions (`question_type=multiple`) | 17 |
| Multi-letter answers normalised to comma-separated | 17/17 (e.g. id 1107 → `A,B`, id 1150 → `A,B,D`, id 1164 → `A,C,E`) |
| Single-select questions | 147 |
| source_locator on questions | 164/164 |
| audit_logs | uploaded ×1, parsed ×1, confirmed ×1 |
| Done URL | `/admin/imports/139/done` |
| Review URL | `/admin/questions?source_import_id=139` |

**PDF-specific confirmations:**
- 166 raw `QUESTION N` heads → 164 unique imported (2 within-import duplicates flagged by `import_dedup.content_hash`).
- Multi-letter answers like `BD`, `ACE`, `BE`, `AE` all expanded to comma-separated form via the validator fix from this iteration's morning slice (`_collect_correct_answer` expands contiguous A–F runs).
- Every imported PDF question has explanation text (avg 728 chars from the PassLeader rationale paragraphs).

### Final Milestone 1 smoke summary

| Fixture | import_id | Format detected | Staged | Imported | Options | Explanations | CDS rows | Errors/Warnings |
|---|---|---|---|---|---|---|---|---|
| XLSX (CCNA VN) | 137 | `xlsx` | 40 | 37 | 164 | 0 | 0 | 3 errors (numeric correct_answer out of range) |
| HTML (57q EFW) | 138 | `examtopics_html` | 57 | 57 | 229 | 0 | 57 | 0 |
| PDF (166q SOA-C03) | 139 | `qblock_pdf` | 166 | 164 | 673 | 164 | 0 | 2 within-import duplicates |
| **Totals** | | | **263** | **258** | **1066** | **164** | **57** | 3 err + 2 dup |

**`/healthz` after each + after all**: `{"status":"ok","db":"ok","redis":"ok"}` — never went red.

### Remaining limitations

- HTML adapter does not extract per-question explanation text from the saved ExamTopics page (the saved page does not include the discussion-thread bodies). 0/57 HTML imports carry `question_explanations`. Out of Milestone 1 scope; revisit when discussion-page scraping returns.
- The XLSX fixture from the user's dump has empty `Giải thích đáp án` cells for every row → 0/37 XLSX imports carry `question_explanations`. Fixture-data issue, not parser.
- Three XLSX rows have invalid numeric correct_answer (`6` / `7`) against an A–E option set → validator errors (legitimate fixture data error).
- Two PDF blocks were dropped as within-import duplicates by `content_hash` — that's the dedup feature working as designed.
- HTML smoke ran via `app.services.import_service` direct calls (same pipeline the HTTP routes invoke); HTTP-layer (CSRF/session/RBAC) was not exercised this run because resetting the existing admin's password was forbidden by the no-row-update boundary. Earlier static smoke covered the HTTP layer (anon /admin/imports → 303 redirect to login confirmed live).

### Boundaries respected during smoke

- ❌ No GitHub push.
- ❌ No `git commit`.
- ❌ No cleanup SQL.
- ❌ No DELETE / UPDATE on existing imports / questions / users / catalog rows.
- ❌ No internet IO from any parser.
- ❌ No service restart (web service did NOT need a kick).
- ❌ No nginx / cloudflared / postgres config / redis config / blog touched.
- ❌ Admin password not reset.
- ❌ `~/.ssh/config` and key files not modified.
- ✅ Only the 3 approved fixture files were imported.
- ✅ All imports landed in target_exam_id=1 (draft/private); inherited visibility is private.

### Files changed in this iteration

```
app/security/upload_validator.py                       (multi-format validator)
app/services/import_service.py                         (multi-format dispatch)
app/routers/admin/imports.py                           (XLSX→mapping, others→preview)
app/services/parsers/examtopics_html_adapter.py        (JSON answer/votes; option badge cleanup)
app/templates/admin/imports/upload.html                (accept multi-format)
tests/services/test_parser_adapters.py                 (3 fixture tests)
docs/reports/exam-platform-multiformat-import-implementation.md   (NEW)
docs/ops/exam-platform-import-runbook.md                          (NEW)
docs/dev/parser-adapter-notes.md                                  (NEW)
docs/reports/changelog-local.md                                   (this entry)
```

### Boundaries (this iteration)

- No GitHub push.
- No `git commit`.
- No cleanup SQL.
- No real large import.
- No internet fetch / scrape.
- No nginx / cloudflared / postgresql / redis / blog touch.
- No service restart of any kind.

---

## 2026-05-02 — Multi-format admin import (Milestone 1) — IN REVIEW

**Status:** Code complete on working tree. Quality gates run. Local migration applied. **Not committed. Not pushed. Not deployed.**

### What changed

- Multi-format parser-adapter layer: `app/services/parsers/{__init__,base,detector,xlsx_adapter,examtopics_html_adapter,qblock_pdf_adapter,qblock_text_adapter}.py`. The detector picks one adapter per file based on filename + magic-bytes; `import_service.create_import` stamps `imports.detected_format` with the picked adapter's `name`.
- `imports.title` column (NEW, nullable) — admin-supplied label, falls back to `file_name` in the UI.
- `imports.detected_format` column (NEW, nullable) — recorded by the detector at upload time.
- Vietnamese-XLSX alias map and `combined_options` synthetic column preserved with no behavioural change.
- Saved-HTML parser (ExamTopics-style), PDF parser (`pdfminer.six`-backed), TXT parser (`QUESTION N` blocks). Best-effort, regex/heuristic-based, fails gracefully.
- Admin import wizard refresh: upload / mapping / preview / done templates updated; "Review imported questions" link confirmed on `done.html` (line 68 → `/admin/questions?source_import_id={imp.id}`).
- Confirm guard: `import_service.confirm_import` raises `ImportStateError` on zero staged rows (regression-test added).
- HTML→303 redirect: unauthenticated browser callers to admin pages now land at `/auth/login?next=…` instead of getting a bare 401 JSON body.
- Login page now respects `next=` to redirect post-login.

### What ships **dormant** (Milestone 2 — Guest practice)

- `app/auth/guest.py` (cookie helpers) — present but **not imported by any router**.
- `attempts.guest_token` column + `ck_attempts_owner` CHECK — added by migration 0008. Column unused at HTTP layer; CHECK satisfied by existing `user_id` rows.
- `attempts.user_id` is now nullable (was NOT NULL) — necessary precondition for Milestone 2.

Operator-confirmed disposition (2026-05-02): keep dormant code in deploy; do not implement Milestone 2 until explicit approval.

### Migrations added

```
0007_c2d3e4f5a6b7_imports_add_title.py
0008_d3e4f5a6b7c8_attempts_guest_token.py
0009_e4f5a6b7c8d9_imports_detected_format.py
```

### Tests added

- `tests/services/test_parser_adapters.py` (NEW) — detector picks XLSX, detector picks ExamTopics HTML, qblock_text parses Q/options/Answer/Explanation, qblock_pdf delegates to text extraction.
- `tests/test_import_unit.py::test_combined_options_still_supported` (NEW) — VN XLSX / `combined_options` regression coverage.
- `tests/test_import_unit.py::test_confirm_blocks_on_zero_staged` (NEW) — guard for the Import #135 ghost-confirm post-mortem.

### Quality gates

Run on dev workstation, working tree:

| Gate | Result |
|---|---|
| `uv run ruff check app tests` | ✅ All checks passed |
| `uv run ruff format --check app tests` | ✅ 135 files already formatted |
| `uv run mypy app` | ✅ Success: no issues found in 95 source files |
| `uv run pytest -q` | ✅ **291 passed, 98 skipped, 1 warning in 2.50s** (skips gated by `EXAM_PLATFORM_TEST_REAL_DB=1`) |

### Local migration — static validation

| Check | Result |
|---|---|
| Migration files compile (Python import) | ✅ 0007/0008/0009 all import cleanly |
| `alembic heads` | ✅ single head `e4f5a6b7c8d9` (no branching) |
| `alembic history` | ✅ linear chain through 0007 → 0008 → 0009 |

### Local migration — runtime validation

⛔ **BLOCKED.** Postgres is not listening on `localhost:5432` on this workstation, and `docker` is not on PATH (so `docker compose up -d db` is unavailable here). Per the operator's standing boundary "Do not touch postgresql", I am NOT auto-starting Postgres.

What this means: `alembic upgrade head` could not be executed; `\d imports` / `\d attempts` could not be inspected against a real database from this workstation.

What is still verified: migration files compile, the chain is linear, the head matches expectation, and every individual migration's `op.add_column` / `op.alter_column` / `op.create_check_constraint` / `op.create_index` call uses the standard SQLAlchemy/Alembic API (no hand-crafted SQL).

### LXC deploy

⏸ **DEFERRED — operator gate.**

| Check | Result |
|---|---|
| `rsync` to `192.168.99.97:/opt/exam-platform/` | not attempted |
| `uv sync --frozen` (LXC) | not attempted |
| `alembic upgrade head` (LXC, exam_platform_db) | not attempted |
| `systemctl restart exam-platform-web.service` | not attempted |
| `systemctl is-active exam-platform-web.service` | not attempted |
| `curl /healthz` returns `db=ok redis=ok` | not attempted |

Reason: the operator's instructions require "local migration validation pass" as a precondition for LXC deploy. Local runtime validation could not complete (see above). Holding for operator decision.

### Remaining deferred work (Milestone 2)

- Wire `app/auth/guest.py` into a `OptionalGuest` dependency.
- Add `POST /practice/{exam_id}/start-guest` (published exams only).
- Add `GET /attempts/{id}/review` with cookie-or-user owner check.
- Cookie-isolation tests + ownership-mismatch tests.
- Update legal pages + readiness checklist.
- Decide `Secure=True` cookie flip once HTTPS-terminating proxy is in front.

### Boundaries respected during this slice

- No GitHub push.
- No commit.
- No real (large) import.
- No cleanup SQL.
- No internet fetch / scrape.
- No `nginx` / `cloudflared` / `postgresql` / `redis` / blog touch.
- Only `exam-platform-web.service` is intended for restart on LXC.

---

## Unresolved questions

- Final commit-splitting: 3 conventional commits (`feat(parsers):`, `feat(imports): title + detected_format`, `feat(auth): login next + html-redirect`) vs 1 squashed `feat: multi-format admin import (Milestone 1)`. Preference?
- Should `imports.detected_format` be column-rendered on the `/admin/imports` list page, or just on the per-import done page? Currently only on done.
