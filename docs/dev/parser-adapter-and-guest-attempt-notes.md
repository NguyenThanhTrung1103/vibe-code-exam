# Parser-Adapter and Guest-Attempt — Developer Notes

**Audience:** Engineers extending the import pipeline or wiring the deferred guest-practice flow.
**Related code:** `app/services/parsers/`, `app/auth/guest.py`, `app/models/imports.py`, `app/models/attempts.py`.
**Last updated:** 2026-05-02.

---

## 1. Parser-adapter contract

### Why this exists

Before this slice, `app/services/excel_parser.py` had a hard-coded XLSX assumption. We now accept four formats (XLSX, ExamTopics-style HTML, generic `QUESTION N` PDF, generic `QUESTION N` text). Adding a fifth should NOT require touching `import_normalizer`, `import_validator`, dedup, or community-source upsert. The adapter layer is the single seam.

### The Protocol

`app/services/parsers/base.py`:

```python
@runtime_checkable
class ParserAdapter(Protocol):
    name: str
    priority: int

    def detect(self, *, filename: str, head_bytes: bytes) -> bool: ...

    def parse(
        self,
        *,
        file_path: Path,
        column_mapping: dict[str, str | None] | None = None,
    ) -> Iterator[ParsedQuestion]: ...
```

- `name` — short identifier persisted to `imports.detected_format`. Examples: `xlsx`, `examtopics_html`, `qblock_pdf`, `qblock_text`.
- `priority` — higher wins when multiple adapters claim a file. Current ordering: `xlsx` 80 > `examtopics_html` 70 > `qblock_pdf` 60 > `qblock_text` 50.
- `detect()` — **cheap** signature check. Reads `head_bytes` (first 4 KiB of the file) and the `filename`. MUST NOT parse the whole file. MUST NOT raise on bad input — return `False` instead.
- `parse()` — yields `dict[str, Any]` rows whose keys are a subset of `CANONICAL_FIELDS`. The tuple in `base.py` is the single source of truth; downstream code grabs whatever keys it needs.

### What the canonical row contains

`base.py:CANONICAL_FIELDS` — see file. Highlights:

- Question + options: `question_text`, `option_a`..`option_f`, `combined_options` (single-cell fallback for XLSX), `correct_answer`.
- Discussion / community: `discussion_url`, `discussion_count`, `vote_a`..`vote_f`, `external_question_id`.
- Source-locator (NEW with this slice, persisted into `questions.source_locator JSONB`): `source_url`, `source_format`, `source_page`, `raw_source_ref`.

Adapters MAY emit a subset; missing keys are `None`. The normalizer in `import_normalizer.py` enforces "required = `question_text` AND (`option_a + option_b` OR `combined_options`) AND `correct_answer`".

### How the detector picks one

`app/services/parsers/detector.py`:

```python
def detect_adapter(*, filename: str, file_path: Path) -> ParserAdapter | None:
    head = open(file_path, "rb").read(4096)
    for adapter in sorted(_REGISTRY, key=lambda a: -a.priority):
        if adapter.detect(filename=filename, head_bytes=head):
            return adapter
    return None
```

Decisions:

- Filename suffix is part of the detect key. `.xlsx` files claimed by `XlsxAdapter` only; `.html`/`.htm` by `ExamTopicsHtmlAdapter`; `.pdf` by `QBlockPdfAdapter`; `.txt`/`.text` by `QBlockTextAdapter`.
- Magic-bytes check beats filename: `XlsxAdapter` requires the ZIP magic `PK\x03\x04`, `QBlockPdfAdapter` requires `%PDF-`. This rejects renamed-but-not-converted files cleanly.
- `examtopics_html` looks for textual hints in the head bytes (`question-body`, `voted-answers-tally`, `data-id=`, `discussion-count`, `examtopics`) before claiming an HTML file. A generic HTML page with no such markers will not be claimed and the upload still uploads but is staged with `detected_format = NULL` — admin can then proceed via the XLSX path or abort.

### Adding a new adapter (5 steps)

1. Create `app/services/parsers/<name>_adapter.py`. Implement `detect()` and `parse()` per the Protocol.
2. Pick a `priority`. Lower than 50 if it should be the last-resort fallback.
3. Register in `_REGISTRY` in `detector.py`.
4. Update `CANONICAL_FIELDS` ONLY if your adapter produces a brand-new column. Avoid this — prefer reusing existing keys.
5. Add a hermetic test under `tests/services/` that constructs a small fixture file and asserts `detect_adapter().name == "<name>"` plus a smoke parse.

### Things that will break the contract (do not do)

- Returning a bare `dict` from a non-generator `parse()` — must be an iterator (yield).
- Reading the entire file in `detect()` — kills upload latency on large files.
- Raising in `detect()` — the dispatcher silently skips adapters that raise. Better: return `False` and log via `structlog` if it's surprising.
- Mutating shared state between rows. Each yielded dict must be independent — the streamer assumes no aliasing.

---

## 2. XLSX adapter — special considerations

`xlsx_adapter.py` wraps `excel_parser.stream_rows`. **No new behaviour.** Why this matters:

