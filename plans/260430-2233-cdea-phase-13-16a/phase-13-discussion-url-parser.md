---
title: Phase 13 — Discussion URL Parser
status: pending
priority: high (Sprint-1 blocker for Phase 16a)
effort: 3–4 working days (incl. 30% buffer)
depends_on: pre-reqs.md (BLOCKING)
blocks: phase-16a-admin-community-tab-readonly.md (schema migration must apply first)
---

# Phase 13 — Discussion URL Parser

## Context links
- Pre-reqs: [`pre-reqs.md`](pre-reqs.md)
- Design doc v2 §5: [`../NewPRD.md`](../NewPRD.md)
- Schema spec v2 §10: [`../NewPRD.md`](../NewPRD.md)
- Red-team report: [`../reports/redteam-260430-2211-cdea-newprd.md`](../reports/redteam-260430-2211-cdea-newprd.md)
- Existing import service: [`../../app/services/import_service.py`](../../app/services/import_service.py)
- Existing excel_parser: [`../../app/services/excel_parser.py`](../../app/services/excel_parser.py)
- Existing audit writer: [`../../app/audit/writer.py`](../../app/audit/writer.py)

## Overview

**Priority:** High — blocks Phase 16a admin tab.

**Brief:** Khi admin import HTML/Excel dump, parser tách 4 community-signal fields per row, validate qua Pydantic, lưu vào `import_items.normalized_data` JSONB + tạo `community_discussion_sources` candidate row (status=`pending`).

**KHÔNG fetch Internet, KHÔNG gọi AI.** Pure parsing.

## Key insights (từ research + red-team)

