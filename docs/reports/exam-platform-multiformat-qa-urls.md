# Milestone 1 — Browser QA URL Handoff

Date: 2026-05-02 (post-deploy verification)
Audience: operator running QA on the LXC instance at `http://192.168.99.97:8001/`.

Prereq: log in as an admin (e.g. `admin@local.test`). All routes below are
`RequireAdmin`-gated; anonymous access redirects to
`/auth/login?next=…` (303) when the request advertises `Accept: text/html`,
or returns `401 application/json` with `WWW-Authenticate: Cookie` for API
callers.

## URL list and expectations

### 1. `/admin/imports/137/done`

* **Page:** Done step of the wizard for import #137.
* **Expected title chip:** `Milestone 1 smoke — XLSX (Vietnamese CCNA)`
* **Expected file name chip:** `fixture-xlsx.xlsx`
* **Expected detected_format chip:** `xlsx`
* **Expected counts panel:**
  * `imported = 37`
  * `error = 3` (rows 4 / 9 / 18 — `correct_answer` numeric out of range against an A–E option set)
  * `duplicate = 0`
* **Expected status pill:** `ready_to_publish`
* **Review imported questions link:** points to `/admin/questions?source_import_id=137` and is enabled (`first_question_id = 998`).

### 2. `/admin/questions?source_import_id=137`

* **Page:** Admin question list filtered by import.
* **Expected total rows on this filter:** **37**
* **Expected question_id range:** 998 – 1034
* **Expected target exam:** `id=1`, `NSE 4 — FortiGate Security` (draft / private).
* **Expected question_options per question:** mostly 4–5 (164 options total ÷ 37 rows ≈ 4.4).
* **Expected explanations:** 0 (the source XLSX cells in `Giải thích đáp án` are empty for every row — confirmed via `import_items.raw_data`).
* **Expected community sources:** none (XLSX has no community columns).

### 3. `/admin/imports/138/done`

* **Page:** Done step for import #138.
* **Expected title chip:** `Milestone 1 smoke - HTML 57q ExamTopics`
* **Expected file name chip:** `fixture-html.html`
* **Expected detected_format chip:** `examtopics_html`
* **Expected counts panel:**
  * `imported = 57`
  * `error = 0`
  * `duplicate = 0`
* **Expected status pill:** `ready_to_publish`
* **Review imported questions link:** `/admin/questions?source_import_id=138` (enabled, `first_question_id = 1035`).

### 4. `/admin/questions?source_import_id=138`

* **Expected total rows:** **57**
* **Expected question_id range:** 1035 – 1091
* **Expected options per question:** 4 (229 options total ÷ 57 ≈ 4.0).
* **Expected explanations:** 0 (saved ExamTopics page does not include the discussion-thread bodies — adapter limitation, not a bug).
* **Expected community sources:** **57**, one per question — each row has `source_url` (absolutized via the saved page's `<base href>`), `external_question_id` (data-id), `vote_distribution` JSONB, and `discussion_count > 0`.
* **Correct-answer source:** JSON tally inside the saved page's `<script type="application/json">` under `.voted-answers-tally`.

### 5. `/admin/imports/139/done`

* **Page:** Done step for import #139.
* **Expected title chip:** `Milestone 1 smoke - PDF 166q PassLeader`
* **Expected file name chip:** `fixture-pdf.pdf`
* **Expected detected_format chip:** `qblock_pdf`
* **Expected counts panel:**
  * `imported = 164`
  * `duplicate = 2` (within-import duplicates flagged by `import_dedup.content_hash`)
  * `error = 0`
* **Expected status pill:** `ready_to_publish`
* **Review imported questions link:** `/admin/questions?source_import_id=139` (enabled, `first_question_id = 1092`).

### 6. `/admin/questions?source_import_id=139`

* **Expected total rows:** **164**
* **Expected question_id range:** 1092 – 1255
* **Expected options per question:** mostly 4–5 (673 options total ÷ 164 ≈ 4.1).
* **Expected explanations:** **164** (every imported question has explanation text; min 312 / avg 728 / max 1723 chars).
* **Expected community sources:** none (PDF has no community columns).
* **Multi-select questions:** 17 with `question_type=multiple` and comma-separated `given_answer` (e.g. `A,B`, `A,B,D`, `A,C,E`).
* **Single-select questions:** 147.

## QA pass/fail rubric

The QA run passes if, for every URL above:

1. The page renders without 5xx.
2. The detected_format chip matches the table.
3. The "Review imported questions" link is present and clicking it lands on a non-empty filter list.
4. Per-row counts match the totals listed.
5. For HTML #138: opening one community source row shows the absolutized `source_url` and the `vote_distribution` JSONB visible to admin tooling.
6. For PDF #139: opening one multi-select question shows ≥ 2 options flagged correct, matching the comma-separated `given_answer`.

## What QA should NOT touch

* No "Confirm again" — imports are already at `ready_to_publish`.
* No "Soft-retire" / "Restore" — the operator has not authorised lifecycle changes.
* No deletion / cleanup of imports 137 / 138 / 139.
* No bulk-topic assignment yet — Milestone 1 is import-only.

## Known limitations to surface during QA

* HTML adapter does not extract per-question explanation text from the saved
  ExamTopics page (the saved page lacks discussion bodies). 0 / 57 HTML
  imports carry `question_explanations`. Out of Milestone 1.
* XLSX fixture has empty `Giải thích đáp án` cells for every row → 0 / 37
  XLSX imports carry `question_explanations`. Fixture-data, not parser.
* PDF parser is text-only (pdfminer). Image-only / scanned PDFs would
  yield zero rows.
* Browser upload UI was not exercised end-to-end during the smoke
  (import_service direct call path was used, see
  `scripts/smoke_milestone1_fixture.py`). Anon → 303 redirect smoke is
  green via curl.
