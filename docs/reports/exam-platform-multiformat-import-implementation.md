# Multi-format Import — Milestone 1 Implementation Report

Date: 2026-05-02
Owner: local single-user app (LXC 192.168.99.97)
Scope: parser/import only — no guest-practice, no enrichment, no AI analyzer.

## Result

| Format | Detected as | Fixture | Parsed rows | Status |
|---|---|---|---|---|
| XLSX (Vietnamese, combined options) | `xlsx` | `Template Dump/import_quiz_question_ccna_online.xlsx` | 41 data rows | OK |
| Saved HTML (ExamTopics-like) | `examtopics_html` | `Template Dump/57q_efw.html` | 57 questions | OK |
| PDF (PassLeader QUESTION-block style) | `qblock_pdf` | `Template Dump/646b6d2013bb103e361af8674630dcb6_2.pdf` | 166 questions | OK |
| TXT (QUESTION-block) | `qblock_text` | n/a in fixtures — covered by hermetic test | — | OK |

All 3 sample dump files satisfy the acceptance criteria in `Desktop\new 7.txt`.

## Supported formats

The importer dispatches per the **first** parser-adapter (highest priority) whose
`detect()` claims the file via filename extension + first-4-KB magic bytes. The
adapter then yields canonical rows that flow into the same
normalize → validate → dedup → stage path used since Phase 05.

| Family | Adapter name | Priority | Detection signature |
|---|---|---|---|
| Excel workbook | `xlsx` | 80 | `.xlsx` extension + `PK\x03\x04` zip magic |
| Saved ExamTopics HTML | `examtopics_html` | 70 | `.html`/`.htm` + any of `question-body`, `voted-answers-tally`, `data-id=`, `discussion-count`, `examtopics`, `multi-choice-item` in head |
| PDF QUESTION-block dump | `qblock_pdf` | 60 | `.pdf` + `%PDF-` magic |
| TXT QUESTION-block dump | `qblock_text` | 50 | `.txt`/`.text` + a `QUESTION N` head match |

Detector picks adapter once at upload time and writes its name to
`imports.detected_format`. The admin UI surfaces it as a chip on the recent-imports
table.

## How each fixture is parsed

### XLSX — `import_quiz_question_ccna_online.xlsx`

* Header row: `Loại câu hỏi | Câu hỏi(Tiêu đề) * | Mô tả thêm | Tags … | Danh sách đáp án … * | Đáp án đúng … * | Giải thích đáp án`.
* `excel_parser._normalize_header` strips diacritics, folds `đ → d`, keeps alphanumerics.
* Substring match against the alias map resolves the long Vietnamese labels:
  * `Câu hỏi(Tiêu đề) *` → `cauhoi` substring → `question_text`
  * `Danh sách đáp án …` → `danhsachdapan` → `combined_options`
  * `Đáp án đúng …` → `dapandung` → `correct_answer`
  * `Giải thích đáp án` → `giaithichdapan` → `explanation`
  * `Loại câu hỏi` → `loaicauhoi` → not aliased; admin can pick `question_type` manually
* `combined_options` is split at normalize time on `;` / `；` / newlines into `option_a..option_f`.
* Numeric correct answer (`1`) is resolved to letter `A` by the validator.

### Saved HTML — `57q_efw.html`

* `[data-id]` divs are walked (57 total).
* Question text comes from the inner `<p class="card-text">` (the wrapper is `.card-body.question-body` and `get_text()` of the wrapper would pull options in too).
* Options come from `<li class="multi-choice-item">` items. The leading
  `<span class="multi-choice-letter" data-choice-letter="A">A.</span>` and any
  trailing `Most Voted` / `Reveal Solution` / `Correct Answer` badge text are
  stripped.
* Correct answer + per-letter votes are pulled from the
  `<script type="application/json">` payload inside `.voted-answers-tally`
  (e.g. `[{"voted_answers":"A","vote_count":11,"is_most_voted":true}]`).
  Multi-letter `voted_answers` strings (e.g. `AC`) split per letter so each
  contributes to the per-letter tally.
