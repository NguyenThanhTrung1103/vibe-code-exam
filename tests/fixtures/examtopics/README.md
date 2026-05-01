# ExamTopics Parser Fixtures

**These fixtures are SYNTHETIC, sanitized, structure-only stubs.**

## Provenance

- **Source:** Hand-crafted minimal HTML matching public structural conventions of community discussion dump pages (data-id attribute, voted-answers-tally JSON block, discussion link). Author: this project; NOT scraped from any live page.
- **Capture / authored date:** 2026-04-30 (locked to `PARSER_SCHEMA_VERSION = "2026-04-30"` in `app/services/community_dump_parser.py`).
- **Scope:** Phase 13 parser regression testing only. Used to detect structural drift if a future site rewrite changes selectors.

## Sanitization rules (enforced)

- ❌ NO real user handles, usernames, emails, IPs.
- ❌ NO real comment bodies. Comment text replaced by short placeholder strings (`"Lorem placeholder."`).
- ❌ NO real exam vendor question content. Question stems replaced by generic placeholder (`"Sample question stem placeholder."`).
- ❌ NO long raw HTML / pages copied verbatim.
- ✅ ONLY the structural CSS classes / attributes / element nesting needed for selector validation.
- ✅ ALL fixtures < 5KB to keep parser tests fast and to make sanitization auditable on inspection.

## Files

| File | Purpose |
|---|---|
| `2026-04-30-fortinet-q1.html` | Happy path: 4 options A–D, vote A=21 D=6, A is given_answer. High community agree. |
| `2026-04-30-fortinet-q2.html` | Split case: 5 options A–E, vote A=8 D=10, A is given_answer. Community disagrees. |
| `2026-04-30-fortinet-q3-multivote.html` | Multi-correct (A+C). 4 options. Vote evenly split. Tests answer joining. |
| `2026-04-30-fortinet-q4-no-discussion.html` | No `<a href="/discussions/...">`. Tests graceful NULL for `discussion_url`. |
| `2026-04-30-fortinet-q5-6options.html` | 6 options A–F to test dynamic vote labels (NOT hardcoded A–E). |

## Drift policy

When ExamTopics changes their HTML structure:

1. Author NEW fixtures with new date prefix (e.g. `2026-09-15-*.html`).
2. Bump `PARSER_SCHEMA_VERSION` in `app/services/community_dump_parser.py`.
3. Update parser selectors.
4. Run regression tests against BOTH old + new fixtures (parser must report version mismatch on old fixtures, success on new).
5. Document the structural diff in this README under "Drift history".

## Drift history

| Version | Date | Notes |
|---|---|---|
| 2026-04-30 | 2026-04-30 | Initial author. Structure: `[data-id]`, `.voted-answers-tally`, `a[href*="/discussions/"]`. |

## Disclaimer

These fixtures contain NO copyrighted content. They are hand-authored minimal stubs documenting only the public structural pattern. They are NOT to be redistributed outside this repository. They are NOT a re-publishing of any third-party site content.
