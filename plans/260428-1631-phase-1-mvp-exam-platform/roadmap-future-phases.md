---
title: Future Phases — Roadmap Stub
status: stub
note: Do not detail-plan until Phase 1 has shipped and stabilized.
---

# Future Phases — Roadmap Stub

> This is a deliberate **stub**. Phase 2 and Phase 3 are summarized only. Detailed planning waits until Phase 1 exit criteria are signed off and 5+ beta users have completed full attempts.

## Phase 2 — AI Verification (target: 6–10 weeks after Phase 1)

**Goal:** Every imported question is AI-verified, evidenced, scored. Admin reviews ~10%.

Modules to add:
- HTML + PDF import (`bs4`, PyMuPDF, pdfplumber, LLM normalization fallback)
- AI Verification Worker (RQ jobs)
- Evidence Cache (`question_explanations`, `question_references`, populated by AI)
- Confidence Engine (rule-based per PRD §14)
- Source Trust Policy management UI (PRD §9)
- Review Queue (admin)
- Admin dashboard health + insight views
- Question reports (student dispute → review queue)
- Staleness & re-verification scheduler
- AI cost tracking (per-job + per-import budgets)
- Full prompt-injection hardening (PRD §22)
- WAL archiving for PITR
- Encrypted backups at rest

Cluster upgrade window: PG14 → PG16/17 before Nov 2026 EOL. Affects blog + exam together.

Exit criteria:
- ≥80% of AI-verified questions reach medium/high confidence.
- Cache hit rate ≥95% on review pages.
- Admin review load ≤15% of imports.
- Median verification <60 s/question.
- Cost per question within budget (target <$0.08 first-pass).

## Phase 3 — Learning Intelligence (target: 8–12 weeks after Phase 2)

**Goal:** The platform actively teaches.

Modules to add:
- Review / Weak-topic / Flashcard modes (full)
- Deep weakness analytics
- AI Tutor chat (bound to question + cache + glossary)
- Glossary (EN/VN bilingual) with admin approval flow
- Spaced repetition scheduler
- Near-duplicate detection via `pgvector`
- Cohort retention + topic mastery analytics

Exit criteria:
- ≥30% returning users use Tutor or Weak-topic mode.
- Spaced repetition shows measurable retention lift.
- Vietnamese coverage matches English on a target exam.

## Beyond Phase 3
Instructor accounts, billing, mobile/PWA, white-label, partner content programs.

## Re-Planning Trigger
When Phase 1 ships and 5+ beta users complete full attempts, run `/ck-plan` again with PRD §30.2 as input to detail-plan Phase 2.
