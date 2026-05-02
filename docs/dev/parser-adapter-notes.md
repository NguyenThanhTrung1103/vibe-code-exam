# Parser-Adapter Notes (Milestone 1)

## Why an adapter layer

The Phase 05 importer was XLSX-only — `excel_parser.stream_rows` was the single
row source for `import_service.parse_and_stage`. Milestone 1 needed three more
formats (saved HTML, PDF, TXT) without rewriting normalize / validate / dedup
or the `import_items` staging table.

The adapter layer lives in `app/services/parsers/`. Each adapter is a small
module that:

1. Decides whether it can claim a file (`detect()` — filename + first 4 KB).
2. Yields canonical-row dicts with the same keys the rest of the pipeline
   already understands (`question_text`, `option_a..option_f`,
   `correct_answer`, `explanation`, `external_question_id`, `discussion_url`,
   `discussion_count`, `vote_a..vote_f`, plus source-locator fields).

`detect_adapter(filename, file_path)` walks the registry sorted by priority
(highest first) and returns the first one that claims the file. The chosen
adapter's `name` is persisted on `imports.detected_format` for UI display
and any downstream policy lookup.

## Registry

```
xlsx              priority 80    .xlsx + zip magic
examtopics_html   priority 70    .html/.htm + ExamTopics markers in head
qblock_pdf        priority 60    .pdf + %PDF- magic
qblock_text       priority 50    .txt/.text + a "QUESTION N" head match
```

Higher priority = tried first. Order matters when a file could match
multiple adapters (e.g. an HTML page that happens to contain a `QUESTION 1`
literal — `examtopics_html` claims it via filename extension before
`qblock_text` is even consulted).

## Canonical row shape

Every adapter must yield a `dict` with at least:

* `question_text: str` (required, ≤ 4000 chars after normalize)
* `option_a, option_b: str` (≥ 2 options required by the validator)
* `correct_answer: str` (single letter `A`–`F`, numeric `1`–`6`, or
  verbatim option text — all three are recognised by `import_validator`)

Optional but commonly carried:

* `option_c, option_d, option_e, option_f`
* `explanation`, `reference`, `tags`
* `external_question_id`, `discussion_url`, `discussion_count`
* `vote_a..vote_f` (per-letter community vote counts, ints)
* `source_format`, `source_url`, `source_page`, `raw_source_ref`
  — passthrough metadata for the future enrichment layer.

The XLSX adapter still goes through `column_mapping` because admins want a
visual mapping page (Vietnamese vs English vs custom dump headers vary).
Non-XLSX adapters bypass mapping; they emit canonical keys directly.

## How the wizard dispatches

`import_service.create_import` sets `imports.file_type` to one of `xlsx`,
`html`, `pdf`, `txt` (the *family* — what was uploaded) and runs the detector
to set `imports.detected_format` to the *adapter name* — these can differ
when a file's extension matches one family but the bytes match another
adapter's signature.

`parse_and_stage`:

* `file_type == "xlsx"` (or `detected_format == "xlsx"`) → legacy
  `excel_parser.stream_rows` path. Requires `column_mapping`.
* anything else → `_adapter_rows()` re-runs `detect_adapter` and walks
  the chosen adapter's `parse()` output. No `column_mapping` needed.

The router (`app/routers/admin/imports.py`) routes the upload step:

* XLSX → `…/mapping`
* anything else → `parse_and_stage` runs synchronously inside the upload
  handler, then redirects to `…/preview`.

## Adapter-specific notes

### `xlsx_adapter.py`

Wraps `excel_parser.stream_rows`. Source-locator fields are filled in from
the file path and the row number so non-XLSX uploads have parity.

### `examtopics_html_adapter.py`

* Question text comes from `<p class="card-text">` (the `.question-body`
  wrapper would pull in option text via `get_text()`).
* Option text comes from `<li class="multi-choice-item">` with
  `<span data-choice-letter="A">` providing the label and the surrounding
  text providing the body. The leading `A.` and trailing `Most Voted` /
  `Reveal Solution` / `Correct Answer` badge text are stripped with the
  `_OPTION_BADGE_NOISE_RE` regex.
* Correct answer + per-letter votes are pulled out of the JSON payload
  inside `<script type="application/json">` under `.voted-answers-tally`,
  e.g.:

  ```json
  [{"voted_answers": "A", "vote_count": 11, "is_most_voted": true}]
  ```

  Multi-letter `voted_answers` strings (e.g. `AC`) split per letter so each
  contributes to the per-letter tally; `is_most_voted` selects the
  `correct_answer`.
* `external_question_id = block.get("data-id")`. Total vote count goes to
  `discussion_count`.

### `qblock_pdf_adapter.py` + `qblock_text_adapter.py`

* The text adapter is the source of truth — `qblock_pdf` just
  `pdfminer.high_level.extract_text(...)` then delegates.
* Splits text on `^QUESTION N` lines (case-insensitive). Inside a block:
  * Question lines accumulate until the first `^[A-F][.):-]` option line.
  * Option lines populate `option_a..option_f`. Subsequent non-option,
    non-`Answer:`, non-`Explanation:` lines are appended to the last-seen
    option (handles wrapped option text).
  * `Answer: X` (or `Reason:` / `Rationale:`) flips state to
    `answer`/`explanation`.
  * Lines that look like page numbers (`^\d{1,4}$`) are dropped.
* Blocks with zero options are silently skipped — best-effort, no crash.

## Adding a new adapter

1. Create `app/services/parsers/my_adapter.py` with a class that has
   `name`, `priority`, `detect()`, `parse()`. `parse()` yields canonical
   row dicts.
2. Register in `app/services/parsers/detector.py` `_REGISTRY`.
3. Add tests to `tests/services/test_parser_adapters.py` — both a hermetic
   test and (ideally) a fixture-backed one if sample files exist.
4. If your adapter family needs a new file extension, extend
   `app.security.upload_validator.ALLOWED_EXTS_MULTIFORMAT` and the
   `validate_upload_bytes` magic-byte branch.
5. Update `app/templates/admin/imports/upload.html` `accept=` and helper
   text.

## Boundaries

* No internet IO. `requests` / `httpx` calls are not allowed inside any
  adapter. The only network access in the import path is the database
  driver.
* No DRM bypass. PDFs marked "do not allow extraction" are decoded by
  pdfminer (which logs the metadata hint but proceeds for non-DRM PDFs);
  encrypted PDFs would still fail and we let them.
