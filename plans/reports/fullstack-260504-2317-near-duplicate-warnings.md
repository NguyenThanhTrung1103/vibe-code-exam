# Near-duplicate import warnings — implementation report

**Date:** 2026-05-04 23:35 (Asia/Saigon)
**Plan:** `plans/260504-2324-near-duplicate-warnings/plan.md`
**Target env:** dev — `exam-lxc`, `exam-platform-web` on `127.0.0.1:8001`
**Status:** ✅ Shipped to dev

## Summary

Non-blocking near-duplicate detection during admin import. Uses Postgres
`pg_trgm` (no external services, no ML model). Rows above the configured
similarity threshold land as `warning` instead of `ok`, render a "Similar
to #N (sim 0.93)" chip in the preview, and **still import by default**
unless the admin clicks **Skip**.

## Code changes

| File | LOC | Purpose |
|---|---|---|
| `migrations/versions/0010_…_pg_trgm_question_text_index.py` | +47 | Enable `pg_trgm`, build partial GIN index `WHERE deleted_at IS NULL`, concurrent build |
| `app/services/import_dedup.py` | +49 | `NearDuplicateMatch` dataclass + `find_near_duplicates(session, exam_id, question_text, threshold, limit)` |
| `app/services/import_service.py` | +27 | Hook into `parse_and_stage`; extend `confirm_import` to also process `warning`; extend `toggle_row` for `warning ↔ skipped` |
| `app/templates/admin/imports/_row.html` | +13 | Render near-dup chip on warning rows |
| `app/config.py` | +9 | `import_near_duplicate_threshold` (default 0.55) |
| `tests/test_import_unit.py` | +22 | 2 unit tests (short-text guard, dataclass rounding/truncation) |

Net: **~167 LOC + 1 migration**, well under the planned 270 estimate.

## Behaviour matrix

Verified end-to-end via `plans/reports/near-dup-smoke-driver.py` against
live LXC data (target: question #1256, exam_id=1):

| Variation | Status | Similarity | Pass |
|---|---|---|---|
| Identical question_text + same options | `duplicate` | exact-hash | ✅ |
| Same question, ` the ` → ` a `, suffix `(variant)` | `warning` | 0.932 | ✅ |
| Brand-new content (`ZZZ_SMOKE_FRESH …`) | `ok` | — | ✅ |
| Original text + ` — alt-options`, different option texts | `warning` | 0.916 | ✅ |

`warning_message` reads:
> *"Similar to question #1256 (similarity 0.93). Imports as a new question by default; skip this row to suppress."*

`normalized_data._near_duplicate_match` payload (rendered as chip in
admin preview):
```json
[{"question_id": 1256, "similarity": 0.932,
  "snippet": "The process of a web server adding a TCP header…"}]
```

## Tuning + safety

- **Threshold default 0.55** — passes typo/paraphrase/option-swap variants in smoke (0.92, 0.93) but doesn't false-positive `ZZZ_SMOKE_FRESH` against the existing 259-question bank. Configurable via `settings.import_near_duplicate_threshold` (env: `IMPORT_NEAR_DUPLICATE_THRESHOLD`).
- **Min-text-len guard 40 chars** — short stems like "Which of the following…" trigger trigram noise. Skipped without DB call (asserted in `test_find_near_duplicates_skips_short_text`).
- **Per-exam scope** — same as exact dedup. Cross-exam similarity not flagged.
- **Index excludes soft-deleted** — partial GIN `WHERE deleted_at IS NULL` keeps the index lean.

## Migration verification

```
extension: pg_trgm 1.6 active
index:     ix_questions_question_text_trgm  (GIN, partial, gin_trgm_ops)
EXPLAIN:   Seq Scan currently chosen at 259 rows (correct — small table); planner switches to GIN once table exceeds ~few-thousand rows
upgrade:   alembic upgrade head succeeded on LXC dev DB (e4f5a6b7c8d9 → f5a6b7c8d9e0)
downgrade: drop_index + DROP EXTENSION (reversible)
```

## Test results

- **Local hermetic suite**: 332 passed, 10 skipped (real-DB gated), 0 failed
- **LXC import unit tests**: 54/54 passed against deployed code
- **End-to-end smoke**: 4/4 expected outcomes confirmed (identical → duplicate, reword → warning, fresh → ok, alt-options → warning)
- **Healthz post-deploy**: `{"status":"ok","db":"ok","redis":"ok"}`

## Bonus fix discovered during implementation

Pre-existing bug: `confirm_import` only processed `status='ok'` rows
despite the preview UI saying *"Warnings do not block confirmation"*. So
validator-set warnings (e.g. invalid difficulty falling back to medium,
malformed community signal) were silently dropped on confirm. Fixed:
`confirm_import` now processes both `ok` and `warning` rows. Admin can
still skip warnings via the existing toggle (extended to support
`warning ↔ skipped`).

## State of dev DB after smoke + cleanup

| | Count |
|---|---|
| imports | 4 (143–146, original 4-dump load) |
| questions (alive) | 259 |
| community_discussion_sources | 57 |

Smoke import (#150) and orphan failed-smoke imports (#147–149 from
earlier `%%`-bug iterations) were cleaned in a single transaction
before report. No residue.

## Unresolved questions

1. **Production rollout** — this was deployed to LXC dev. When promoting to a real prod environment, the migration will need to run on real data; the index build is `CONCURRENTLY` so should be safe but worth a maintenance-window plan if the questions table grows large.
2. **Threshold tuning at scale** — 0.55 is sensible for 259 questions of mixed cert content. Once the bank has 10k+ rows across many exams, monitor "warning" volume and bump to 0.60–0.65 if admins complain about noise.
3. **pgvector path** — deferred. Trigram catches the typo/paraphrase cases shown in smoke; semantic-only matches (different words, same meaning) still slip through. Open a follow-up plan if real usage shows that's a problem.

---

**Status:** DONE
**Summary:** Near-duplicate detection live in dev; non-blocking; UI surfaces match link; threshold configurable. End-to-end smoke confirms expected status assignments for identical/reworded/fresh/option-swapped inputs.

RTK note: used `rtk grep` once during scout for `OPTION_LABELS`/Settings discovery; minimal savings.