- The English alias map (`question`, `option_a`, `correct_answer`, …) and the **Vietnamese** alias map (`câu_hỏi`, `đáp_án_đúng`, …) live in `excel_parser.py:_ALIAS`. Both still work transparently — this slice does not redefine them.
- `combined_options` is preserved: when an admin maps a single sheet column to `combined_options`, the row reader splits on `;` / `；` / newline into `option_a`..`option_f`. Confirmed by regression test.
- `XlsxAdapter.parse()` returns `None` early if `column_mapping` is missing — the wizard collects the mapping in step 2 BEFORE step 3 streams rows, so this is not a real path in production. Keep it for safety and for unit tests that drive `parse()` directly.

---

## 3. ExamTopics HTML adapter — heuristics

`examtopics_html_adapter.py` parses **uploaded saved pages**, not live URLs.

The `_block_to_row` function tries, in order:

- Question text from `.question-body` → `.card-text` → first `<p>`.
- Options from `<ul>/<ol> li` matching `^[A-F][.):-]\s*…$` regex → fallback to `<p>` lines that match the same pattern.
- Suggested answer from `.correct-answer` → `.reveal-solution` → `.question-answer`. The literal `B` letter is extracted from inline text like "Suggested Answer: B".
- Vote distribution from `.voted-answers-tally` (regex `\b([A-F])\b\s*[:\-]?\s*(\d+)`).
- Explanation from `.question-explanation` → `.answer-description` → `.explanation`.
- `external_question_id` from `[data-id]` attribute, with `ET-{idx:04d}` fallback.

Best-effort by design — drift is expected as ExamTopics changes their DOM. Failing gracefully (returning `None` from `_block_to_row`, skipping the block) is preferred over noisy errors.

---

## 4. Guest-attempt cookie helpers (Milestone 2 — DORMANT)

`app/auth/guest.py` is implemented but **NOT WIRED**. It must not become reachable until Milestone 2 is approved.

### Contract

```python
GUEST_COOKIE = "exam_guest_token"
GUEST_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

def read_guest_token(request: Request) -> str | None: ...
def issue_guest_token(response: Response) -> str: ...        # mints + sets cookie
def ensure_guest_token(request: Request, response: Response) -> str: ...
```

- Token = `secrets.token_urlsafe(32)`. URL-safe, 43 chars, ~256 bits of entropy.
- Cookie attrs: `HttpOnly=True`, `SameSite=Lax`, `Secure=False` (dev/LAN — flip to `True` once HTTPS-terminating proxy is in front).
- Validation in `read_guest_token` rejects tokens outside the 16–64 char range to keep cookie noise out of the DB.
- `attempts.guest_token` column is `String(64)` — fits.

### Wiring plan (when Milestone 2 lands)

1. Add a FastAPI dependency `OptionalGuest` that returns `(authed_user_or_none, guest_token_or_none)` for a request — uses `read_guest_token` only.
2. New route `POST /practice/{exam_id}/start-guest` mints a guest token (only for **published** exams), creates an `attempts` row with `user_id=NULL, guest_token=<token>`, sets cookie.
3. New route `GET /attempts/{id}/review` allows access if EITHER `current_user.id == attempt.user_id` OR `cookie_token == attempt.guest_token`.
4. CSRF: practice/start endpoints require CSRF token even for unauthed callers (cookie-bound).
5. Tests: cookie isolation across two browsers, ownership rejection of mismatched cookies, expiry behaviour.

### Why "Option B" (keep code, don't remove)

Removing `app/auth/guest.py` and rolling back migration 0008 would mean re-writing both later. Since `guest.py` is unimported and the DB column is unused, leaving them in place adds zero attack surface and saves a churn cycle. The `imports.detected_format` column applies regardless.

---

## 5. CHECK constraint `ck_attempts_owner`

```sql
ALTER TABLE attempts
  ADD CONSTRAINT ck_attempts_owner
    CHECK (user_id IS NOT NULL OR guest_token IS NOT NULL);
```

- Existing rows have `user_id` populated → constraint passes for them.
- New rows from authed users continue to set `user_id` → passes.
- New rows from guests (Milestone 2) will set `guest_token` → passes.
- An accidental `INSERT` with both `NULL` will be rejected by Postgres before the row lands. This is the safety net behind keeping `guest_token` dormant.

---

## 6. Migration ordering

```
b1c2d3e4f5a6  (existing head before this slice)
   ↓
c2d3e4f5a6b7  0007_imports_add_title
   ↓
d3e4f5a6b7c8  0008_attempts_guest_token
   ↓
e4f5a6b7c8d9  0009_imports_detected_format   ← head
```

Apply with `alembic upgrade head`. Each migration is independently reversible with `alembic downgrade -1`.

---

## Unresolved questions

- Should we add a "force adapter" admin override on the upload page when the detector mis-claims a file? Probably yes for support, but not in this slice.
- Vietnamese-keyword detection for HTML/PDF/TXT (not just XLSX headers) — defer until we see real Vietnamese non-XLSX dumps in the wild.
- Should `examtopics_html_adapter` rate-limit DOM parses for very large pages? Current behaviour reads the whole file via BeautifulSoup `html.parser`. Memory profile is fine for the page sizes seen so far (single question pages ~50 KB).
