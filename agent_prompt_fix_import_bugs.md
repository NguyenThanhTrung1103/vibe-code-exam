# Agent Task — Fix 3 Import Bugs on Exam Platform

## Context

You are working on **Exam Platform**, a single-tenant exam-practice web app.

**Stack:**
- FastAPI (Python 3.12, `uv` package manager)
- PostgreSQL 14, database `exam_platform_db`, owner `exam_platform`
- Redis (sessions / rate limits / soft locks)
- Jinja2 server-rendered HTML
- SQLAlchemy 2.x ORM, Alembic migrations
- Deployed on Ubuntu 22.04 LXC at `192.168.99.97:8001`
- App path: `/srv/exam-platform`
- systemd service: `exam-platform-web.service`

**Current branch:** `master`. Latest commit: `9335105`.

**SSH rule (mandatory):** Always use the alias `exam-lxc` defined in `~/.ssh/config`.
Never hardcode `user@host`. Consult `.claude/skills/ssh/SKILL.md` if connectivity issues arise.

```bash
ssh exam-lxc
scp file exam-lxc:/srv/exam-platform/...
```

---

## Safety boundaries — read before touching anything

- **Never** run `DELETE` or `UPDATE` on confirmed `questions` or `imports` rows.
  Re-staging `import_items` (staging data) is OK when explicitly requested.
- **Always** backup the DB before a forward migration:

```bash
ssh exam-lxc '
TS=$(date -u +%Y%m%dT%H%M%SZ)
sudo -u postgres pg_dump --format=custom \
  --file=/var/backups/exam-platform/exam_platform_db-${TS}.dump \
  exam_platform_db
echo "BACKUP_PATH=/var/backups/exam-platform/exam_platform_db-${TS}.dump"
'
```

- **Only** restart `exam-platform-web.service`. Never touch PostgreSQL, Redis, nginx, or cloudflared.
- **No internet fetch / scrape** at runtime. All parsers are local-file only.
- **Never commit:** `.env`, `Template Dump/`, `*.dump`, SSH keys, secrets.

---

## Deploy workflow (after every code change)

```bash
# 1. Local lint + tests
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run pytest

# 2. Sync changed files
scp app/.../changed.py exam-lxc:/srv/exam-platform/app/.../

# 3. Fix ownership + restart
ssh exam-lxc 'chown exam-platform:exam-platform /srv/exam-platform/<paths>'
ssh exam-lxc 'systemctl restart exam-platform-web.service'
ssh exam-lxc 'curl -fsS http://127.0.0.1:8001/healthz'
```

Healthcheck must return `{"status":"ok","db":"ok","redis":"ok"}` after every deploy.

---

## Migration workflow

```bash
# Always backup first (see above), then:
ssh exam-lxc 'cd /srv/exam-platform && uv run alembic upgrade head'
```

---

## The 3 bugs to fix — in order

### Bug 1 (Critical) — Schema A–F cap blocks rows with 7–8 options

**Symptom:**
- Import `#142` (`import_quiz_question_ccna_online.xlsx`) has row 9 with
  8 listed options and `correct_answer=7`. This row errors on import.
- Import `#143` and `#147` both show `header failed 2 · target exam #1`
  for the same root cause.
- Current cap is A–F (6 options). The storage cap was raised A–E → A–F
  in commit `9335105` but was not taken further.

**Root cause:**
- DB schema has columns only up to `option_f` on the `questions` table.
- The validator, `question_service`, and `attempt_service` hard-cap at 6.
- XLSX adapter maps at most 6 option columns; rows with G or H columns are rejected.

**Files likely involved:**
- `alembic/versions/` — need a new migration
- `app/models/question.py` (or wherever `option_a..option_f` columns are defined)
- `app/services/import_service.py` — validator cap
- `app/services/question_service.py` — option handling
- `app/services/attempt_service.py` — option selection parsing
- XLSX parser adapter (wherever `option_a..option_f` mapping is defined)

**Fix required:**

1. **DB migration** — add two nullable text columns:
```sql
ALTER TABLE questions ADD COLUMN option_g TEXT;
ALTER TABLE questions ADD COLUMN option_h TEXT;
```

2. **SQLAlchemy model** — add `option_g` and `option_h` fields (nullable, same type as `option_f`).

3. **Validator** — raise the cap from 6 to 8:
   - Accepted answer labels: `A`–`H`
   - Numeric `correct_answer`: valid range `1..8` → maps to `A..H`
   - `combined_options` split: accept up to 8 segments

4. **XLSX adapter** — extend the column alias map to include `option_g` / `G` / `Option G`
   and `option_h` / `H` / `Option H`.

