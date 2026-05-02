---
title: Gate-A1 — Lean Execution Note
date: 2026-05-02
purpose: Validate Phase 16a-lite UI usefulness with minimum friction
companion: gate-a1-260502-checklist.md
---

# Gate-A1 — Lean Execution Note

## The whole flow (4 steps)

1. **Seed** — admin uploads 15–20-row community-bearing Excel via `/admin/imports`.
2. **Data readiness check** — 1 query, 5 sec, must pass thresholds (§3 below).
3. **Admin review** — admin opens 10 questions, fills `gate-a1-260502-checklist.md`.
4. **Decide** — checklist verdict feeds the decision matrix (§5 below).

## §1 Seed-data guidance

Prefer **real** community-bearing dump data (admin sources from a real ExamTopics-style dump or partner-supplied data).

Synthetic data is **acceptable for UI smoke only**, NOT for the final Gate-A1 decision. If review uses synthetic data, the verdict is provisional and must be re-run with real data before committing to Phase 14 / 16b.

Excel column hints (Phase 13 alias map auto-recognises these):

| Column header | Maps to |
|---|---|
| `Question`, `Question Text`, `Q` | `question_text` |
| `A`..`E`, `Option A`..`Option E` | `option_a`..`option_e` |
| `Correct`, `Correct Answer`, `Answer` | `correct_answer` |
| `Difficulty`, `Level` | `difficulty` |
| `Discussion URL`, `Discussion` | `discussion_url` |
| `External Question ID`, `Ext QID` | `external_question_id` |
| `Discussion Count`, `Comments` | `discussion_count` |
| `Vote A`..`Vote F` | `vote_a`..`vote_f` |

Aim for **≥3 rows where the top vote disagrees with `correct_answer`** so conflict warnings appear.

## §2 Operator vs admin: who does what

If no Beta-A admin is available now, **operator/dev may seed data first** (§1). The seed step doesn't require admin judgement — it's just an import.

The **review** step (§4) **must be done by an admin** to make the Gate-A1 verdict meaningful. The admin role is for usefulness assessment, not data entry.

## §3 Read-only data readiness check

ONE query, run from LXC. Read-only.

```bash
ssh exam-lxc 'cd /srv/exam-platform && set -a && . ./.env && set +a && /srv/exam-platform/.venv/bin/python -c "
from sqlalchemy import create_engine, text
import os
e = create_engine(os.environ[\"DATABASE_URL\"])
with e.connect() as c:
    rev_cds = c.execute(text(\"\"\"
        SELECT count(*) FROM community_discussion_sources
        WHERE source_url IS NOT NULL AND source_url <> ''
    \"\"\")).scalar()
    rev_questions = c.execute(text(\"\"\"
        SELECT count(DISTINCT question_id) FROM community_discussion_sources
        WHERE source_url IS NOT NULL AND source_url <> ''
    \"\"\")).scalar()
print(f\"reviewable_cds={rev_cds}\")
print(f\"distinct_reviewable_questions={rev_questions}\")
"'
```

### §3.1 Pass thresholds

| Metric | Threshold |
|---|---|
| reviewable_cds (rows with non-empty `source_url`) | **≥ 10** |
| distinct_reviewable_questions (DISTINCT `question_id` across those rows) | **≥ 10** |

Both must pass. If either is below threshold → seed more rows before review.

The 10-row CDS rule is the spec floor. The 10-distinct-question rule prevents one chatty question with many sources from satisfying the count without giving the reviewer enough variety.

## §4 Admin review

Open `gate-a1-260502-checklist.md`, fill in 10 rows. ~30 minutes.

Each row checks 6 things:
1. Card readable in <30 sec?
2. Vote bar useful?
3. Conflict warning (when present) clear?
4. Summary useful (when present)?
5. Would the admin act on this row?
6. Free-text notes if anything notable.

Then pick ONE verdict at the bottom of the checklist.

## §5 Decision matrix

| Verdict | Next action |
|---|---|
| Useful — want auto-fetch | Phase 14 (community fetcher) |
| Useful — want action buttons | Phase 16b (Ignore + Mark Reviewed) |
| Useful — both | Phase 16b first (smaller, lower-risk); fetcher follows |
| Not useful | Pause CDEA; record reasoning; defer 14/15/16b/17 indefinitely |

## §6 What is intentionally NOT in this plan

- audit_log engagement counting (Phase 16a-lite has no mutation routes; counting clicks isn't worth the complexity)
- confidence-breakdown statistics (not needed for go/no-go)
- DB metrics dashboard (not needed for 1 admin × 10 reviews)
- form-based feedback service (Markdown checklist is enough)
- automated test against prod (no mutation tests)
- pre-emptive Phase 14 / 16b code

## §7 Boundaries

- No Phase 14 / 15 / 16b / 17 code.
- No fetcher, AI, RQ worker.
- No DB schema change.
- No service restart.
- No GitHub push.
- No blogdb / blog role / /srv/blog-website / nginx / cloudflared / PG-config / Redis-config / blog.service touch.
- Read-only DB query above only — execute on user approval.

## §8 Open items

1. Is a Beta-A admin available within the next 1–2 weeks? If yes, schedule the review window. If no, seed data anyway and review later.
2. Is real community-bearing dump data available, or do we use synthetic seed for the UI smoke (provisional verdict only)?
3. After seed + review, do you want me to consolidate the verdict + decision into a `plans/reports/gate-a1-260502-verdict.md` follow-up? (Recommended for traceability.)