* `external_question_id` = the wrapper's `data-id`; total vote count lands as
  `discussion_count`; explanation/discussion URL captured when present.

### PDF — `646b6d2013bb103e361af8674630dcb6_2.pdf`

* `pdfminer.six.high_level.extract_text(...)` provides the page text.
  PassLeader marks the file as "do not extract" — pdfminer logs the metadata
  hint and proceeds; we do **not** bypass any DRM.
* The text is fed through `parse_qblock_text(...)` (same function the `.txt`
  adapter uses) so behaviour is identical across delivery formats.
* Splitter recognises `^QUESTION N` lines, then collects question text /
  `A. … D.` options / `Answer: X` / `Explanation:` blocks. Continuation
  lines are appended to the last-seen option (handles long wrapped option
  text). Page-number-only lines (`^\d{1,4}$`) are discarded.

## Known limitations

* HTML parser assumes the `card-text` / `multi-choice-item` / `voted-answers-tally`
  shape. ExamTopics layout changes will need the adapter updated; we do **not**
  fall back to fetching the live page (no internet IO by design).
* PDF parser is pdfminer-only — scanned PDFs (image-only) yield nothing.
* QUESTION-block parser drops blocks with no parseable options (best-effort).
  The PDF fixture has 166/166 with options; some block-style PDFs may be lossy.
* Multi-letter answers like `BD` round-trip as a single string; the validator
  splits on `,`/`;`/newline so a TXT/PDF dump using `Answer: B, D` would be
  recognised but `Answer: BD` is treated as the literal label `BD` and rejected
  by the label whitelist. Out of scope for Milestone 1.
* No internet enrichment, no Ollama, no RQ/AI verification — explicitly deferred.
* Guest practice routes/templates exist in the codebase but the upload pipeline
  does not surface anything guest-related; admin import remains
  `RequireAdmin`-gated.

## Operator test steps

After deploy on the LXC:

```bash
# 1. service is up
systemctl is-active exam-platform-web.service                   # → active

# 2. healthz reports both backends green
curl -fsS http://192.168.99.97:8001/healthz
# → {"status":"ok","db":"ok","redis":"ok"}

# 3. anonymous /admin/imports redirects to login
curl -isS http://192.168.99.97:8001/admin/imports | head -1
# → HTTP/1.1 303 See Other  (Location: /auth/login...)

# 4. authenticated /admin/imports loads
curl -isS -b "$COOKIE" http://192.168.99.97:8001/admin/imports | head -1
# → HTTP/1.1 200 OK

# 5. upload each of the 3 sample dumps via the wizard:
#    - XLSX → mapping page → preview → confirm
#    - HTML → preview (no mapping page)            → confirm
#    - PDF  → preview (no mapping page)            → confirm
#    Verify Done page shows non-zero "imported" + a "Review imported questions" link.
```

## Rollback notes

The Milestone 1 deploy is additive:

* New columns are nullable (`imports.title`, `imports.detected_format`,
  `attempts.guest_token`).
* The `attempts.user_id NOT NULL → NULL` change is backed by a CHECK constraint
  (`ck_attempts_owner`) — existing rows satisfy it via their populated
  `user_id`.

To rollback:

```bash
# On the LXC
sudo systemctl stop exam-platform-web.service
sudo -u postgres pg_restore --clean --if-exists --dbname=exam_platform_db \
  /var/backups/exam-platform/<dump-from-step-1>.dump
sudo systemctl start exam-platform-web.service
```

Or, if only the migration needs reverting:

```bash
cd /opt/exam-platform
uv run alembic downgrade c2d3e4f5a6b7   # back to before guest_token + detected_format
sudo systemctl restart exam-platform-web.service
```

## Commands run