5. **`attempt_service`** — wherever option labels are enumerated (e.g. `['A','B','C','D','E','F']`),
   extend to `['A','B','C','D','E','F','G','H']`. Same for any scoring loops.

6. **`question_service`** — same extension for option replace / CRUD methods.

7. **Tests** — update existing A–F tests and add at least one test for a valid 7-option
   and one for a valid 8-option row.

After fix, re-stage import `#142` and verify row 9 no longer errors.

---

### Bug 2 (High) — Deduplication false-positive flags 100% of rows as DUPLICATE

**Symptom:**
- Import `#148` (NSE7, `57q_efw.html`, 57 rows): **all 57 rows flagged DUPLICATE**,
  bank count = 0, but status shows `NORMALIZED` and "Looks safe to confirm. No errors detected."
- The system contradicts itself: it says "safe to confirm" but shows 57 duplicates with 0 OK rows.
- Import `#144` (same file `57q_efw.html`) completed with 57 rows in bank — so the
  content exists but a prior import already owns it.
- The dedup step matches on `content_hash`. The preview cannot auto-resolve which
  prior import a duplicate row belongs to (documented limitation).

**Root cause:**
The `content_hash` / fingerprint function generates the hash from raw text without
normalizing first. As a result:
- Whitespace differences (trailing spaces, double spaces) produce a different hash
  even when the question is semantically identical.
- Option order differences produce a different hash even though the answer set is the same.
- However, the comparison logic may also have the inverse problem: it may be
  matching too broadly (e.g. comparing hash against all exams, not just the target exam),
  causing legitimate new questions to be flagged as duplicates of questions in other exams.

**Files likely involved:**
- `app/services/import_service.py` — `content_hash` generation and dedup query
- Possibly `app/models/import_item.py` or `app/models/question.py`

**Fix required:**

1. **Normalize before hashing.** The hash input must be built from a canonical form:

```python
import hashlib, unicodedata, re

def _canonical(text: str) -> str:
    # NFKD normalize, lowercase, collapse whitespace
    text = unicodedata.normalize("NFKD", text or "")
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text

def make_content_hash(question_text: str, options: list[str], correct_answer: str) -> str:
    q = _canonical(question_text)
    opts = sorted(_canonical(o) for o in options if o)  # sort so order doesn't matter
    ans = _canonical(correct_answer)
    payload = q + "|" + ";".join(opts) + "|" + ans
    return hashlib.sha256(payload.encode()).hexdigest()
```

2. **Scope dedup to the target exam.** The duplicate check must only match questions
   that belong to the **same `exam_id`** as the import target. If the current query
   checks globally across all exams, narrow it:

```sql
-- pseudocode: only flag duplicate if same exam_id
SELECT id FROM questions
WHERE content_hash = :hash AND exam_id = :target_exam_id AND deleted_at IS NULL
```

3. **Re-hash existing rows** (one-off migration or admin script) so that the new
   canonical hash is consistent with the data already in the DB. Otherwise, all
   existing questions will appear as "new" after the fix.
   - Write a script `scripts/rehash_questions.py` that iterates over all questions,
     recomputes `content_hash` with the new function, and updates in-place.
   - Gate this behind an explicit operator run (`uv run python scripts/rehash_questions.py`).
   - Do **not** run this automatically on startup.

4. **Tests** — add unit tests for `make_content_hash` covering:
   - Identical questions with different whitespace → same hash
   - Identical questions with options in different order → same hash
   - Questions for different exams with same text → dedup does NOT fire across exams
   - Genuinely different questions → different hash

After fix, re-run import `#148` and verify the 57 rows are treated correctly
(either OK because they genuinely differ from what's in the bank, or DUPLICATE
with the correct prior import identified).

---

### Bug 3 (High) — XLSX column header mapping fails silently on non-standard column names

**Symptom:**
- Import `#147` (CCNA XLSX): `2 row error(s) · header failed 2 · target exam #1`
- Import `#143` (auto-import `import_quiz_question_ccna_online.xlsx`): same error pattern.
- The `auto_map()` function pre-fills via an alias map, but when a header doesn't
  match any known alias, the row is rejected with a generic "header failed" error
  rather than a helpful message.

**Root cause:**
The alias map in `auto_map()` covers known Vietnamese and English headers
(documented in summary §6) but does not handle:
- Column names with extra punctuation or parenthetical suffixes not in the alias list
- Headers that differ only by diacritics when NFKD stripping is not applied consistently
- The mapper fails the entire row instead of skipping only the unmapped columns
  and surfacing a warning

**Files likely involved:**
- `app/services/import_service.py` — `auto_map()` and header normalization
- `app/routers/admin/imports.py` — mapping step error handling
- Possibly `app/templates/admin/imports/mapping.html` — UI feedback

**Fix required:**

