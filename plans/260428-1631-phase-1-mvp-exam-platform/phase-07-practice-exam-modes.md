---
phase: 07
title: Practice & exam mode delivery
status: pending
effort: 4-5 days
priority: critical
depends_on: [06]
---

# Phase 07 — Practice & Exam Mode Delivery

## Context Links
- PRD §12 (modes), §16 (UX components), §22 (multi-select handling)
- Phase 06 left a question bank in place; this phase serves it to learners

## Overview
Implement two of the five PRD modes: **Practice** (immediate feedback per question) and **Exam** (timer, no feedback until submit). Question delivery, answer submission with auto-save, navigation, flag/bookmark, multi-select handling, exam timer with auto-submit. Result/review screen handled in Phase 08.

## Key Insights
- **Sequential single-page-per-question** is the simplest correct UX. SPA-style "all questions on one page" creates state-management bugs and timer drift.
- **Server holds the source of truth.** Each answer submission is a `POST` to `/attempts/{id}/answers/{question_id}`. Auto-save fires on selection change via HTMX (`hx-trigger="change delay:500ms"`).
- **Timer is server-authoritative.** Client shows countdown from `attempt.started_at + exam.time_limit_seconds`; client clock cannot grant extra time. Server enforces on submit.
- **Question order is fixed at attempt creation and persisted on `attempt_answers.order_index`** (Phase 02 schema). At `POST /attempts/start`, take a **snapshot** of published, non-retired questions for the exam, **shuffle randomly once** (e.g. `random.shuffle` after `secrets` or `random` — unpredictable order per attempt is fine). Immediately persist the resulting order as `order_index` 1..N on each pre-created `attempt_answers` row. **From that point on, `order_index` is the only source of truth** for navigation, review, replay, and analytics — not a live re-shuffle. After the attempt exists, **admin edits or `retired_at` on a question do not reorder or drop rows** for that attempt; the attempt still references the same `question_id` rows (content may change for display policy, but sequence stays frozen).
- **Decision needed (PRD §35 #5):** free navigation in Exam mode vs. forward-only. Phase 1 default: **free navigation, like real exams**. Document and ship.
- **Multi-select UX:** show "Select N answers" label when `question_type=multiple` and `correct_answer` count >1.
- **Anonymous practice:** Phase 1 requires registration (PRD #4 decision pending; recommended yes for analytics). Confirm or revisit at launch.

## Requirements
**Functional**
- Routes:
  - `POST /attempts/start` — body: `exam_id`, `mode`. Creates attempt; redirects to question 1.
  - `GET /attempts/{id}/q/{order}` — show question at position `order`.
  - `POST /attempts/{id}/q/{order}/answer` — auto-save selection.
  - `POST /attempts/{id}/q/{order}/flag` — toggle flag.
  - `POST /attempts/{id}/submit` — finalize.
- Modes: Practice (immediate explanation reveal — toggled in Phase 08 review); Exam (no reveal until submit).
- Timer: visible in Exam mode only; soft warning at 5 min remaining (yellow); 0 min auto-submit.
- Multi-select: checkboxes; "Select N answers" badge.
- Flag/bookmark: client-side optimistic, server-side persisted.
- Navigation: prev/next, jump-to (number grid in side panel).
- Auto-save: each selection persisted; refresh recovers state.

**Non-functional**
- Question page render <500 ms p95.
- Auto-save round-trip <300 ms.
- 1000 simultaneous attempts feasible on a single LXC (postgres connection budget OK at 30/limit per role).

## Architecture

```
app/
├── routers/practice.py
├── services/
│   ├── attempt_service.py            # start, get_question, save_answer, submit
│   └── question_selector.py          # snapshot exam questions, shuffle once, persist order_index
├── schemas/attempt.py
├── templates/practice/
│   ├── question.html
│   ├── _option_radio.html
│   ├── _option_checkbox.html
│   ├── _timer.html                   # Alpine x-data countdown
│   ├── _nav_grid.html
│   └── submit_confirm.html
└── static/js/practice.js             # tiny, optional
```

### Attempt state machine
```
created → in_progress → submitted
                      └→ abandoned (auto if no activity for 24h)
```

### Question selector (shuffle once at start, persist via `order_index`)
```python
def start_attempt(session, *, user_id, exam_id, mode) -> Attempt:
    qs = list_published_active_questions(exam_id)   # snapshot for this attempt only
    random.shuffle(qs)                                 # one random permutation; not reproducible across attempts
    attempt = Attempt(user_id=user_id, exam_id=exam_id,
                      exam_version=current_exam_version,
                      mode=mode, started_at=now())
    session.add(attempt); session.flush()            # need attempt.id
    for idx, q in enumerate(qs, start=1):
        session.add(AttemptAnswer(
            attempt_id=attempt.id,
            question_id=q.id,
            question_version=q.question_version,
            order_index=idx,                          # 1..N, frozen forever for this attempt
            selected_options=None,
            is_correct=None,
            flagged=False,
        ))
    session.commit()
    return attempt
```
Navigation, review, and replay **always** use `order_index` (and the linked `question_id` on each `attempt_answer`). They **do not** re-query the exam's current question list for ordering. Later admin edits or retirements **do not change** `order_index` or which rows belong to the attempt; historical attempts remain valid for review.

### Timer (client + server)
- Client: Alpine `x-data` reads `time_remaining_seconds` from server-rendered attribute, decrements every second, posts `submit` on 0.
- Server: every page render computes `time_left = (started_at + time_limit) - now()`. If <0 and mode is exam, redirect to submit.

## Related Code Files
**Create**
- `app/services/attempt_service.py`, `question_selector.py`
- `app/schemas/attempt.py`
- `app/routers/practice.py`
- `app/templates/practice/*.html`
- `app/static/js/practice.js` (small)
- `tests/test_attempt_service.py`, `test_question_selector.py`, `test_practice_routes.py`

## Implementation Steps

1. **Attempt creation** — `POST /attempts/start` validates exam published, exam has ≥1 published non-retired question. Creates `attempt` row + pre-creates `attempt_answers` (one per question) with `order_index` 1..N, `selected_options=NULL`. Wraps in single transaction.
2. **Question delivery** route — fetches `attempt_answer` by `(attempt_id, order_index=:n)`, joins to `question` and options. Renders via Jinja partial. Ignores any newer published questions on the exam — the frozen attempt order is authoritative.
4. **Answer save** — accepts `selected_options` (string `B` or `A,C`); validates each label exists; updates `attempt_answers.selected_options`. Returns 204 (HTMX swap target = nothing).
5. **Flag toggle** — flips `attempt_answers.flagged`. Returns updated flag-icon partial.
6. **Navigation** — prev/next compute next `order_index`; jump-to grid renders attempt_answers state badges (answered/flagged/blank).
7. **Multi-select handling** — render checkboxes vs radios based on `question.question_type`. Show "Select N answers" when type is `multiple`; N from `count(is_correct)`.
8. **Timer**:
   - Server passes `time_remaining_seconds` to template only in Exam mode.
   - Alpine countdown handles UI ticks.
   - Soft warning (color flip) at 300 s.
   - On 0, client posts to `/attempts/{id}/submit`. Server also checks server-time on every render — defense in depth.
9. **Submit endpoint** — sets `finished_at`, then delegates to Phase 08 `scoring_service` in the same transaction (Phase 08); redirects to result page.
10. **Idle handling** — if no activity for 24h, mark `abandoned` via daily cron (Phase 10 / 11). Phase 7 only renders banner "Resume in progress."
11. **Practice mode reveal** — flag in URL `?reveal=1` (server-rendered) shows correct answer + explanation immediately after each selection. Phase 08 wires the result review; here we just render the toggle behavior.
12. **Tests**:
    - start attempt: pre-creates N attempt_answers rows.
    - save selection updates row.
    - timer expiry server-side forces submit.
    - multi-select with 2 correct shows "Select 2 answers" label.
    - prev/next navigation respects bounds.
    - jump-to grid badges match state.

## Todo List
- [ ] Attempt start with pre-created attempt_answers (`order_index` 1..N)
- [ ] Question shuffle frozen via `order_index`; survives later question edits/retirements
- [ ] Question delivery page with HTMX auto-save
- [ ] Multi-select label and checkbox rendering
- [ ] Flag/bookmark toggle
- [ ] Prev/next + jump-to navigation grid
- [ ] Timer with Alpine countdown + server enforcement
- [ ] Soft warning at 5 min
- [ ] Auto-submit on time expiry (server-authoritative)
- [ ] Practice-mode reveal toggle (basic)
- [ ] Submit endpoint sets finished_at
- [ ] Tests cover happy paths and timer enforcement

## Success Criteria
- Student starts NSE4 attempt → answers 50 questions in 60-min exam mode → auto-submits at 0 → result page accessible (Phase 08).
- Refreshing mid-attempt restores all selections.
- Multi-select question with 2 correct answers requires both to be marked.
- Server clock manipulation (browser DevTools) does NOT extend the timer.
- 100 concurrent attempts on dev LXC sustain p95 <800 ms.

## Risk Assessment
- **HTMX auto-save chatter** — every selection change posts. Debounce 500 ms. Acceptable load (<2 req/s/user).
- **Timer drift** if server time skewed from NTP. Mitigate: ensure NTP/chrony installed in deployment phase.
- **Race condition** on submit (auto-submit + manual submit collision). Mitigate: idempotent submit (`if finished_at is not null: return current state`).
- **Reload-spam** loophole to "skip" timer (refresh between submits) — server uses `started_at` not session, so no.
- **Pre-creating attempt_answers** is wasted I/O if student abandons. Acceptable; row count modest.

## Security Considerations
- All practice routes require authenticated user; cross-user attempt access returns 403 (`attempt.user_id != current_user.id`).
- CSRF on all POST endpoints.
- Rate limit on `start attempt`: 30/min per user (anti-abuse).
- Multi-select labels NOT exposed via API in exam mode (no `is_correct` on the `GET q/{n}` endpoint).
- Question text rendered via sanitized markdown (re-sanitization at render).

## Next Steps
Phase 08 — Compute scoring, generate result + review screens with explanations.