```bash
# Local Windows dev
uv run pytest tests/services/test_parser_adapters.py -v       # 10 passed
uv run pytest                                                 # 294 passed, 98 skipped
uv run alembic heads                                          # e4f5a6b7c8d9 (head)
```

## Deployment result

See `docs/reports/changelog-local.md` for the dated deployment log.
See `docs/ops/exam-platform-import-runbook.md` for the deploy runbook.

## Healthcheck

Captured during deploy; recorded in `changelog-local.md`.

## Files changed in this iteration

```
app/security/upload_validator.py             # add validate_upload_bytes (multi-format)
app/services/import_service.py               # multi-format create_import + parse_and_stage dispatch
app/routers/admin/imports.py                 # XLSX → mapping; HTML/PDF/TXT → straight to preview
app/services/parsers/examtopics_html_adapter.py  # JSON answer/votes; strip badge noise from options
app/templates/admin/imports/upload.html      # accept .xlsx/.html/.pdf/.txt
tests/services/test_parser_adapters.py       # add 3 fixture-based golden tests
```

(Adapters, detector, qblock parser, and migrations 0007–0009 already existed.)

## Migrations applied

* `0007_c2d3e4f5a6b7_imports_add_title.py` — `imports.title TEXT NULL`
* `0008_d3e4f5a6b7c8_attempts_guest_token.py` — `attempts.user_id` nullable + `attempts.guest_token` + `ck_attempts_owner`
* `0009_e4f5a6b7c8d9_imports_detected_format.py` — `imports.detected_format VARCHAR(32) NULL`

`alembic heads` → `e4f5a6b7c8d9`.

## Dependencies added

None — `pdfminer.six`, `beautifulsoup4`, `lxml` already in `pyproject.toml`.

## Tests added

* `tests/services/test_parser_adapters.py::test_fixture_xlsx_detects_and_parses_vietnamese_dump`
* `tests/services/test_parser_adapters.py::test_fixture_html_detects_and_parses_examtopics_dump`
* `tests/services/test_parser_adapters.py::test_fixture_pdf_detects_and_parses_qblock_dump`

## Acceptance check vs `Desktop\new 7.txt`

* **A. XLSX** — detected `xlsx`; auto_map covers question_text + correct_answer + combined_options; combined splits into option_a/b at normalize; numeric `1` → `A`; preview/confirm wired; Done page shows `Review imported questions` link (template `app/templates/admin/imports/done.html` already exposes `first_question_id`).
* **B. HTML** — detected `examtopics_html`; preview shows 57 parsed questions; options A/B/C/D parsed; correct answer parsed (was missing pre-Milestone-1, now extracted from JSON); confirm imports valid rows.
* **C. PDF** — detected `qblock_pdf`; preview shows 166 QUESTION blocks; options A/B/C/D parsed; Answer parsed; Explanation parsed; confirm imports valid rows.
* **D. Admin/security** — `/admin/imports` and all sub-routes use `RequireAdmin`; anonymous redirects to login; no public/draft visibility changes.
* **E. Reliability** — mapping/preview errors render the wizard with an inline error banner (no raw error page); zero-staged-rows confirm raises `ImportStateError` (handled by router); per-row errors are shown in preview.

## Confirmations

* No GitHub push.
* No commit (left for explicit user approval).
* No cleanup SQL.
* No internet fetch.
* No nginx/cloudflared/redis/postgresql config touched.
* No service other than `exam-platform-web.service` restarted.
* LAN 8001 exposure unchanged.

## Unresolved questions

* Should we expose the multi-letter `Answer: B, D` syntax in the qblock TXT/PDF
  parser (currently splits on `,`/`;`/newline at validator level — works for
  comma-separated, fails for "BD")? Out of scope for Milestone 1, flagging.
* The PDF fixture vendor metadata says "do not allow text extraction" but ships
  no actual DRM. We log the warning and proceed. Fine for local-only use; revisit
  if we ever import for a third-party.
