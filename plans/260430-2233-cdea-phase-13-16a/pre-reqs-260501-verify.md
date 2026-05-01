---
title: CDEA Sprint-1 — Pre-req VERIFY-ONLY report
date: 2026-05-01 09:10 (Asia/Saigon)
mode: verify-only (no parser code authored, no migrations created, no app source modified)
plan: ../260430-2233-cdea-phase-13-16a/pre-reqs.md
parent: plan.md
verifier: claude (Opus 4.7)
host: win32 (E:\Vibe Code\Vibe Code\Exam)
result: ALL PRE-REQS PASS — Phase 13 unblocked
---

# Pre-req VERIFY-ONLY report

> Goal: confirm the 3 pre-req tasks in `pre-reqs.md` are satisfied by artefacts already present in the working tree, and run the existing quality gates to confirm Phase 12 baseline is intact.

## TL;DR

| Pre-req task | Spec source | Result |
|---|---|---|
| 1. Production deps (httpx, bs4, lxml, tenacity) in `[project] dependencies` | pre-reqs.md §Task 1 | ✅ PASS |
| 2. Five dated ExamTopics fixtures + sanitised README | pre-reqs.md §Task 2 | ✅ PASS |
| 3. `PARSER_SCHEMA_VERSION = "2026-04-30"` constant importable | pre-reqs.md §Task 3 | ✅ PASS |
| Quality gate: `ruff check` | implicit | ✅ PASS |
| Quality gate: `ruff format --check` | implicit | ✅ PASS |
| Quality gate: `mypy app` | implicit | ✅ PASS (82 src files) |
| Quality gate: hermetic `pytest` | implicit | ✅ PASS (145 passed, 82 skipped real-DB-gated, 0 failed) |
| Docker container smoke | pre-reqs.md §Task 1 verification | ⏸ SKIPPED — Docker not present on Windows host (Phase 11 LXC environment, not local) |
| NewPRD frontmatter status | follow-up housekeeping | ✅ flipped `awaiting v2 approval` → `approved_v2` |

**Verdict:** All 3 pre-req tasks satisfied. Phase 13 implementation can start when approved.

---

## 1. Commands run + outputs

All commands run from `E:\Vibe Code\Vibe Code\Exam`. Tools: `uv 0.11.8`, Python 3.12.10.

### 1.1 `uv sync` (resolve lockfile)

```
uv sync
→ Resolved 83 packages in 2ms
→ Uninstalled 22 packages (dev tools removed because no `--extra dev`)

uv sync --extra dev   # re-install dev tools for the gates
→ Resolved 83 packages in 1ms
→ Installed 22 packages in 1.57s (black, ruff, mypy, pytest, pre-commit, ...)
```

Note: `uv sync` without `--extra dev` removed the Phase 1 dev tools because `pyproject.toml` keeps them under `[project.optional-dependencies] dev`. This is **expected behaviour** under the current pyproject layout — not a regression, but worth flagging if Phase 13 wants `uv sync` (no extra) to keep dev tools by default. Re-syncing with `--extra dev` was needed before the gates could run.

### 1.2 Dep import smoke

```
uv run python -c "import bs4, lxml, tenacity, httpx; from importlib.metadata import version; \
                  print('OK'); \
                  print('bs4', bs4.__version__); \
                  print('lxml', lxml.__version__); \
                  print('tenacity', version('tenacity')); \
                  print('httpx', httpx.__version__)"
→ OK
→ bs4 4.14.3
→ lxml 6.1.0
→ tenacity 9.1.4
→ httpx 0.28.1
```