1. ExamTopics HTML structure (`data-id`, `voted-answers-tally`, `discussion_url`) là third-party contract — parser phải pin version qua `PARSER_SCHEMA_VERSION` const + dated fixtures (red-team #4).
2. Vote labels NOT hardcoded A-E — Cisco/Fortinet 6-option questions exist (red-team #10). Pydantic `VoteDistribution` schema validate dynamic labels with int range 0–10000.
3. Failed selector → hard `import_item_status='error'` với `error_message="parse_error: <selector>"` — NEVER silent NULL (red-team #4).
4. URL validation phải defense-in-depth ngay tại normalize step (Phase 13) AND fetch step (Phase 14) — red-team #2.
5. CDS row FK `ON DELETE RESTRICT` (not CASCADE) + relink logic by `external_question_id` để re-import không orphan cache (red-team #6).
6. Audit log emission từ system actor dùng `write_audit_log` với `actor_type=ActorType.system, actor_id=None`. Phase 13 chạy trong FastAPI request context (admin import flow), nên `request_id` đến từ middleware.

## Requirements

### Functional
- Parse Excel rows với cột optional: `discussion_url`, `vote_a..vote_e..vote_*`, `external_question_id`, `discussion_count`.
- Parse HTML inline blocks trong Excel cell (BeautifulSoup) nếu admin paste HTML qua field — graceful, không fail nếu thiếu.
- Validate URL qua `app/security/url_validator.py` SSRF guard (Phase 13 ship version với expanded blocklist).
- Validate vote distribution qua Pydantic `VoteDistribution`.
- Compute `total_votes` regular INT column (NOT GENERATED).
- Insert/update CDS row với UNIQUE `(question_id, source_name, source_url)`.
- Re-import same `external_question_id` → re-link `question_id` thay vì duplicate.
- Re-import với content_hash khác → auto-reset `approved_for_student=false` + audit `community_source.relinked_text_changed`.
- Emit audit `community_source.candidate_created` (system actor) per CDS row.

### Non-functional
- Coverage ≥80% on parser + validator modules.
- Parser handles 1000-row import without OOM (streaming Excel via existing `openpyxl read_only`).
- Schema migration zero-downtime: only adds tables/enums + 1 column on `questions`.

### Out of scope
- HTTP fetch (Phase 14).
- Analyzer / community_answer computation (Phase 15).
- Admin UI (Phase 16a separate file).
- Ollama integration (Appendix A only).
- Manual official-reference CRUD (Phase 18).

## Architecture

### Component diagram

```
admin upload Excel/HTML
        │
        ▼
import_service.parse_and_stage()  (existing, extended)
        │
        ├── excel_parser.stream_rows()       (existing, accept new fields)
        │
        ├── community_dump_parser.parse_html_block()  (NEW Phase 13)
        │       └── BS4 + PARSER_SCHEMA_VERSION
        │
        ├── import_normalizer.normalize_row()  (extended)
        │       └── url_validator.validate()  (NEW Phase 13, expanded SSRF blocklist)
        │
        ├── schemas/community.VoteDistribution  (NEW Phase 13)
        │       └── Pydantic int validation
        │
        ├── import_validator.validate_row()  (existing, extended for community fields)
        │
        └── store: import_items.normalized_data JSONB
                  + community_discussion_sources row (NEW Phase 13)
                  + audit_log: community_source.candidate_created (NEW)
```

### Data flow

1. Admin import Excel → wizard upload → mapping → preview → confirm.
2. `confirm_import` loop per row:
   - Insert/update `Question` (existing logic).
   - **NEW:** Compute `external_question_id + source_url`. If both present:
     - SELECT existing CDS by `(external_question_id, source_name, source_url)`.
     - If found: re-link `question_id`; if content_hash changed → reset `approved_for_student=false` + audit.
     - Else: INSERT new CDS row, status=`pending`.
   - **NEW:** Emit audit per CDS write.
3. Commit transaction (audit + CDS in same tx as Question — existing same-tx pattern).

## Related code files

### Files to MODIFY
- `app/services/excel_parser.py` — add canonical fields `discussion_url`, `vote_*`, `external_question_id`, `discussion_count` to `CANONICAL_FIELDS`.
- `app/services/import_normalizer.py` — call URL validator on `discussion_url`; sanitize `external_question_id`.
- `app/services/import_validator.py` — accept new fields; non-required, graceful NULL.
- `app/services/import_service.py` — `confirm_import` adds CDS insert/relink + audit emission.
- `app/audit/events.py` — add new `AuditAction` values: `community_source.candidate_created`, `community_source.relinked`, `community_source.relinked_text_changed`.

### Files to CREATE
- `app/services/community_dump_parser.py` — BS4-based HTML block parser + `PARSER_SCHEMA_VERSION` (skeleton from pre-req task 3, parser functions added here).
- `app/security/url_validator.py` — SSRF guard module với expanded blocklist (used by Phase 13 normalize + Phase 14 fetch).
- `app/schemas/community.py` — Pydantic `VoteDistribution`, `ParsedCommunityRow`.
- `app/models/community.py` — SQLAlchemy ORM `CommunityDiscussionSource` (matches schema in NewPRD §10.2).
- `migrations/versions/0XXX_phase13_community_sources.py` — Alembic migration:
  - CREATE TYPE 4 enums: `community_source_name`, `community_fetch_status`, `community_consensus`, `community_confidence`.
  - CREATE TABLE `community_discussion_sources`.
  - ALTER TABLE `questions` ADD COLUMN `row_version INTEGER NOT NULL DEFAULT 0`.
- `tests/services/test_community_dump_parser.py` — parser unit tests using fixtures.
- `tests/services/test_url_validator.py` — SSRF guard unit tests.
- `tests/services/test_import_service_community.py` — integration: import → CDS row created.
- `tests/schemas/test_vote_distribution.py` — Pydantic validation tests.

### Files to DELETE
- None.

## Implementation steps

1. **Verify pre-reqs done** (`pre-reqs.md` all 3 tasks pass verification).
2. **Schema layer:**
   1. Create `app/schemas/community.py` with `VoteDistribution(BaseModel)` validating dict[str, int 0–10000], dynamic labels, no hardcode A-E.
   2. Create `app/models/community.py` with `CommunityDiscussionSource` SQLAlchemy model (per §10.2 v2 schema).
   3. Update `app/audit/events.py` add 3 new `AuditAction` values.
3. **SSRF guard layer:**
   1. Create `app/security/url_validator.py` with:
      - `BLOCKED_IPV4_NETWORKS` (10 ranges incl. CGNAT 100.64/10).
      - `BLOCKED_IPV6_NETWORKS` (7 ranges).
      - `validate_url(url) -> ValidatedURL` with scheme check + DNS resolve + IP pin.
      - `BlockedURLError` exception.
   2. Unit tests covering 8+ cases (CGNAT, IPv6 mapped, DNS rebind via mock resolver, redirect chain).
4. **Parser layer:**
   1. Extend `app/services/community_dump_parser.py` (skeleton from pre-req) with:
      - `parse_html_block(html_str) -> dict | None` using BS4 + lxml.
      - Selectors mapped: `[data-id]` → `external_question_id`, `.voted-answers-tally` → `vote_distribution`, `a[href*="/discussions/"]` → `discussion_url`.
      - Failed selector → raise `ParseError(selector, reason)`.
   2. Unit tests against 5 fixtures from pre-req task 2.
5. **Excel/normalize integration:**
   1. Add canonical fields to `excel_parser.CANONICAL_FIELDS` + `_ALIAS` map.
   2. Extend `import_normalizer.normalize_row` to call `url_validator.validate_url` on `discussion_url`; ParseError → row marks `error`.
   3. Extend `import_validator.validate_row` to accept new optional fields with graceful None.
6. **Import service integration:**
   1. Extend `import_service.confirm_import` per-row logic:
      - After Question insert/update, build `community_state` dict from validated fields.
      - SELECT existing CDS via `(external_question_id, source_name, source_url)` → relink or insert.
      - Detect content_hash change → reset approval + audit.
      - Emit `write_audit_log(actor_type=ActorType.system, actor_id=None, request_id=request.id, ...)`.
7. **Migration:**
   1. Generate `migrations/versions/0XXX_phase13_community_sources.py`.
   2. Review autogenerate output: enum CREATE TYPE x4, CREATE TABLE x1, ALTER TABLE questions x1, indexes x6.
   3. Add explicit `op.execute("DROP TYPE IF EXISTS …")` in downgrade.
   4. Test on clean DB: `alembic upgrade head` → ok; `alembic downgrade -1` → clean.
8. **Compile + lint:**
   ```bash
   uv run ruff check . && uv run ruff format --check . && uv run mypy app
   ```
9. **Tests:**
   ```bash
   uv run pytest tests/services/test_community_dump_parser.py
   uv run pytest tests/services/test_url_validator.py
   uv run pytest tests/services/test_import_service_community.py
   uv run pytest tests/schemas/test_vote_distribution.py
   uv run pytest -k "import"  # ensure no regression
   ```

## Todo list
- [ ] Pre-reqs verified (deps, fixtures, PARSER_SCHEMA_VERSION)
- [ ] `app/schemas/community.py` — VoteDistribution Pydantic
- [ ] `app/models/community.py` — CommunityDiscussionSource ORM
- [ ] `app/audit/events.py` — 3 new AuditAction values
- [ ] `app/security/url_validator.py` — SSRF guard expanded
- [ ] `app/services/community_dump_parser.py` — parser functions
- [ ] `app/services/excel_parser.py` — extend CANONICAL_FIELDS
- [ ] `app/services/import_normalizer.py` — call url_validator
- [ ] `app/services/import_validator.py` — accept new fields
- [ ] `app/services/import_service.py` — CDS insert/relink + audit
- [ ] `migrations/versions/0XXX_phase13_community_sources.py`
- [ ] Tests: parser, url_validator, import integration, vote distribution
- [ ] Migration test: upgrade head + downgrade -1 clean
- [ ] Lint + mypy clean
- [ ] Manual smoke: import 1 dump → 1 CDS row created with correct fields
- [ ] Audit log query: `entity_type='community_source'` returns rows with `request_id` populated

## Success criteria
- 4 keys (`discussion_url`, `vote_distribution`, `external_question_id`, `discussion_count`) populate trong `import_items.normalized_data` khi input có data.
- 1 row trong `community_discussion_sources` per question có discussion_url, status=`pending`.
- Audit `community_source.candidate_created` emitted per row, `request_id` populated từ middleware UUID.
- 0 fetch Internet, 0 AI call (verified by network monitoring during test run).
- Failed selector → row `import_item_status='error'` với `error_message='parse_error: <selector>'`. NO silent NULL.
- Re-import idempotent: same dump 2× → 0 duplicate CDS rows.
- Test coverage ≥80% trên 4 new modules.
- `alembic upgrade head` + `downgrade -1` clean trên empty DB.
- `ruff check`, `ruff format --check`, `mypy` all green.

## Risk assessment
- **High:** ExamTopics HTML drift mid-Phase-13 → Pre-req task 2 fixtures lock contract; parser hard-error on selector miss; daily smoke job (Phase 14 setup) detects drift.
- **Medium:** Re-import relink logic complex → 6+ test cases (new import, relink, content_hash change, multi-source per question, deleted question with cache, etc.).
- **Medium:** Migration interacts với Phase 02 stub `evidence_fetch_logs` (NOT touched by Phase 13 — defer to Phase 14 or Phase 2).
- **Low:** Pydantic dynamic labels validation — straightforward; covered by tests.

## Security considerations
- **SSRF defense-in-depth:** url_validator called at normalize (Phase 13) AND fetch (Phase 14, future). DNS pin + `follow_redirects=False` enforced ở `validate_url` return.
- **CGNAT block:** `100.64.0.0/10` MUST be in blocklist (Tailscale subnet, red-team #2 Critical).
- **`external_question_id` injection:** Pydantic regex `^[A-Za-z0-9_\-]{1,255}$` ngăn log injection / XSS bleed.
- **Audit immutability:** CDS audit write trong cùng SQLAlchemy session as data write (existing same-tx pattern).
- **No PII in fixtures:** confirmed by pre-req task 2 done criteria.

## Next steps
After Phase 13 done → Phase 16a admin tab (parallel from day 2 actually). After 16a → Sprint-1 ship → Gate-A1 evaluation → trigger Sprint-2 (Phase 14) only on demand signal.