1. **Harden the header normalizer.** All header strings must go through the same
   pipeline before alias lookup:
```python
import unicodedata, re

def normalize_header(h: str) -> str:
    h = unicodedata.normalize("NFKD", h or "")
    h = h.lower().strip()
    h = re.sub(r"[^a-z0-9]", "", h)   # strip all non-alphanumeric
    return h
```
Apply this to both the incoming XLSX headers **and** the keys in the alias dict.

2. **Extend the alias map** for common variants that the CCNA file likely uses.
   Add at minimum:
```python
HEADER_ALIASES = {
    # ... existing entries ...
    "question":        ["question", "questiontext", "noidungcauhoi", "cauhoi", "noidung"],
    "option_a":        ["optiona", "choicea", "answera", "a"],
    "option_b":        ["optionb", "choiceb", "answerb", "b"],
    "option_c":        ["optionc", "choicec", "answerc", "c"],
    "option_d":        ["optiond", "choiced", "answerd", "d"],
    "option_e":        ["optione", "choicee", "answere", "e"],
    "option_f":        ["optionf", "choicef", "answerf", "f"],
    "option_g":        ["optiong", "choiceg", "answerg", "g"],   # after Bug 1 fix
    "option_h":        ["optionh", "choiceh", "answerh", "h"],   # after Bug 1 fix
    "correct_answer":  ["correct", "correctanswer", "answer", "dapandung", "cautraloidung"],
    "explanation":     ["explanation", "giaithich", "giaitich", "giaithichdapan"],
    "topic":           ["topic", "chude", "linhvuc", "subject"],
    "difficulty":      ["difficulty", "dokho", "level"],
    "tags":            ["tags", "thetag", "tag"],
}
```

3. **Degrade gracefully, don't fail rows.** When a header cannot be mapped:
   - Do **not** error the entire row.
   - Emit a `warning`-level `import_items` status with a clear reason:
     `"Column 'XYZ' could not be mapped to any known field and was ignored."`
   - Only error the row if a **required** field (`question_text`, `correct_answer`,
     and at least `option_a`+`option_b` OR `combined_options`) is missing after mapping.

4. **Surface unmapped headers on the mapping UI.** On the `/admin/imports/{id}/mapping`
   page, show a yellow warning listing any incoming columns that `auto_map()` could not
   resolve, so the operator can manually assign them before proceeding.

5. **Tests** — add tests covering:
   - XLSX with Vietnamese headers → maps correctly
   - XLSX with English headers in unusual casing (`QUESTION`, `Correct Answer`) → maps correctly
   - XLSX with an unknown column → row gets `warning`, not `error`; required fields still validated
   - XLSX missing `question_text` → row gets `error` with clear message

---

## Verification checklist after all 3 fixes

Run in this order:

```bash
# 1. Tests green
uv run pytest

# 2. Lint clean
uv run ruff check app tests
uv run mypy app

# 3. Backup DB
ssh exam-lxc '
TS=$(date -u +%Y%m%dT%H%M%SZ)
sudo -u postgres pg_dump --format=custom \
  --file=/var/backups/exam-platform/exam_platform_db-${TS}.dump \
  exam_platform_db
'

# 4. Run migration (Bug 1 — schema extension)
ssh exam-lxc 'cd /srv/exam-platform && uv run alembic upgrade head'

# 5. Run rehash script (Bug 2 — one-off, operator approval required)
ssh exam-lxc 'cd /srv/exam-platform && uv run python scripts/rehash_questions.py'

# 6. Deploy + restart
scp <changed files> exam-lxc:/srv/exam-platform/...
ssh exam-lxc 'chown exam-platform:exam-platform /srv/exam-platform/<paths>'
ssh exam-lxc 'systemctl restart exam-platform-web.service'
ssh exam-lxc 'curl -fsS http://127.0.0.1:8001/healthz'
```

**Expected healthcheck:** `{"status":"ok","db":"ok","redis":"ok"}`

Then verify imports via the admin UI:
- `/admin/imports/142/preview` → row 9 (8-option) should no longer error
- `/admin/imports/148/preview` → 57 rows should not all be DUPLICATE (re-import if needed)
- `/admin/imports/147/mapping` → no "header failed" errors on CCNA XLSX

---

## Do NOT do

- Do not touch `nginx`, `cloudflared`, `redis-server`, or `postgresql` configs.
- Do not run `DELETE`/`UPDATE` on `questions` or `imports` tables.
- Do not commit `Template Dump/`, `.env`, `*.dump`, `plans/reports/*.xlsx`, or SSH keys.
- Do not fetch the internet at runtime.
- Do not restart any service other than `exam-platform-web.service`.
- Do not run the rehash script without explicit operator confirmation.
