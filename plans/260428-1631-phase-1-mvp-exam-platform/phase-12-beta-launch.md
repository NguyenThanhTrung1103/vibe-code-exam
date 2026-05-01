---
phase: 12
title: Beta launch readiness & content seeding
status: pending
effort: 2-3 days
priority: high
depends_on: [08, 09, 10, 11]
---

# Phase 12 — Beta Launch Readiness & Content Seeding

## Context Links
- PRD §31.1 (Phase 1 success metrics), §37 (production readiness checklist)
- Plan overview exit criteria (`plan.md`)

## Overview
Final phase. Seed real content (200+ Fortinet NSE4 questions), run a 5-user beta, walk the production-readiness checklist, fix the issues found, sign off. This is where Phase 1 either ships or proves the scope was wrong.

**Gate — do not start Phase 12 until:** Phase **08** (attempts/scoring/reports), **09** (security hardening), **10** (backup/observability/DR gates), and **11** (deployment) are complete. Public or broad beta **must not** run on a stack that has not passed Phase 09 and Phase 10 exit criteria.

## Key Insights
- **Beta with real users is non-optional** — internal-only testing misses 80% of UX bugs. Five outside testers find the issues an engineer can't see.
- **Watch the silent failures**, not the loud ones. Loud bugs get fixed; the quiet ones (auto-save dropping the last selection, timer drift on slow networks, wrong topic breakdown when a question has no topic) are the failures that erode trust.
- **Don't treat the readiness checklist as ceremony.** Each unchecked box is a real-world risk.
- **Content quality > volume.** 100 well-tagged, well-explained Fortinet questions beat 500 raw dumps. If admin's NSE4 source has 200 OK questions and 800 messy ones, ship 200.
- **Document residual risks honestly** in the launch note. "We don't have AI verification yet" is a feature claim Phase 2 will close.

## Requirements (revised — two gates instead of one)

### Gate A — Internal Beta (5 users)
**Functional**
- **100+ curated Fortinet NSE4 questions** imported, topic-tagged, published.
- Topic taxonomy seeded (Firewall Policy, NAT, VPN, Routing, Security Profiles, Authentication, Logging, HA).
- **First 30–50 key questions have full per-option explanations**; remaining ≥80% have at least an overall explanation.
- Questions without explanation render honestly: *"No explanation provided yet — Unverified, admin-supplied."*
- Confidence badge text agreed: "Unverified — admin-supplied" for Phase 1.
- Public landing page copy + footer + ToS + Privacy + Disclaimer drafted (boilerplate acceptable; counsel pass before Gate B).
- DMCA contact + workflow live (operational, not just listed).
- 5 beta users complete ≥1 full attempt; feedback collected.
- Phase 10 internal-beta gate met (manual backup drill done; runbook exists).

### Gate B — Public Soft-Launch
**Functional**
- **200+ Fortinet NSE4 questions** published, ≥80% with at least an overall explanation.
- Top-3 issues from internal-beta feedback fixed.
- Counsel-reviewed legal pages (or documented boilerplate-acceptance from founder).
- Phase 10 public-launch gate met (automated off-site backup, retention, UptimeRobot, drill within 30 days).
- Performance smoke (1k seeded users) passes p95 targets.

**Non-functional**
- All Phase 31.1 metrics achieved (PRD).
- Practice page p95 <500 ms with 1k seeded users.
- Result page p95 <800 ms.

## Architecture
No new code modules. Final integration / data / docs phase.

```
content/
├── fortinet-nse4-import.xlsx        # the import file (NOT committed if rights-restricted)
└── topics-seed.sql                  # idempotent topic upserts

docs/
├── disclaimer.md
├── terms-of-service.md
├── privacy-policy.md
├── dmca-takedown.md
└── beta-feedback-log.md             # raw feedback notes during beta
```

## Related Code Files
**Create**
- `content/topics-seed.sql` (or Alembic seed migration) — Fortinet NSE4 topic taxonomy.
- `docs/disclaimer.md`, `terms-of-service.md`, `privacy-policy.md`, `dmca-takedown.md` (project-local; linked from public footer).
- `docs/beta-feedback-log.md` — running notes during beta.
- `tests/load/practice_load.py` — k6 or locust script for 1k-user load smoke (optional).

**Modify**
- Public footer template — links to legal pages + DMCA + version stamp.
- `app/templates/public/exam_detail.html` — show "Last imported" date, "Confidence: Unverified" tile.

## Implementation Steps

1. **Topics seed** — write idempotent topics for NSE4 (Firewall Policy, NAT, VPN, Routing, Security Profiles, FortiGate Authentication, Logging, High Availability). Run on prod.
2. **Content import**
   - Take the source NSE4 Excel.
   - Import via Phase 05 pipeline.
   - Review each batch in admin question editor.
   - Assign topics; fix typos; add per-option explanations where AI doesn't yet exist.
