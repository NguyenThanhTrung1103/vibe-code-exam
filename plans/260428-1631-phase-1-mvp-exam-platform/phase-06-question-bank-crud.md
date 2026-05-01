---
phase: 06
title: Question bank CRUD & manual editor
status: pending
effort: 2-3 days
priority: high
depends_on: [05]
---

# Phase 06 — Question Bank CRUD & Manual Editor

## Context Links
- PRD §3 (catalog), §7.2 (`questions`, `question_options`, `question_explanations`), §23 (lifecycle)
- Phase 05 left questions in `imported`/`private`/`draft`; this phase lets admin edit and prep for publish

## Overview
Admin UI for editing imported questions and creating new ones manually: question text, options, correct answer, per-option explanation, overall explanation, reference URL, topic, difficulty, retire/restore. Maintain audit-log discipline (same as Phase 03: **`audit_log_writer.write()` per mutation in-session**). Single-question editor + paginated list view.

**Student `question_reports`:** triage UI lives at **`/admin/question-reports`** (Phase 08). This phase does not duplicate that queue; link from admin nav when Phase 08 ships.

## Key Insights
- Most edits at MVP fix typos and assign topics. UI optimizes for fast keyboard-driven editing.
- **Per-option explanation** is a Phase 1 deliverable even without AI — admin types the "why wrong" reasoning manually for first 50–100 questions; this becomes training context for Phase 2.
- Soft-delete here is `retired_at`, not `deleted_at`. Retired questions still serve historical attempts but are excluded from new attempt pools.
- **Question publishing is implicit:** a question is "published" when its parent exam is published *and* the question is not retired. No separate per-question publish toggle in Phase 1.
- HTMX inline edit pattern: click a field → edit form swaps in → save → row swaps back. No SPA needed.

## Requirements
**Functional**
- `/admin/exams/{exam_slug}/questions` — paginated list (50/page) with filters: topic, difficulty, status, has-explanation.
- `/admin/exams/{exam_slug}/questions/new` — manual create form.
- `/admin/questions/{id}/edit` — full editor.
- Editor fields: question_text, question_type, options (A–E with is_correct checkboxes), correct_answer (auto-derived from options), per-option `explanation`, overall `correct_explanation`, single `reference` URL, topic, difficulty, retire toggle.
- Soft-retire: sets `retired_at`, hides from new attempts.
- Bulk action: assign topic to selected questions.

**Non-functional**
- List page renders 50 questions in <300 ms p95.
- Save round-trip <500 ms.

## Architecture

```
app/
├── routers/admin/questions.py
├── services/question_service.py     # CRUD + audit + retire/restore
├── schemas/question.py
├── templates/admin/questions/
│   ├── list.html
│   ├── _row.html                    # paginated row partial
│   ├── new.html
│   ├── edit.html
│   ├── _form.html
│   └── _option_row.html             # inline option editor
└── tests/test_question_service.py, test_admin_questions.py
```

### Service surface
```python
class QuestionService:
    def create(session, *, actor, exam_id, payload) -> Question
    def update(session, *, actor, question_id, payload) -> Question
    def update_option(session, *, actor, option_id, payload) -> QuestionOption
    def retire(session, *, actor, question_id, reason) -> None
    def restore(session, *, actor, question_id) -> None
    def assign_topic_bulk(session, *, actor, question_ids, topic_id) -> int
    # all funnel through audit_log_writer
```

## Related Code Files
**Create**
- `app/services/question_service.py`
- `app/schemas/question.py`
- `app/routers/admin/questions.py`
- `app/templates/admin/questions/*.html`
- `tests/test_question_service.py`, `test_admin_questions.py`

## Implementation Steps

1. **Schemas** — `QuestionIn`, `QuestionOptionIn`, `QuestionUpdate`. Validate text length, allowed enums, options 2–5 items, correct_answer subset of options.
2. **`QuestionService`** with CRUD + retire/restore. Each write goes through audit (events: `question.created`, `question.text_edited`, `question.option_edited`, `question.explanation_edited`, `question.retired`, `question.restored`, `question.topic_assigned`).
3. **Content hash maintenance** — on text/option edit, recompute `content_hash` using the **same canonical formula as `plan.md` / Phase 05** (`sha256(normalized_question + "|" + "||".join(sorted_normalized_options))`); if collision with another question in same exam, warn but allow.
4. **List view** with filters + pagination. Filters compose into a SQLAlchemy `select()` with `WHERE` clauses on `topic_id`, `difficulty`, `status`, `retired_at IS NULL`.
5. **HTMX-driven inline edit** — clicking a question opens edit page (full page is OK, simpler than fragment swap for full editor); options table inline-editable per row via fragment swap.
6. **Bulk topic assign** — checkboxes on list page + `<select>` for topic + "Assign" button; HTMX post returns updated rows.
7. **Retire confirmation** — small modal (Alpine.js `x-data` toggle) requiring a typed reason → audit log captures reason.
8. **Tests** — full CRUD, retire/restore, content_hash recompute, audit entries present, bulk topic assign updates correct rows.

## Todo List
- [ ] Pydantic schemas with validators
- [ ] `QuestionService` with audit-logged mutations
- [ ] Content hash recomputation on edit
- [ ] List view with filters and pagination
- [ ] Manual create form
- [ ] Edit page with inline option editing
- [ ] Per-option explanation field saved
- [ ] Retire/restore with reason
- [ ] Bulk topic assignment
- [ ] Audit entries for every mutation
- [ ] Tests cover service + routes

## Success Criteria
- Admin can edit a 4-option question (text, options, explanations, topic, difficulty) and save in <30 s including UI.
- Retired questions disappear from public exam page immediately.
- Bulk-assigning 50 questions to a topic produces 50 audit entries (or 1 batch + 50 detail).
- Editing a question to match another's content produces a warning but does not block save.

## Risk Assessment
- **Per-option explanation tedium** for admin — at MVP, admin may leave them blank. UI flags missing explanations on list view as a soft warning, not error.
- **Audit log volume** if admin bulk-edits 1000 questions. Acceptable; log table is partitioned naturally by `created_at` index. Re-evaluate if it becomes >10M rows.
- **Concurrent edit conflicts** — two admins editing same question. Phase 1: last-write-wins, audit log preserves history. Optimistic concurrency token deferred.

## Security Considerations
- All routes `require_role("admin")`.
- Reference URL field validated as `http(s)://` only; no `javascript:` etc.
- Question text + options + explanations re-sanitized on save (defense in depth).
- Retire reason input length capped at 500 chars; sanitized.

## Next Steps
Phase 07 — Practice and exam mode delivery uses the published, non-retired questions.
