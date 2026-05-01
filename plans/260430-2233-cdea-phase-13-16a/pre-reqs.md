---
title: CDEA Sprint-1 — Pre-requisite tasks (BLOCKING Phase 13)
status: pending
effort: ~0.5 day
blocks: phase-13-discussion-url-parser.md
---

# Pre-requisites (BLOCKING)

> **Phase 13 KHÔNG được bắt đầu cho đến khi 3 pre-req task dưới đây hoàn thành và verified.** Lý do: red-team Critical findings #3 (deps missing) + #4 (HTML contract unverified).

## Context links
- Red-team report (Findings #3, #4): [`../reports/redteam-260430-2211-cdea-newprd.md`](../reports/redteam-260430-2211-cdea-newprd.md)
- Plan v2 §5.2 (Pre-req section): [`../NewPRD.md`](../NewPRD.md)
- Existing pyproject.toml: [`../../pyproject.toml`](../../pyproject.toml)

---

## Task 1 — Add production dependencies

### Why
Plan v2 stack lists `httpx`, `beautifulsoup4`, `lxml`, `tenacity` nhưng `pyproject.toml` hiện tại:
- KHÔNG có `bs4`, `lxml`, `tenacity` ở bất kỳ section nào.
- `httpx>=0.28` chỉ ở `[project.optional-dependencies] dev` (KHÔNG vào production image).

→ Phase 13 day-1 import sẽ fail trên production target.

### Action
1. Run: `uv add httpx beautifulsoup4 lxml tenacity` (vào `[project] dependencies`, KHÔNG dev-extra).
2. Pin versions explicit (`>=` lower bound + tested upper bound).
3. Run `uv sync` để regenerate `uv.lock`.
4. Commit `pyproject.toml` + `uv.lock` thay đổi.

### Verification (must pass before marking task done)
```bash
# Verify deps in production target image
docker compose build app
docker compose run --rm app python -c "import bs4, lxml, tenacity, httpx; print('OK')"
```
Expected output: `OK`. Nếu fail → debug Dockerfile build.

### Effort
~30 minutes.

### Done criteria
- [ ] 4 packages thêm vào `[project] dependencies` of `pyproject.toml`.
- [ ] `uv.lock` regenerated.
- [ ] Production image smoke-test pass: `python -c "import bs4, lxml, tenacity, httpx"` returns `OK`.
- [ ] Existing tests still pass: `uv run pytest` green.

---

## Task 2 — Capture 5 dated ExamTopics HTML fixtures

### Why
Red-team Finding #4: parser dựa trên 3 selector cụ thể (`data-id`, `voted-answers-tally`, `discussion_url`) nhưng KHÔNG có fixture, KHÔNG có version-pin → parser silently NULL khi site rewrite HTML.

### Action
1. Tạo dir: `tests/fixtures/examtopics/`.
2. Capture 5 question pages từ ExamTopics (manual, browser save-as HTML hoặc `curl` với UA của bot — ưu tiên ngày-xếp-tên):
   - `tests/fixtures/examtopics/2026-04-30-fortinet-q1.html`
   - `tests/fixtures/examtopics/2026-04-30-fortinet-q2.html`
   - `tests/fixtures/examtopics/2026-04-30-fortinet-q3-multivote.html` (chọn câu có vote split)
   - `tests/fixtures/examtopics/2026-04-30-fortinet-q4-no-discussion.html` (chọn câu KHÔNG có discussion link để test graceful NULL)
   - `tests/fixtures/examtopics/2026-04-30-fortinet-q5-6options.html` (chọn câu 6 option để test dynamic labels — nếu có; nếu không có 6-option thì pick 5-option Cisco/AWS dump).
3. Document fixture provenance trong `tests/fixtures/examtopics/README.md`:
   - Source URL pattern (REDACT actual paths nếu cần).
   - Capture date.
   - Selector samples confirmed present.
4. Commit fixtures với `.gitignore` exception nếu cần.

### Constraints (legal/copyright)
- Strip user PII / handles trước commit.
- Truncate full HTML nếu > 100KB per file (keep enough for selector validation, not full re-publish).
- `tests/fixtures/examtopics/README.md` add disclaimer: fixtures for parser regression only, not for redistribution.

### Verification
```bash
ls -la tests/fixtures/examtopics/
# 5 .html files + README.md
python -c "from bs4 import BeautifulSoup; \
  html = open('tests/fixtures/examtopics/2026-04-30-fortinet-q1.html').read(); \
  s = BeautifulSoup(html, 'lxml'); \
  print('data-id:', bool(s.select_one('[data-id]'))); \
  print('vote-tally:', bool(s.select_one('.voted-answers-tally'))); \
  print('discussion-link:', bool(s.select_one('a[href*=\"/discussions/\"]')))"
```
Expected: 3× `True` for q1-q3; q4 may show `discussion-link: False` (intentional fixture variant).

### Effort
~1 hour.

### Done criteria
- [ ] 5 HTML files in `tests/fixtures/examtopics/` with `2026-04-30-` date prefix.
- [ ] `tests/fixtures/examtopics/README.md` documents provenance + disclaimer.
- [ ] Selector verification command (above) prints expected outputs.
- [ ] PII / user handles stripped from fixtures.

---

## Task 3 — Define `PARSER_SCHEMA_VERSION` constant

### Why
Red-team Finding #4: hard `parse_error` (KHÔNG silent NULL) khi site HTML drift. Cần 1 const để track parser contract version.

### Action
File: `app/services/community_dump_parser.py` (sẽ tạo trong Phase 13). Trong pre-req chỉ define skeleton placeholder + const + docstring.

```python
"""Phase 13 — community dump parser.

Parses HTML/Excel for community discussion signals:
  external_question_id, discussion_url, vote_distribution, discussion_count.

PARSER_SCHEMA_VERSION pinned to fixture capture date.
Bump version when ExamTopics HTML structure changes; add new fixtures dated to bump date.
"""

from __future__ import annotations

PARSER_SCHEMA_VERSION = "2026-04-30"
"""Pinned to fixture capture date (`tests/fixtures/examtopics/{VERSION}-*.html`).

When site HTML drifts:
  1. Capture new fixtures with new date prefix.
  2. Bump this constant.
  3. Update parser selectors.
  4. Run regression tests against BOTH old + new fixtures.
"""

# (Phase 13 implementation will fill in parser functions below.)
```

**Note:** Pre-req chỉ tạo file skeleton + const. Parser functions (Phase 13) chưa viết.

### Verification
```bash
python -c "from app.services.community_dump_parser import PARSER_SCHEMA_VERSION; \
  assert PARSER_SCHEMA_VERSION == '2026-04-30'; print('OK')"
```

### Effort
~15 minutes.

### Done criteria
- [ ] `app/services/community_dump_parser.py` created with `PARSER_SCHEMA_VERSION = "2026-04-30"`.
- [ ] Module imports cleanly: `python -c "from app.services.community_dump_parser import PARSER_SCHEMA_VERSION"`.
- [ ] No parser functions yet (Phase 13 will add).

---

## Sequence + verification

```bash
# 1. Deps update
uv add httpx beautifulsoup4 lxml tenacity
uv sync
docker compose build app
docker compose run --rm app python -c "import bs4, lxml, tenacity, httpx; print('OK')"

# 2. Fixtures
mkdir -p tests/fixtures/examtopics
# (manual capture 5 .html files + README.md)
ls -la tests/fixtures/examtopics/

# 3. PARSER_SCHEMA_VERSION
# (create app/services/community_dump_parser.py with const)
uv run python -c "from app.services.community_dump_parser import PARSER_SCHEMA_VERSION; print(PARSER_SCHEMA_VERSION)"

# 4. Run existing test suite — must remain green
uv run pytest
uv run ruff check .
uv run mypy app
```

## Risk assessment
- **Low:** deps update is purely additive, no version conflict expected (httpx already in dev-extra).
- **Low-medium:** fixture capture depends on manual web browsing; if ExamTopics blocks scraping → use admin-supplied dump XLSX instead, document in fixture README.
- **Low:** `PARSER_SCHEMA_VERSION` const is informational; bump policy documented in module docstring.

## Security notes
- KHÔNG commit fixtures với PII.
- KHÔNG commit fixtures với personal email / handle.
- Fixtures KHÔNG được publish to external repo public — keep internal only.

## Next steps
After all 3 tasks pass verification → Phase 13 implementation can start. See [`phase-13-discussion-url-parser.md`](phase-13-discussion-url-parser.md).