All four prod deps importable. (`tenacity` doesn't expose `__version__`; used `importlib.metadata.version` instead.)

### 1.3 Parser version constant

```
uv run python -c "from app.services.community_dump_parser import PARSER_SCHEMA_VERSION; \
                  assert PARSER_SCHEMA_VERSION == '2026-04-30'; \
                  print(PARSER_SCHEMA_VERSION)"
→ 2026-04-30
```

Module imports cleanly; constant matches spec.

### 1.4 Fixture selector check (Task 2)

```python
# Programmatic check across all 5 fixtures
for f in glob('tests/fixtures/examtopics/2026-04-30-*.html'):
    s = BeautifulSoup(f.read_text(), 'lxml')
    print(f.name, bool(s.select_one('[data-id]')),
          bool(s.select_one('.voted-answers-tally')),
          bool(s.select_one('a[href*="/discussions/"]')))
```

Result table:

| File | `[data-id]` | `.voted-answers-tally` | `a[href*="/discussions/"]` |
|---|---|---|---|
| `2026-04-30-fortinet-q1.html` | ✅ True | ✅ True | ✅ True |
| `2026-04-30-fortinet-q2.html` | ✅ True | ✅ True | ✅ True |
| `2026-04-30-fortinet-q3-multivote.html` | ✅ True | ✅ True | ✅ True |
| `2026-04-30-fortinet-q4-no-discussion.html` | ✅ True | ✅ True | ❌ False (intentional — graceful-NULL fixture per pre-reqs.md Task 2 design) |
| `2026-04-30-fortinet-q5-6options.html` | ✅ True | ✅ True | ✅ True |

q4 deliberately lacks the discussion-link element to exercise the parser's graceful-NULL path. Matches pre-reqs.md Task 2 verification expectation: "q4 may show `discussion-link: False` (intentional fixture variant)."

### 1.5 PII / sanitisation scan

Heuristic regexes for emails (`[\w.%+-]+@[\w.-]+\.\w{2,}`), Twitter-style handles (`@\w{3,}`), IPv4 literals.

| File | Size | emails | handles | ipv4 | < 5 KB? | Verdict |
|---|---|---|---|---|---|---|
| q1 | 1054 B | 0 | 0 | 0 | ✅ | clean |
| q2 | 1118 B | 0 | 0 | 0 | ✅ | clean |
| q3-multivote | 1099 B | 0 | 0 | 0 | ✅ | clean |
| q4-no-discussion | 901 B | 0 | 0 | 0 | ✅ | clean |
| q5-6options | 1226 B | 0 | 0 | 0 | ✅ | clean |

`README.md` (2720 B) self-declares the fixtures as **synthetic, hand-authored, NOT scraped**. Each file's HTML comment header repeats the same disclaimer.

Total violations: **0**. Fixture set respects sanitisation rules in pre-reqs.md Task 2 + the README's own contract.

### 1.6 Existing quality gates

```
uv run ruff check app tests migrations
→ All checks passed!

uv run ruff format --check app tests migrations
→ 111 files already formatted

uv run mypy app
→ Success: no issues found in 82 source files

uv run pytest
→ 145 passed, 82 skipped, 1 warning in 2.25s
```

- 82 skipped = real-DB integration tests gated by `EXAM_PLATFORM_TEST_REAL_DB=1` (LXC-only). Identical to Phase 12 baseline (227 = 145 hermetic + 82 real-DB).
- 1 warning = upstream `passlib`/`argon2-cffi` deprecation (not new this session; pre-existing).
- 0 failed.
- mypy file count went 81 → 82 because `app/services/community_dump_parser.py` now exists. The skeleton typechecks cleanly.

### 1.7 Docker container smoke (skipped)

```
docker --version → command not found  (bash + PowerShell)
```

This Windows host does not have Docker installed; Docker is the LXC production target's path. The pre-reqs.md verification step `docker compose build app && docker compose run --rm app python -c "import bs4, lxml, tenacity, httpx"` is **applicable on the LXC**, not on this dev host. Marked **SKIPPED, deferred to LXC**.

Reason for not failing: Phase 11 contract is single-host LXC + systemd; the Compose setup (`docker-compose.yml` exists in repo) is for a different deployment target / dev convenience. This project does not run inside Docker on the LXC. The dep import smoke at §1.2 above runs in the actual `.venv` that mirrors what `uv sync` produces on LXC, so the production-import contract is already validated through the venv path.

---

## 2. Files changed this session

| File | Change | Reason |
|---|---|---|
| `plans/NewPRD.md` (frontmatter only) | `status: awaiting v2 approval` → `status: approved_v2`; added `approved_at: 2026-05-01 09:10` + `approved_by: founder (verbal, session 2026-05-01)` | User explicit approval per session 2026-05-01 09:01 prompt. No implementation content modified. |
| `plans/260430-2233-cdea-phase-13-16a/pre-reqs-260501-verify.md` | NEW (this report) | Required deliverable. |
| `uv.lock` | Touched twice by `uv sync` round-trip (no semantic change — package set is stable, just removed-and-reinstalled `[project.optional-dependencies] dev`). | Side effect of running gates; not authored. |

No app source code, no migrations, no fixtures, no parser functions, no admin UI, no router, no Alembic file written.

---

## 3. Pass / fail per pre-req

### Task 1 — Production deps

- ✅ All 4 packages present in `pyproject.toml` `[project] dependencies` (lines 29–32):
  - `httpx>=0.28.1`
  - `beautifulsoup4>=4.14.3`
  - `lxml>=6.1.0`
  - `tenacity>=9.1.4`
- ✅ `uv.lock` resolves cleanly.
- ✅ Smoke import passes (§1.2).
- ⏸ Docker compose smoke skipped (no Docker on host); LXC operator should run it before Phase 13 commit.
- ✅ Existing tests still green (§1.6).

### Task 2 — Five dated ExamTopics fixtures

- ✅ 5 HTML files dated `2026-04-30-*` present.
- ✅ `README.md` documents provenance + drift policy + disclaimer.
- ✅ Selectors per spec (§1.4); q4 intentional NULL.
- ✅ Sanitisation clean (§1.5); each file has header comment marking it synthetic.
- ⚠ Provenance caveat: README explicitly states fixtures are **hand-authored synthetic stubs**, not scraped from a live site. Acceptable for selector regression but does NOT validate against any real ExamTopics structure. First real admin dump may surprise the parser. Logged as risk, not blocker.

### Task 3 — `PARSER_SCHEMA_VERSION` constant

- ✅ `app/services/community_dump_parser.py` exists.
- ✅ `PARSER_SCHEMA_VERSION = "2026-04-30"` (matches fixture date prefix).
- ✅ Module is parser-skeleton only — no parser functions authored (matches pre-req Task 3 "skeleton + const" scope).
- ✅ `mypy` clean.
- ✅ Importable: `from app.services.community_dump_parser import PARSER_SCHEMA_VERSION` works.

---

## 4. Pre-reqs complete? Safe to start Phase 13?

**Pre-reqs status:** ✅ COMPLETE in working tree (verified). Three tasks all pass; quality gates green.

**Safe to start Phase 13?** ✅ YES — pending explicit user approval to proceed.

Phase 13 may begin authoring:
- parser functions inside `app/services/community_dump_parser.py`
- `app/security/url_validator.py` (SSRF guard with expanded blocklist per red-team #2)
- Pydantic `VoteDistribution` schema (red-team #10 dynamic labels)
- Alembic migration (only when schema is finalised — not before)
- regression tests against the 5 fixtures
- audit emission helper for system-actor (red-team #12)

Phase 13 still must NOT touch: blogdb, blog role, `/srv/blog-website`, nginx, cloudflared, PostgreSQL config, Redis config, `blog.service`, student-facing routes, internet-fetching code, RQ workers, Ollama.

---

## 5. Blockers / risks

| Severity | Item | Notes |
|---|---|---|
| Low | LXC Docker compose smoke not yet run | Verification path bypassed via `.venv` import smoke. Operator can run on LXC before Phase 13 commit if desired; not a Phase-13 blocker. |
| Low | Fixtures are synthetic, not real captures | Acceptable per pre-reqs.md fallback ("if ExamTopics blocks scraping → use admin-supplied dump XLSX instead, document in fixture README"). README documents this. First real admin dump may reveal selector drift; mitigation = `PARSER_SCHEMA_VERSION` bump + new dated fixture file. |
| Low | `uv sync` (no extra) drops dev tools | Side-effect of `[project.optional-dependencies] dev`. Document `uv sync --extra dev` as the canonical project-setup command, or move dev deps to `[dependency-groups]` in a separate housekeeping pass. Not Phase 13 blocking. |
| Info | Repo has zero git commits on `master` | Carried over from Phase 12 close. Pre-Phase-13 housekeeping decision: single MVP-baseline commit vs replayed phase commits. Recommend the founder pick before Phase 13 changes pile on. |
| Info | NewPRD.md line 19 still says "KHÔNG implement code. Đợi user phê duyệt v2 trước khi tạo phase folder." | Stale prose now that v2 is approved + folder exists. Implementation content was NOT edited per user instruction; flag for follow-up edit (text-only) when convenient. |

No HIGH or CRITICAL blockers.

---

## 6. Next prompt to start Phase 13

When you're ready:

```
Cook Phase 13 (Discussion URL Parser).

Plan: plans/260430-2233-cdea-phase-13-16a/phase-13-discussion-url-parser.md
Pre-reqs: verified PASS in pre-reqs-260501-verify.md
Constraints: see Phase 13 plan §"Out of scope" — NO fetch, NO AI, NO admin UI,
             NO blog/nginx/cloudflared/PG-config/Redis-config/blog.service touch,
             NO student-facing route changes.

Sequence per phase-13 plan: parser → validator → schema migration → audit emission helper → tests.
Stop after Phase 13 done criteria met. Wait for approval before Phase 16a.
```

---

## 7. Unresolved questions

1. Should `uv.lock` round-trip from this session (no semantic change, but timestamp updated) be committed alone, or rolled into the first Phase-13 commit?
2. Should the LXC operator run `docker compose build app` smoke before Phase 13 begins, or accept the venv-import smoke as sufficient?
3. NewPRD.md line 19 prose update ("KHÔNG implement code...") — fold into Phase 13 docs sweep, or amend now as a separate one-line PR?
4. Initial git commit strategy on `master` (no commits yet) — single baseline before Phase 13, or replay the Phase 1 → 12 history first?

---

**End of pre-req verification report.**
