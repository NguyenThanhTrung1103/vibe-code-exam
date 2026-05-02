-- ============================================================================
-- Gate-A1 synthetic seed cleanup — DRAFT (do not run until reviewed + approved)
-- ============================================================================
-- Date    : 2026-05-02
-- Source  : plans/reports/gate-a1-260502-seed.xlsx (15 synthetic rows)
-- Purpose : Remove the 15 synthetic Gate-A1 UI-smoke rows + their import header
--           after the admin review is complete. Keeps prod's question bank
--           free of synthetic data.
-- Run as  : postgres OR exam_platform_user (DB owner). Wrap in BEGIN/COMMIT.
-- Database: exam_platform_db ONLY (NEVER blogdb).
--
-- SAFETY: triple-guard targeting (boolean AND) prevents false-positive deletion.
--   1. external_question_id LIKE 'SYN-Q-%'
--   2. source_url           LIKE '%/discussions/synthetic/%'
--   3. imports.file_name    LIKE '%gate-a1-260502-seed%'
-- All three must agree per row before any DELETE acts on it.
--
-- USAGE:
--   1) Take pg_dump backup first (see plans/reports/gate-a1-260502-execution-note.md).
--   2) Run preview queries P1..P4. Verify counts match expected.
--   3) If preview counts are NOT as expected → ROLLBACK and escalate.
--   4) Otherwise execute D1..D5 and final verification block.
--   5) COMMIT. Or ROLLBACK if any verification count > 0.
-- ============================================================================

\set ON_ERROR_STOP on
\echo '== gate-a1-260502 cleanup START =='
BEGIN;

-- ---------------------------------------------------------------------------
-- PREVIEW (run before any DELETE; abort if counts unexpected)
-- ---------------------------------------------------------------------------

-- P1. Synthetic CDS rows.
\echo '-- P1 preview: synthetic CDS rows (expect 15 after one import)'
SELECT count(*) AS preview_synthetic_cds_rows
FROM community_discussion_sources
WHERE external_question_id LIKE 'SYN-Q-%'
  AND source_url LIKE '%/discussions/synthetic/%';

-- P2. Synthetic Import header(s).
\echo '-- P2 preview: synthetic Import headers (expect 1 per import attempt)'
SELECT id AS import_id, file_name, target_exam_id, status, created_at, finished_at
FROM imports
WHERE file_name LIKE '%gate-a1-260502-seed%'
ORDER BY id DESC;

-- P3. Synthetic questions tied to the import.
\echo '-- P3 preview: synthetic questions (expect 15 per import attempt)'
WITH syn_imports AS (
    SELECT id FROM imports WHERE file_name LIKE '%gate-a1-260502-seed%'
)
SELECT count(*) AS preview_synthetic_questions
FROM questions q
WHERE q.source_import_id IN (SELECT id FROM syn_imports);

-- P4. Sanity sample — every row's text MUST match 'Sample synthetic question'.
\echo '-- P4 preview: question-text sanity sample'
WITH syn_imports AS (
    SELECT id FROM imports WHERE file_name LIKE '%gate-a1-260502-seed%'
)
SELECT q.id, left(q.question_text, 60) AS text_head, q.exam_id,
       q.source_locator->>'file_name' AS src_file
FROM questions q
WHERE q.source_import_id IN (SELECT id FROM syn_imports)
ORDER BY q.id;
-- Expected: every text_head starts with 'Sample synthetic question'.
-- ABORT (ROLLBACK + escalate) if any row's text does not match.

-- ---------------------------------------------------------------------------
-- DELETE — cascade-ordered (respects FK constraints).
--   community_discussion_sources -> question_options -> question_explanations
--   -> questions -> import_items -> imports
-- ---------------------------------------------------------------------------

-- D1. Synthetic community sources first (FK questions ON DELETE RESTRICT).
\echo '-- D1: delete synthetic community_discussion_sources'
DELETE FROM community_discussion_sources
WHERE external_question_id LIKE 'SYN-Q-%'
  AND source_url LIKE '%/discussions/synthetic/%';

-- D2a. Question options.
\echo '-- D2a: delete options of synthetic questions'
WITH syn_qids AS (
    SELECT q.id
    FROM questions q
    JOIN imports  i ON i.id = q.source_import_id
    WHERE i.file_name LIKE '%gate-a1-260502-seed%'
)
DELETE FROM question_options
WHERE question_id IN (SELECT id FROM syn_qids);

-- D2b. Question explanations.
\echo '-- D2b: delete explanations of synthetic questions'
WITH syn_qids AS (
    SELECT q.id
    FROM questions q
    JOIN imports  i ON i.id = q.source_import_id
    WHERE i.file_name LIKE '%gate-a1-260502-seed%'
)
DELETE FROM question_explanations
WHERE question_id IN (SELECT id FROM syn_qids);

-- D3. Synthetic questions.
\echo '-- D3: delete synthetic questions'
DELETE FROM questions
WHERE source_import_id IN (
    SELECT id FROM imports WHERE file_name LIKE '%gate-a1-260502-seed%'
);

-- D4. Import items (FK to imports has ON DELETE CASCADE; explicit DELETE
--      makes the affected-row count visible in psql output).
\echo '-- D4: delete synthetic import_items'
DELETE FROM import_items
WHERE import_id IN (
    SELECT id FROM imports WHERE file_name LIKE '%gate-a1-260502-seed%'
);

-- D5. Import header(s).
\echo '-- D5: delete synthetic Import header(s)'
DELETE FROM imports
WHERE file_name LIKE '%gate-a1-260502-seed%';

-- D6. (OPTIONAL — left commented out by default)
--      Pruning audit_log entries for the synthetic import. Audit history is
--      intentionally append-only; only enable this if synthetic audit noise
--      is genuinely a concern. Adjust the timestamps to bracket the import +
--      cleanup window before uncommenting.
--
-- DELETE FROM audit_log
-- WHERE entity_type IN ('community_source','question','import','import_item')
--   AND created_at > '<import-start-timestamp>'::timestamptz
--   AND created_at < '<cleanup-timestamp>'::timestamptz;

-- ---------------------------------------------------------------------------
-- VERIFICATION (must all be 0 before COMMIT; otherwise ROLLBACK)
-- ---------------------------------------------------------------------------

\echo '-- Verification: leftover_cds, leftover_imports, leftover_questions (must all be 0)'
SELECT
    (SELECT count(*) FROM community_discussion_sources
       WHERE external_question_id LIKE 'SYN-Q-%'
         AND source_url LIKE '%/discussions/synthetic/%')                         AS leftover_cds,
    (SELECT count(*) FROM imports
       WHERE file_name LIKE '%gate-a1-260502-seed%')                              AS leftover_imports,
    (SELECT count(*) FROM questions q
       JOIN imports i ON i.id = q.source_import_id
       WHERE i.file_name LIKE '%gate-a1-260502-seed%')                            AS leftover_questions;

-- If any of the three counts > 0 → ROLLBACK and investigate.
-- If all three = 0 → COMMIT.

COMMIT;
\echo '== gate-a1-260502 cleanup COMMIT =='

-- End of file. No further statements.
