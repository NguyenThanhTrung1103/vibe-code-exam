# Beta Feedback Log

Append entries below as beta users complete attempts.

| Date (UTC) | Tester | Attempt(s) | Issues raised | Severity | Status |
|------------|--------|------------|---------------|----------|--------|

## How to log a session

1. Tester completes ≥ 1 full attempt + ≥ 1 question report.
2. Operator copies feedback (in-app reports + email/form responses)
   into a row above.
3. Each row gets:
   - **Severity** — `blocker | major | minor | nit`.
   - **Status** — `open | triaged | fixed | wontfix`.
4. Top-3 by severity get a fix before any subsequent gate.

## Phase 12 Gate-A exit requirement

* ≥ 5 beta users have completed ≥ 1 full attempt each.
* Top-3 issues are `triaged` or `fixed`.
* No `blocker` row left in `open` status.

## Phase 12 Gate-B exit requirement

* All Gate-A criteria.
* Top-3 issues from internal beta are `fixed`.
* Performance smoke (1k seeded users) signed off.