3. **Soft-publish** — publish the NSE4 exam after content review.
4. **Legal pages** — author/finalize disclaimer, ToS, privacy policy, DMCA takedown form/email. Link from footer.
5. **Production readiness walk-through** (PRD §37) — go through each checkbox, fix gaps:
   - Reliability (HTTPS valid, healthcheck, worker restart, autovacuum).
   - Backup/DR (drill executed, RTO/RPO documented).
   - Security (RBAC tested, rate limits live, CSP, dep scan, secrets rotated).
   - Content/legal (DMCA, footer, ToS, privacy, upload-rights, private-default).
   - Observability (Sentry, alerts, dashboards mental model).
   - Data integrity (audit log rate matches mutation rate, FK integrity, soft-delete tested).
   - Performance sanity (1k users, no N+1).
6. **Performance smoke** — target: seed 1k fake user accounts; run **k6/locust** (optional if tooling not installed). **If k6/locust is skipped:** use **manual acceptance** — all 5 beta users complete attempts without timeouts; no obvious latency regression in server logs; result/review pages load acceptably. For **Gate B (public soft-launch)**, prefer a **clearer** performance check (scripted load or monitored p95) per `plan.md` targets.
7. **Beta invite** — 5 users from cert-prep community + 2-3 internal. Ask each to complete ≥1 full NSE4 attempt + 1 question report.
8. **Feedback collection** — open Google Form or in-app modal. Log to `docs/beta-feedback-log.md` daily.
9. **Iterate one cycle** — fix the top-3 issues from feedback before public soft-launch.
10. **Launch comms** — status page (or simple uptime page); on-call rotation (founder); rollback plan documented.
11. **Sign-off** — record in `dr-drill-log.md` + `docs/beta-feedback-log.md` that exit criteria are met. Update `plan.md` status to `completed`.

## Todo List
**Gate A — internal beta**
- [ ] NSE4 topics seeded (idempotent)
- [ ] 100+ NSE4 questions imported and topic-tagged
- [ ] First 30–50 key questions have full per-option explanations
- [ ] ≥80% of imported questions have at least an overall explanation
- [ ] Honest "No explanation provided yet" rendering verified
- [ ] NSE4 exam published
- [ ] Disclaimer, ToS, Privacy, DMCA drafted and linked from footer
- [ ] DMCA contact monitored
- [ ] 5 beta users completed full attempt
- [ ] Beta feedback collected in `docs/beta-feedback-log.md`
- [ ] Manual backup drill executed (Phase 10 Gate A)

**Gate B — public soft-launch**
- [ ] 200+ NSE4 questions published, 80%+ with overall explanations
- [ ] Top-3 internal-beta issues fixed
- [ ] Legal pages reviewed or boilerplate-accepted by founder
- [ ] Production-readiness checklist all green (PRD §37)
- [ ] Performance smoke passes (1k users, p95 <500 ms)
- [ ] Automated off-site backup + retention live (Phase 10 Gate B)
- [ ] On-call rotation + rollback plan documented
- [ ] Sign-off entries in dr-drill-log + beta-feedback-log
- [ ] `plan.md` status updated to `completed`

## Success Criteria
**MVP exit (PRD §31.1):**
- ≥200 questions imported in <10 min.
- 5 beta users completed ≥1 full attempt.
- Result/review screen passes "no-coaching" usability — beta tester reads it without help from the founder.
- ≥70% of beta users say per-question explanations are useful.
- Excel import error rate <5% on the standard template.
- No critical data loss in monthly backup/restore drill.
- All admin question/exam mutations appear in audit log.
- 100% of imports default to private; explicit publish required.

## Risk Assessment
- **Content rights** — if NSE4 source is from a copyright-restricted dump, do NOT publish. Use first-party authored content even if smaller. Per PRD §26.
- **Beta tester recruitment** is a real bottleneck. Start outreach early in Phase 11.
- **Performance smoke surprises** — 1k seeded user practice page may surface N+1 queries. Mitigate: profile early; add `selectinload()` for known-busy joins.
- **Last-minute scope creep** — "let's add weak-topic mode for beta" is the canonical Phase 1 scope-killer. Refuse; document as Phase 3 idea.
- **Audit log volume during seed** — 200+ imports + edits could produce thousands of rows. Acceptable; designed for it.

## Security Considerations
- All Phase 09 + Phase 11 hardening verified end-to-end with real traffic.
- DMCA contact email staffed by a real person from launch day.
- Privacy policy reflects what we actually collect: email, attempt analytics, log data.
- Beta users informed they're testing pre-release — set expectations that data may be reset.
- 2FA is **not** in MVP — explicitly note as residual risk in launch notes.

## Next Steps
Once Phase 1 sign-off complete:
1. Mark `plan.md` `status: completed`.
2. Run `/ck-plan archive` to journal Phase 1 outcomes.
3. Run `/ck-plan` against PRD §30.2 to detail-plan Phase 2 (AI verification + evidence cache + HTML/PDF import).
4. Re-decide founder questions still open from PRD §35 (notably TTL default, AI provider choice, two-tier model strategy).
