# Near-duplicate import warnings

**Status:** ✅ Shipped to dev (LXC) on 2026-05-04
**Owner:** Jason
**Created:** 2026-05-04

## Problem

Exact-match dedup (`content_hash` SHA-256) is correct and not changing. But
admins want a **non-blocking signal** when a candidate import row looks
suspiciously similar to an existing question on the same exam (typos,
paraphrases, slight rewording). Today such rows import as new questions
silently — admin discovers the near-duplicate weeks later via student
reports.

## Goal

During `parse_and_stage`, attach a `near_duplicate_match` payload to each
import_item that crosses a similarity threshold against existing
non-deleted questions on the same exam. **Do not block** — admin sees the
match on the preview page, can:

- ignore (default → row imports as new question)
- mark as duplicate (status flips to `duplicate`, no question created)
- open the matched question in a side panel for compare

## Out of scope

- Cross-exam similarity (per-exam scope only)
- Semantic embeddings (pg_trgm first; embeddings is phase 2 only if trigram proves insufficient)
- Auto-merge / canonicalisation (admin decision, manual)
- Editing the matched canonical question (separate flow)

## Approach

**Extension:** `pg_trgm` (already-shipped Postgres contrib). Char-trigram
similarity scoring on `question_text`. Cheap, native, no external services.

**Threshold:** start at `0.55` (Postgres default `set_limit`). Tune with
synthetic test pairs in phase 5. Configurable via
`settings.import_near_duplicate_threshold`.

**Why not pgvector + embeddings:** more ops surface (model serving, GPU
budget, async backfill, vector index tuning) for a marginal win on
question text that's already short and lexically constrained. Defer to a
later iteration if trigram misses too many real near-duplicates.

## Phases

| # | Phase | Status | LOC est. |
|---|---|---|---|
| 01 | Migration: enable `pg_trgm` + GIN index on `questions.question_text` | ✅ done | 47 |
| 02 | Service: `find_near_duplicates(session, exam_id, text, k=3, threshold)` in `app/services/import_dedup.py` | ✅ done | 49 |
| 03 | Wire into `parse_and_stage`: attach `_near_duplicate_match` JSONB to `import_items.normalized_data`, set `status='warning'` when matched. Also extended `confirm_import` to import `warning` rows (was missing semantic — preview text said warnings don't block but code only confirmed `ok`) and `toggle_row` to support `warning ↔ skipped`. | ✅ done | 27 |
| 04 | Preview UI: render "Similar to #N (sim 0.78)" chip on warning rows linking to `/admin/questions/N/edit` | ✅ done | 13 |
| 05 | Tests: hermetic guards on short-text bypass + dataclass shape; full real-DB end-to-end via smoke driver | ✅ done | 22 unit + smoke driver |

Total ≈ 270 LOC + migration. Single sprint.

## Key trade-offs

- **`status='warning'` reuse vs new status** — preview already renders
  warnings with distinct styling. Reusing is cheaper than adding
  `near_duplicate` to the enum + migration.
- **GIN index on `question_text`** — write amplification on every
  question insert, ~5-10% overhead. Acceptable.
- **Threshold setting per-exam vs global** — start global, lift to
  per-exam if real exams have very different baselines (likely fine
  global since most exams are CS/cert content).

## Risks

- **False-positive flood**: trigram matches ~every common-stem question. Mitigation: phase 5 threshold tuning + minimum length guard (skip < 40 char question_text).
- **Performance** on large exams (>10k questions): `LIMIT k` + GIN index keeps it bounded. Benchmark at end of phase 02.

## Files touched (preview)

- `migrations/versions/...near_duplicate_index.py` (new)
- `app/services/import_dedup.py` (extend)
- `app/services/import_service.py` (call new func in parse_and_stage)
- `app/templates/admin/imports/preview.html` (render match)
- `app/templates/admin/imports/_row.html` (toggle)
- `app/config.py` (`import_near_duplicate_threshold`)
- `tests/test_import_dedup_unit.py` (new)
- `tests/test_import_real_db.py` (extend; gated on EXAM_PLATFORM_TEST_REAL_DB)

## Decision needed

Approve to proceed? If yes, phase 01 first (migration is reversible — drop extension/index leaves no schema delta).
