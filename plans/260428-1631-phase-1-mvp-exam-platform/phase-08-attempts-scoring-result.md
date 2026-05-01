---
phase: 08
title: Attempts, scoring, result/review screen
status: pending
effort: 3-4 days
priority: critical
depends_on: [07]
---

# Phase 08 — Attempts, Scoring, Result/Review Screen

## Context Links
- PRD §13 (result + review UX), §17 (review screen components)
- Phase 07 sets `finished_at`; this phase computes the rest

## Overview
Compute correctness, total score, topic breakdown, time-spent analytics. Render the result screen and the per-question review screen with the per-option reasoning entered in Phase 06. Wire the "Report this question" button into `question_reports`.

## Key Insights
- **Scoring is all-or-nothing** for multi-select (PRD §35 #6 default). Partial credit is a future enhancement.
- **Topic breakdown** uses only questions **in this attempt** (via `attempt_answers` → `questions`), not the exam's live question pool. Requires `topic_id` on question; questions without topic land in "Untagged". UI shows the bucket honestly.
- **Result page is shareable in spirit (URL has attempt id)** but server enforces ownership. No public sharing in Phase 1.
- **Review page reuses the practice question template** with `?reveal=1` semantics, plus per-option explanations and reference badge. Review **always** iterates `attempt_answers` **`ORDER BY order_index ASC`** so the student sees the same sequence as during the attempt.
- **Question reports (student)** — button on review page → modal with reason dropdown + comment → `POST` → `question_reports` row + audit log.
- **Question reports (admin)** — Phase 1 includes a minimal **admin queue** at **`/admin/question-reports`** (list, filter `open` / `resolved`, link to question, actions **mark resolved** / **rejected**). Implement in this phase alongside student POST; `require_role("admin")`, CSRF, rate limits per Phase 09. (If time-boxed, ship student POST + DB first, but admin list must land before public beta — track in Phase 12 checklist.)
- **No AI tutor** in Phase 1 — the "Ask AI Tutor" button is hidden or shown as "Coming soon" tooltip.
- **Computation timing:** scoring runs synchronously on submit. Prefer **one or two set-based queries** (load all `attempt_answers` for the attempt plus related `question_options` / correctness flags), then compute in Python — avoid N+1 and avoid mis-joining `question_options` as if each row were one "answer."

## Requirements
**Functional**
- Routes:
  - `GET /attempts/{id}/result` — score + topic breakdown + suggestions.
  - `GET /attempts/{id}/review` — paginated review of all questions.
  - `GET /attempts/{id}/review?wrong_only=1` — wrong answers only.
  - `GET /attempts/{id}/review/q/{order}` — single-question review.
  - `POST /questions/{id}/reports` — student-side dispute.
- Score calculation:
  - `is_correct = (set(selected_options) == set(correct_options))` per question.
  - `score_percent = correct_count / total_questions * 100`.
  - `passed = score_percent >= exam.passing_score_percent` (if set).
- Topic breakdown: per topic, `correct/total`. Sort weakest first.
- Recommendation: top 2 weakest topics (≥3 questions each, score ≤ overall − 10pt).
- Review page shows: question, student selection, correct answer, per-option explanation, overall explanation, reference, confidence badge ("unverified — Phase 1 only"), report button.

**Non-functional**
- Result computed in <500 ms for 100-question attempt.
- Review page loads question + options in single query.

## Architecture

```
app/
├── routers/
│   ├── attempts.py                    # /attempts/{id}/result, /review, /review/q/{n}
│   ├── reports.py                     # POST /questions/{id}/reports (student)
│   └── admin/
│       └── question_reports.py        # GET /admin/question-reports, resolve/reject actions
├── services/
│   ├── scoring_service.py             # compute_score, topic_breakdown
│   └── recommendation.py              # weakest-topic suggestion
├── templates/
│   ├── attempts/
│   │   ├── result.html
│   │   ├── review_list.html
│   │   ├── review_question.html
│   │   ├── _topic_bar.html
│   │   └── _confidence_badge.html
│   └── reports/_modal.html
├── schemas/report.py
└── tests/test_scoring.py, test_review_routes.py, test_reports.py
```

### Scoring algorithm

**Per question, one row in `attempt_answers`:** compare the **set** of selected option labels (from `attempt_answers.selected_options`) to the **set** of correct option labels derived from `question_options` where `is_correct == True`. Do **not** treat each `question_options` row as a separate "answer line" for scoring — aggregate by `question_id` (or by `attempt_answer.id`).

```python
def compute_attempt_score(session, attempt_id) -> AttemptScore:
    # 1) Load all attempt_answers for this attempt (with question_id, selected_options, order_index).
    # 2) For those question_ids, load question_options; build correct_label_set per question_id:
    #    correct_labels[qid] = { row.option_label for row in options where row.is_correct }
    # 3) For each attempt_answer row:
    #    selected_set = parse_selected_labels(aa.selected_options)   # e.g. {"A","C"}
    #    is_correct = selected_set == correct_labels[aa.question_id]
    #    Set aa.is_correct accordingly (all-or-nothing for multi-select).
    # 4) Aggregate: total questions, correct_count; topic breakdown from questions.topic_id via attempt_answers.
    # 5) Persist aggregates on attempts row.
```

**Review and result screens** list questions in **`order_index ASC`**. Topic breakdown and percentages use **only** `attempt_answers` tied to this `attempt_id`, not a fresh count of the exam's published questions.

### Per-topic breakdown
```sql
SELECT t.id, t.name, t.weight,
       COUNT(*)                          AS total,
       COUNT(*) FILTER (WHERE aa.is_correct) AS correct
FROM attempt_answers aa
JOIN questions q ON q.id = aa.question_id
LEFT JOIN topics t ON t.id = q.topic_id
WHERE aa.attempt_id = :id
GROUP BY t.id, t.name, t.weight;
```

## Related Code Files
**Create**
- `app/services/scoring_service.py`, `recommendation.py`
- `app/routers/attempts.py`, `reports.py`, `app/routers/admin/question_reports.py`
- `app/schemas/report.py`
- `app/templates/attempts/*.html`, `templates/reports/_modal.html`, `app/templates/admin/question_reports/*.html`
- `tests/test_scoring.py`, `test_review_routes.py`, `test_reports.py`

## Implementation Steps

1. **Scoring service** — set-based load of `attempt_answers` + `question_options` for involved `question_id`s; per-question **set equality** (`selected` vs `correct` labels). Set `is_correct` per `attempt_answer`. Compute aggregate.
2. **Hook into submit** — `attempt_service.submit()` (Phase 07) now calls `scoring_service.compute_attempt_score()` inside the same tx, persists `attempts.score_percent`, `correct_count`, `wrong_count`, `passed`.
3. **Result page**
   - Big score number + pass/fail banner.
   - Counts row.
   - Topic breakdown bars (sorted weakest first).
   - Recommendation panel (top 2 weak topics).
   - CTAs: Review wrong only / Review all / Retake.
4. **Review list page**
   - Paginated 25/page.
   - Per row: Q index, status icon (✓/✗), topic, difficulty.
   - Filter chips: All / Wrong / Flagged / Reported.
5. **Review single-question page**
   - Question with selection vs. correct visually distinguished.
   - Each option: text + per-option explanation (from `question_options.explanation`) + checkmark/X.
   - Overall explanation panel.
   - Reference URL with trust badge.
   - Confidence badge — Phase 1: always renders **"Unverified (admin-supplied)"**; sets honest expectation.
   - "Report this question" button → modal.
   - "Last verified" — Phase 1 shows "Manual import" or `last_verified_at` if admin manually set it.
6. **Question report modal** (student)
   - Reason dropdown (`wrong_answer`, `ambiguous`, `outdated`, `typo`, `other`).
   - Comment textarea (optional, ≤2000 chars).
   - POST creates `question_reports` row with `status='open'` + audit log.
6b. **Admin question reports** (`/admin/question-reports`)
   - Paginated table; filters: status open / resolved / rejected (as schema allows).
   - Row: report id, question link, reason, created_at, reporter (if stored).
   - Actions: view question, **mark resolved**, **mark rejected** (each writes audit log).
7. **Recommendation logic** — pick topics where:
   - ≥3 questions answered in the attempt.
   - Topic score ≥10 percentage points below overall.
   - Cap at 2 suggestions; sort by score gap descending.
8. **Tests**
   - Scoring with single-select correct.
   - Scoring with multi-select all-or-nothing.
   - Untagged questions roll up into "Untagged" bucket.
   - Wrong-only filter shows only `is_correct=false`.
   - Cross-user access to `/attempts/{id}/result` returns 403.
   - Report submission creates row + audit entry.
   - Admin `/admin/question-reports`: list, resolve/reject, audit written; non-admin gets 403.

## Todo List
- [ ] Set-based scoring (per-question set compare); update `is_correct` on each `attempt_answer`
- [ ] Admin `/admin/question-reports` list + resolve/reject + audit
- [ ] Submit pipeline writes score fields atomically
- [ ] Result page with topic breakdown and recommendations
- [ ] Review list with filters and pagination
- [ ] Single-question review page
- [ ] Per-option explanation rendering
- [ ] Confidence badge ("Unverified" in Phase 1)
- [ ] Question report modal + endpoint
- [ ] Recommendation ranks weak topics correctly
- [ ] Cross-user access blocked
- [ ] Tests for scoring + filters + reports

## Success Criteria
- 50-question NSE4 attempt computes score + topic breakdown in <500 ms.
- Multi-select question with one missed correct option scores wrong (all-or-nothing verified).
- Recommendation surfaces 2 weakest topics with ≥3 questions each.
- Reporting a question creates a `question_reports` row visible at **`/admin/question-reports`** (admin queue from this phase).
- Result page passes "no-coaching" usability — beta tester reads it without help.

## Risk Assessment
- **Slow scoring on huge attempts** (e.g., 200-question exam) — set-based queries + in-Python set compare mitigates; benchmark in tests.
- **Recommendation fires misleading suggestions** with sparse topic data — guard with ≥3 questions per topic.
- **Untagged bucket dominating** if admin didn't assign topics — surfacing the gap as a soft warning on result page is healthy.
- **Confidence badge wording** ("Unverified") may erode trust in Phase 1. Honest expectation-setting > silent over-promising.

## Security Considerations
- Result/review pages: `attempt.user_id == current_user.id` enforced.
- Review page does not expose `is_correct` for *other* users' attempts (N/A here, but design assumption).
- Report endpoint rate-limited: 30/hour/user.
- Reason dropdown server-side validated (enum).
- Comment textarea sanitized + length-capped (2000).

## Next Steps
Phase 09 — Security hardening (CSP, full HTML sanitizer policies, encrypted backups groundwork). Phase 10 — Backup + observability + DR drill.
