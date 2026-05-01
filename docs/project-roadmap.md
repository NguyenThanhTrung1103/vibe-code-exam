# Project Roadmap

Live phase tracking. Update after each phase completion.

> Source plan: `plans/260428-1631-phase-1-mvp-exam-platform/plan.md`

## Phase 1 MVP (4–6 weeks, in progress)

| # | Phase | Status | Completed | Effort | Owner |
|---|---|---|---|---|---|
| 01 | Project scaffolding & local dev env | ✅ Complete | 2026-04-29 | 2 d | dev |
| 02 | Database migrations & PG co-tenant setup | ✅ Complete | 2026-04-29 | 2–3 d | dev |
| 03 | Auth, RBAC, audit log foundation | ✅ Complete | 2026-04-29 | 3–4 d | dev |
| 04 | Catalog: provider/course/exam/topic CRUD | ✅ Complete | 2026-04-29 | 3–4 d | dev |
| 05 | Excel import pipeline w/ dedup + sanitization | ✅ Complete | 2026-04-29 | 5–6 d | dev |
| 06 | Question bank CRUD & manual editor | ✅ Complete | 2026-04-29 | 2–3 d | dev |
| 07 | Practice & exam mode delivery | ✅ Complete | 2026-04-29 | 4–5 d | dev |
| 08 | Attempts, scoring, result/review screen | ✅ Complete | 2026-04-29 | 3–4 d | dev |
| 09 | Security hardening & rate limiting | ✅ Complete | 2026-04-30 | 2–3 d | dev |
| 10 | Backup, observability, DR drill | ✅ Complete | 2026-04-30 | 2 d | dev |
| 11 | Deployment on LXC w/ Nginx + systemd | ✅ Complete (loopback) | 2026-04-30 | 2–3 d | dev |
| 12 | Beta launch readiness + content seeding | ✅ Complete (Gate-A scaffolding) | 2026-04-30 | 2–3 d | dev |

**Realistic effort:** 32–42 working days for solo dev (≈6 weeks).

## Exit gates

### Gate A — Internal Beta (5 users)

Status: not yet attempted.

- [ ] 1 vendor (Fortinet) seeded
- [ ] ≥100 curated, topic-tagged questions imported
- [ ] First 30–50 questions have full per-option explanations
- [ ] ≥80% have at least an overall explanation
- [ ] 5 internal beta users complete a full attempt
- [ ] Admin imports 100+ questions in <10 min
- [ ] All admin question/exam mutations appear in `audit_logs`
- [ ] 100% of imports default to `private`
- [ ] Manual `pg_dump` + `pg_restore` drill executed and recorded
- [ ] Excel import error rate <5% on the canonical template
- [ ] Idempotent confirm verified

### Gate B — Public Soft-Launch

Status: not yet attempted.

- [ ] ≥200 published questions, ≥80% with overall explanations
- [ ] Top-3 internal-beta issues fixed
- [ ] Practice page p95 <500 ms; result page p95 <800 ms (1k seeded users)
- [ ] Automated off-site backup live with 7d/4w/6m retention
- [ ] Restore drill repeated within last 30 days
- [ ] Counsel-reviewed legal pages or documented founder boilerplate

## Future phases (out of Phase 1)

Tracked in `plans/260428-1631-phase-1-mvp-exam-platform/roadmap-future-phases.md`:

- **Phase 2** — AI verification, evidence cache, HTML/PDF import.
- **Phase 3** — AI tutor, glossary, weak-topic, flashcards, spaced
  repetition.

Schema-only stubs for Phase 2/3 already exist (created in Phase 02) so
future phases don't pay migration churn:
`source_domains`, `ai_verification_jobs`, `evidence_fetch_logs`,
`question_duplicate_groups`, `glossary_terms`.

## Cross-cutting risks

- **Scope creep into Phase 2** (AI features) is the #1 risk.
- **Excel template drift** — admin's real Excel files won't match
  canonical template. Mapping UI is mandatory in Phase 05.
- **PG14 EOL Nov 2026** — plan PG16/17 cluster upgrade for Phase 2.
- **HTMX learning curve** — budgeted into Phase 01 (now done).
