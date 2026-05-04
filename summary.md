# Exam Platform — Full Project Summary

> Handoff document for the next developer / operator. Snapshot taken
> 2026-05-04. Covers what the app is, what already ships, what is
> deployed on the LXC right now, what remains, and how to keep moving
> without losing context.

---

## 1. Project overview

Exam Platform is a single-tenant exam-practice web app:

- **Stack:** FastAPI (Python 3.12, `uv` package manager) + PostgreSQL 14
  + Redis (sessions / rate limit / soft locks) + Jinja2 server-rendered
  HTML. SQLAlchemy 2.x ORM. Alembic for schema migrations. `httptools`
  + `uvloop` under uvicorn workers (single-host).
- **Deploy target:** an Ubuntu 22.04 LXC at `192.168.99.97` reachable
  on the LAN via `8001/tcp`. Service runs as the `exam-platform` user
  out of `/srv/exam-platform` under `systemd`.
- **Purpose:** let an admin import a dump of practice questions
  (Excel, saved HTML, PDF, TXT), curate them in a question bank, and
  serve them to candidates as practice attempts. Future work adds
  guest practice without login, scoring/review UX, and CDEA
  evidence/explanation enrichment.

The app is deliberately conservative: no internet fetches at runtime,
no third-party scraping, no public exposure beyond the LAN until
explicitly opted in. Single-user / single-admin assumption is baked
into rate limits and several UX flows.

---

## 2. Current infrastructure

| Item | Value |
|---|---|
| LXC IP | `192.168.99.97` |
| App path on LXC | `/srv/exam-platform` |
| systemd service | `exam-platform-web.service` (only one to restart) |
| Python venv | `/srv/exam-platform/.venv` (managed by `uv sync --extra dev`) |
| DB | PostgreSQL 14, database `exam_platform_db`, owner `exam_platform` |
| Redis | local instance, used for sessions + rate limits + import soft locks |
| LAN URL | `http://192.168.99.97:8001` |
| Healthcheck | `GET /healthz` → `{"status":"ok","db":"ok","redis":"ok"}` |
| LAN exposure status | **temporary**: 8001 is bound directly. Revert to loopback-only after Gate-A1 / Milestone testing if you want to harden. |
| nginx / cloudflared | shipped as ops/* templates, **not** installed live. Do not modify without approval. |

### SSH alias rule (mandatory)

Always connect through the `exam-lxc` alias defined in
`~/.ssh/config`. **Never** guess `user@host`.

```bash
ssh exam-lxc       # opens shell as the configured user
scp file exam-lxc:/srv/exam-platform/...
```

The SSH skill that documents and diagnoses this is at:

```
.claude/skills/ssh/SKILL.md
```

If a session ever asks "which user is exam-lxc?", consult that skill.
The connectivity guard is part of the standard pre-deploy preflight.

---

## 3. Admin / import authentication

- Every `/admin/*` route requires an admin role.
- Anonymous access redirects (303) to `/auth/login?next=<original-path>`.
- Admin import (`/admin/imports`, `/admin/imports/{id}/...`) is fully
  CSRF-protected and rate-limited via `RL_ADMIN_IMPORT`.
- Public / guest practice is **not** fully wired yet (see § 11). Today,
  every practice attempt requires an authenticated user.
- Admin-login caveat: `scripts/create_admin.py` accepts a 10-char
  password floor (lowered from 16 in commit `ad55c68`). The seeded
  admin on the LXC is `admin@local.test`; the password is **not**
  in the repo. To rotate, ssh in and run `create_admin.py --update`.

---

## 4. Import pipeline overview

Lives at `app/routers/admin/imports.py` + `app/services/import_service.py`.
The wizard is linear:

```
Upload  →  Mapping (XLSX only)  →  Preview  →  Confirm  →  Done
                          ↓
                  parse_and_stage runs
                  rows land in import_items
```

| Step | Route | What happens |
|---|---|---|
| Upload | `POST /admin/imports` | Validates magic bytes / extension, stores file under `uploads/imports/{id}.{ext}`, runs the format detector, inserts the `imports` row, sets `file_type` + `detected_format`. XLSX → mapping; everything else → straight to preview. |
| Mapping | `GET/POST /admin/imports/{id}/mapping` | Per-header → canonical-field selectors. `auto_map()` pre-fills via the alias map. Save runs `parse_and_stage()`. |
| Preview | `GET /admin/imports/{id}/preview` | Lists every staged row, grouped by status. Filters: all / ok / duplicates / errors / warnings / skipped / imported. |
| Confirm | `POST /admin/imports/{id}/confirm` | Idempotent insert into `questions` for every `import_items` row in `ok`. Re-running confirms zero new questions. |
| Done | `GET /admin/imports/{id}/done` | Summary metrics + Review-imported-questions link. |

The Recent imports table on `/admin/imports` lists the latest 20
imports plus an explicit **Imported** count column. Each row carries
two CTAs:

- **Open import** → re-opens the preview.
- **Review questions** → `/admin/questions?source_import_id=<id>`,
  filtering the question bank to whatever this import committed.

If a row's live count is zero, the second CTA is replaced by a muted
**No imported questions** label.

### `import_items.status` lifecycle

```
parsed → ok          (passed normalization + validation)
       → warning     (passed; non-blocking warning, e.g. unknown difficulty)
       → duplicate   (content_hash matches another row in this import or an existing question in the same exam)
       → error       (validation failed; row will not confirm)
       → skipped     (operator toggled it off in preview)
       → imported    (confirm wrote a `questions` row)
```

### `imports.status` lifecycle

| Status | Meaning |
|---|---|
| `uploaded` | File written, no rows staged yet. |
| `needs_mapping` | XLSX awaiting / received column mapping. |
| `normalized` | Rows staged via `parse_and_stage`; preview is meaningful here. |
| `partially_verified` | Reserved for future CDEA cycle. |
| `ready_to_publish` | Confirmed; questions live in the bank. |
| `published` | Operator (or a future workflow) flipped the import to public visibility. Today the field exists but no UI mutates it. |
| `failed` | Hard parser failure on the whole file (rare). |

---

## 5. Supported import formats

All formats funnel through the same `parse_and_stage` →
`normalize_row` → `validate_row` → dedup pipeline. Differences live
in the parser adapter.

### 5.1 XLSX canonical (English headers)

- `detected_format = xlsx`
- Expected columns: `Question`, `A`/`Option A`, …, `Correct`, optional
  `Difficulty`, `Topic`, `Tags`, `Explanation`, `Reference`, plus
  Phase 13 community columns (`Discussion URL`, `Vote A`..`F`, …).
- Walks the column-mapping wizard.
- Cap: max 5,000 rows / max 32 columns per file.

### 5.2 Vietnamese XLSX

- `detected_format = xlsx`
- Auto-map honours: `Câu hỏi`, `Nội dung câu hỏi`, `Đáp án đúng`,
  `Giải thích đáp án`, `Mô tả thêm`, `Loại câu hỏi`, `Chủ đề` /
  `Lĩnh vực`, `Độ khó`, `Tags`, `Thẻ tag`. Both diacritic and
  ASCII-transliterated forms are recognised after NFKD-stripping.
- Operator-supplied dump title is preferred over the file name in
  the Recent imports list.

### 5.3 XLSX with `combined_options` (single-cell answer list)

- `detected_format = xlsx`
- The cell `Danh sách đáp án (...)` (or any column the operator
  manually maps to `combined_options`) carries every option in one
  cell, separated by `;` / `；` / newlines. The normalizer splits it
  into `option_a..option_f` so the rest of the pipeline never sees
  the difference.
- The mapping page shows
  "Combined options column detected. It will be split into Option A..F
  during parsing." and exempts `option_a` / `option_b` from the
  required-fields check.

### 5.4 Saved HTML (ExamTopics-like)

- `detected_format = examtopics_html`
- Adapter: `app/services/parsers/examtopics_html_adapter.py`
- Pulls question text from `<p class="card-text">`, options from
  `<li class="multi-choice-item">`, correct answer + per-letter votes
  from the JSON payload inside `<script type="application/json">` under
  `.voted-answers-tally`.
- `<base href="...">` is honoured to resolve relative discussion
  URLs.
- **Limitation:** if the saved page does not include the discussion
  body, no community explanations are imported (zero
  `community_discussion_sources`).
- **No internet fetch.** Adapter is purely local-file.

### 5.5 PDF / TXT QUESTION-block

- `detected_format = qblock_pdf` / `qblock_text`
- Adapter: `app/services/parsers/qblock_text_adapter.py` (with a
  pdfminer.six text-extraction front-end for PDFs).
- Recognises `QUESTION N`-delimited blocks with `A.` / `B.` / ...
  bullets, an `Answer:` line, and an optional `Explanation:` line.
- Multi-answer (e.g. `Answer: BD`) supported via the contiguous
  multi-letter expansion in the validator.
- **Limitation:** image-only / scanned PDFs return empty text and
  parse to 0 rows. No OCR fallback.

---

## 6. Excel / Vietnamese XLSX mapping rules

Auto-map alias table (after NFKD accent-strip + lowercase +
alphanumeric-only normalisation):

| Vietnamese label | Canonical field |
|---|---|
| `Câu hỏi` / `Nội dung câu hỏi` | `question_text` |
| `Loại câu hỏi` | `question_type` |
| `Danh sách đáp án (...)` / `Các đáp án` / `Đáp án` | `combined_options` |
| `Đáp án đúng (...)` / `Câu trả lời đúng` | `correct_answer` |
| `Giải thích đáp án` / `Giải thích` | `explanation` |
| `Mô tả thêm` | `reference` |
| `Chủ đề` / `Lĩnh vực` | `topic` |
| `Độ khó` | `difficulty` |
| `Tags` / `Thẻ tag` | `tags` |

`combined_options` rule:

- A mapping is valid if `question_text` + `correct_answer` are mapped
  AND **either** both `option_a` and `option_b` are mapped OR
  `combined_options` is mapped. The required-fields card and the
  service-side `required_mapping_missing()` helper both use the same
  rule (no UI / service drift).
- The normalizer splits the combined cell on `;` / `；` / newline
  and strips leading ordinal labels (`A.`, `1)`, `B:` …) so the
  individual texts are clean.

`correct_answer` shapes (mixed within one cell are fine — split first
on `,` / `;` / newline):

- Letter labels `A`..`F` (case-insensitive).
- Contiguous multi-letter `AC`, `BD`, `ACE` (no separator) — expanded
  to individual labels.
- Numeric `1..6` → `A..F`. `1;3` → A,C, `4;6` → D,F.
- Verbatim option text (case-fold compare).

`question_type` normalization:

| Cell value (case-insensitive, hyphens / spaces collapsed) | Stored as |
|---|---|
| `single`, `single_choice`, `one_choice`, `radio` | `single` |
| `multiple`, `multi`, `multiple_choice`, `multi_choice`, `checkbox`, `checkboxes` | `multiple` |
| `true_false`, `truefalse`, `boolean`, `bool`, `tf` | `true_false` |
| `choice` or blank | inferred from `correct_answer` count (≥ 2 → `multiple`, else `single`) |

`auto_map` also de-duplicates: if two headers resolve to the same
canonical field, the more specific (exact match > position-0
substring > buried substring; longer alias > shorter) wins, the
rival is reset to None, and the mapping page renders a yellow warning
listing the conflicting headers.

### A–F storage cap

The validator, `question_service`, and `attempt_service` all accept
labels A through F (six options). Earlier in this milestone the cap
was A–E.

**Current limitation:** rows with seven or more options (for
example a row whose `correct_answer` references `7`) still error
out. The fixture `import_quiz_question_ccna_online.xlsx` (#142)
has exactly one such row; bumping the cap further requires a
schema-level decision about `option_g` / `option_h` and
attempt-side selection parsing.

---

## 7. HTML import behaviour

- Saved local HTML only — **never** fetches the internet, never
  re-runs JS. The operator must save the page in their browser as
  "Webpage, complete" and upload it.
- Adapter: ExamTopics-like saved-page format.
- Per-row data extracted: question text, options, correct answer
  (from the JSON tally / "most voted" when available),
  `discussion_url`, `external_question_id`, `discussion_count`,
  per-letter vote counts.
- Community signals land in `community_discussion_sources`; the
  admin Community tab (Phase 16a) renders them read-only.
- **Limitation:** the saved fixture (#138) does not include the
  discussion body, so 0 explanations are imported. The community
  votes still land.

---

## 8. PDF / TXT import behaviour

- pdfminer.six text extraction (PDF) → `qblock_text` adapter.
- Recognises `QUESTION N` blocks, `A.` / `B.` / ... options,
  `Answer:`, optional `Explanation:`.
- Multi-answer: contiguous letters (`Answer: BD`) → expanded.
- Text-only. **No OCR.** Image-only PDFs parse to 0 rows.

---

## 9. What has been completed

Phases 1 through 16a + a series of post-milestone fixes:

- Phase 1 — bootstrapping (FastAPI / Alembic / settings).
- Phase 2 — auth + RBAC (admin / candidate roles, sessions, CSRF).
- Phase 3 — providers / courses / exams catalog CRUD.
- Phase 4 — topics CRUD + bulk topic assign.
- Phase 5 — Excel import pipeline (column-mapping wizard +
  normalize + validate + dedup + confirm + audit + soft-lock).
- Phase 6 — Question bank CRUD (manual create, edit, retire,
  restore, options replace, explanation save, source_import_id
  filter).
- Phase 7 — exam attempts (start, navigate, answer, submit, expire).
- Phase 8 — scoring (single + multiple).
- Phase 9 — practice flow (resume, finalise, recompute on submit).
- Phase 10 — reports (per-attempt review).
- Phase 11 — MVP deploy hardening (loopback / 8001 binding,
  systemd, healthcheck, `_layout` polish, `imports.title`).
- Phase 12 — admin question reports queue.
- Phase 13 — community-signal import: schema columns, parser,
  `community_discussion_sources` table, voting tally extraction.
- Phase 16a — admin Community tab (read-only) with consensus chip.

Post-milestone fixes (today, 2026-05-04):

- `feat(imports): support multi-format dump import (Milestone 1)` —
  commit `a830556` — XLSX / saved HTML / PDF / TXT adapter
  architecture + detector + `imports.detected_format`.
- `docs(reports): record Milestone 1 LXC redeploy + post-deploy
  verification` — commit `6126869`.
- `feat(imports): add review links for duplicate dump workflows` —
  commit `c3e925c` — Recent imports `Review questions` link,
  duplicate-info banner on preview, source_import context header on
  `/admin/questions`, runbook section.
- `fix(imports): treat combined options as satisfying required
  answer fields` — commit `64b0a85` — UI no longer flags
  `option_a`/`option_b` red when `combined_options` is mapped.
  `motathem` rerouted from `explanation` to `reference`.
  `loaicauhoi` aliased to `question_type`. Position-0 substring
  match beats buried substring (so `Tags (...)` wins `tags` not
  `combined_options`). `auto_map` de-duplicates canonicals.
- `fix(imports): normalize Excel choice question type and
  multi-answer keys` — commit `9335105` — `_normalize_question_type`
  alias table; storage cap raised A–E → A–F across validator /
  question_service / attempt_service; numeric `1..6` → A..F path
  fixed.
- This summary — commit on top of `9335105`, hash recorded in
  the changelog after push.

Other ground-truth artefacts:

- SSH skill at `.claude/skills/ssh/SKILL.md` and the matching
  alias rule in `~/.ssh/config`.
- Runbook `docs/ops/exam-platform-import-runbook.md` covers
  multi-format, combined_options, qtype aliases, and the
  duplicate-review workflow.
- Local changelog `docs/reports/changelog-local.md` carries every
  uncommitted-or-recently-committed entry until the next
  `project-changelog.md` fold-in.

---

## 10. Live smoke / import results

State on the LXC at the time of writing (DB + healthcheck verified):

| Import | Format | Total rows | Confirmed `questions` | Notes |
|---|---|---|---|---|
| `#137` | XLSX | 40 | 37 imported | 3 row errors carried over from earlier seed |
| `#138` | HTML | 57 | 57 imported | 57 community sources, 0 explanations (saved page lacked discussion body) |
| `#139` | PDF | 166 | 164 imported | 164 explanations (`Answer:` + `Explanation:` blocks) |
| `#142` | XLSX | 40 | 0 (unconfirmed) | Re-staged today after the qtype fix: ok=4, duplicate=35, error=1. Row 9 has 8 listed options + `correct_answer=7`. |

`curl /healthz` → `{"status":"ok","db":"ok","redis":"ok"}`.

All imported questions land under `exam_id=1` with status `imported`
(private/draft). Nothing has been published. Operators can review
via:

```
/admin/questions?source_import_id=137   # 37 rows
/admin/questions?source_import_id=138   # 57 rows
/admin/questions?source_import_id=139   # 164 rows
```

---

## 11. Known issues / current bugs / limitations

- **Browser upload UI is not automated in agent sessions.** The
  agent has no admin cookie. Backend signals (route reachability,
  no template render exceptions, DB-level counts) are the proxy.
  Operator must eyeball the actual mapping / preview pages on each
  significant deploy.
- **Some imports are staged but not confirmed.** A `normalized`
  status means the operator still has to step through preview
  and click Confirm. #142 in particular sits at `normalized`.
- **Recent imports UI** has the new Imported / Review-questions
  columns but might still feel cluttered on a small viewport.
  Polish is welcome but not blocking.
- **Practice / test-taking flow is not yet usable for guests.**
  Authentication is required for every attempt today.
- **Imported questions are in the bank but there is no admin "play
  this dump as a test" CTA yet.** Phase 17 below.
- **Excel rows with > 6 options error.** A–F is the storage cap.
  Row 9 of #142 is the canonical example.
- **HTML explanations are not imported** unless the saved page
  carries the discussion body inline.
- **PDF parser has no OCR.** Image-only / scanned PDFs parse to
  zero rows.
- **Guest practice without login is not implemented.** Only
  partially scaffolded (the `attempts.guest_token` column exists,
  the `ck_attempts_owner` constraint enforces "user_id OR
  guest_token", but the public router and guest-token issuance UI
  do not exist yet).
- **CDEA / enrichment / external search not implemented.**
  Deliberately deferred.
- **Imports `#137`/`#138`/`#139` are test fixture data.** Keep them
  for QA unless you have explicit operator approval to soft-retire.

---

## 12. What to do next

Suggested ordering (top → bottom):

1. **Browser QA** of the routes that backend tests already cover.
   Open in this order on a fresh admin login session:
   - `/admin/imports` (look for new Imported / Review questions columns)
   - `/admin/imports/137/done` → `/admin/questions?source_import_id=137`
   - `/admin/imports/138/done` → `/admin/questions?source_import_id=138`
   - `/admin/imports/139/done` → `/admin/questions?source_import_id=139`
   - `/admin/imports/142/mapping` (verify no red `option_a/b`,
     green "combined options" banner, no duplicate-canonical
     warning)
   - `/admin/imports/142/preview` (verify counts ok=4, dup=35,
     error=1)
2. **Polish Recent imports UI** if it still feels visually noisy.
3. **Decide #142 fate** — confirm the 4 ok rows, mark the
   duplicates as skip if you don't want them re-tracked, fix or
   document row 9 (8-option case).
4. **Phase 17** — admin practice preview for imported dumps (an
   admin can launch a draft/private exam as a private practice
   attempt, no public exposure).
5. **Phase 18** — guest / public practice mode with `guest_token`
   issuance + secure review-by-token.
6. **Phase 19** — review UX (selected vs correct, explanation,
   missing-explanation fallback, multi-answer scoring transparency).
7. **Phase 20** — CDEA evidence cache foundation (uploaded
   explanations first, then question_references / source_domains /
   evidence_fetch_logs).
8. **Phase 21** — optional external enrichment / search
   (cache-first; vendor/official docs preferred; never scrape
   ExamTopics / PassLeader / PrepAway / ActualTests / VCEGuide).
9. **Phase 22** — cleanup / ops hardening (cleanup fixture imports
   if approved, revert LAN 8001 exposure if desired, improve 403
   page, add browser E2E tests, automate backup/deploy runbook).

---

## 13. Future phases

### Phase 17 — Admin practice preview for imported dumps

- Admin can launch a practice attempt against a draft / private
  exam without publishing it.
- No public exposure.
- The Done page (`/admin/imports/{id}/done`) gets a "Start practice
  preview" CTA next to "Review imported questions".
- Reuses the existing attempt machinery (`attempt_service`),
  scoped via the admin role.

### Phase 18 — Guest / public practice mode

- Published exams playable without login.
- Guest attempt token issued via short-lived signed cookie.
- Secure review-by-token (token in URL → finalised attempt only).
- Draft / private exams remain protected.
- Wires up `attempts.guest_token` (column already exists) +
  `ck_attempts_owner` (constraint already exists).

### Phase 19 — Result / review UX

- Show selected answer alongside correct answer.
- Correct / wrong indicator per option.
- Explanation rendering (overall + per-option when present).
- Graceful fallback when explanation is missing ("No explanation
  recorded for this question yet").
- Multi-answer scoring breakdown ("you picked 2/3 correct, 1
  missed").

### Phase 20 — CDEA evidence cache foundation

- Use uploaded explanations first.
- Surface community votes / `discussion_url` / `external_question_id`
  metadata next to the question.
- New tables: `question_references`, `source_domains`,
  `evidence_fetch_logs`.
- **No external fetch** until Phase 21 explicitly turns it on.

### Phase 21 — External enrichment / search (optional)

- Official / vendor docs first (Cisco, Microsoft Learn, AWS docs,
  RFCs, etc.).
- Cache results in `question_references` keyed by
  (canonical_url, question_id).
- One search per question at most; no per-page repeated search.
- **Block list:** `examtopics.com`, `passleader.com`,
  `prepaway.com`, `actualtests.com`, `vceguide.com`. Never scrape
  copyrighted dump sites.

### Phase 22 — Cleanup / ops hardening

- Cleanup fixture imports `#137`/`#138`/`#139` once they have
  served QA (operator approval required; SQL plan is in
  `plans/reports/gate-a1-260502-cleanup.sql`).
- Revert LAN 8001 exposure to loopback-only if you no longer need
  cross-host access.
- Improve the 403 page (currently a plain text response).
- Add browser E2E tests (Playwright is in the dev-extra group).
- Automate the backup / deploy runbook into `make` targets or a
  small Bash script that mirrors the manual steps in
  `docs/ops/exam-platform-import-runbook.md`.

---

## 14. Operational runbook summary

### Check service / health

```bash
ssh exam-lxc 'systemctl is-active exam-platform-web.service'
ssh exam-lxc 'curl -fsS http://127.0.0.1:8001/healthz'
ssh exam-lxc 'journalctl -u exam-platform-web.service -n 100 --no-pager'
```

### Deploy a code change

```bash
# (1) Local: tests + lint
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run pytest

# (2) Sync only the touched files (or rsync the tree)
scp app/.../changed.py exam-lxc:/srv/exam-platform/app/.../

# (3) Fix ownership + restart only the web service
ssh exam-lxc 'chown exam-platform:exam-platform /srv/exam-platform/<paths>'
ssh exam-lxc 'systemctl restart exam-platform-web.service'
ssh exam-lxc 'curl -fsS http://127.0.0.1:8001/healthz'
```

### Migrations

```bash
ssh exam-lxc 'cd /srv/exam-platform && uv run alembic current'
ssh exam-lxc 'cd /srv/exam-platform && uv run alembic upgrade head'
```

Always backup the DB before a forward migration on this LXC:

```bash
ssh exam-lxc '
TS=$(date -u +%Y%m%dT%H%M%SZ)
sudo -u postgres pg_dump --format=custom \
  --file=/var/backups/exam-platform/exam_platform_db-${TS}.dump \
  exam_platform_db
echo "BACKUP_PATH=/var/backups/exam-platform/exam_platform_db-${TS}.dump"
'
```

### Review imports

- `/admin/imports` — Recent imports table (latest 20).
- `/admin/imports/{id}/preview` — staged rows, filterable by status.
- `/admin/questions?source_import_id=<id>` — questions committed
  by that import.

### Status interpretation cheatsheet

| Saw | Means | Do |
|---|---|---|
| `imp.status=normalized` and `failed_questions>0` | Rows staged but some errored. | Open preview, filter by `errors`, fix mapping or skip the offending rows. |
| `dup_count>0` on preview | Some rows already exist as questions in this exam. | Open Recent imports, find the previous import, click Review questions. |
| Review questions button absent on a row | Import created zero live questions. | Open the import to inspect staged state. |
| Health says `redis=fail` | Redis daemon is down. | `sudo systemctl status redis-server`. Do **not** restart anything else. |

### Handling duplicate rows

The dedup step matches on **content hash**, not on which import a
question came from, so the preview cannot auto-resolve which prior
import a duplicate row belongs to. Use the Recent imports table to
locate the previous import by title / filename / format / id; click
Review questions; or fall back to the per-exam `/admin/questions?exam_id=<id>`
list.

---

## 15. Git / deploy history

- Branch: `master`.
- Remote: configured per `.git/config` (origin = the upstream
  copy of this repo).
- Recent commit chain (most recent first):

  ```
  9335105  fix(imports): normalize Excel choice question type and multi-answer keys
  64b0a85  fix(imports): treat combined options as satisfying required answer fields
  c3e925c  feat(imports): add review links for duplicate dump workflows
  6126869  docs(reports): record Milestone 1 LXC redeploy + post-deploy verification
  a830556  feat(imports): support multi-format dump import (Milestone 1)
  ad55c68  chore(scripts): lower create_admin password floor to 10 chars
  12fee63  docs(gate): add Gate-A1 cleanup SQL
  aa7d00a  docs(ops): document venv ownership recovery runbook
  ```

- This summary (`summary.md`) ships in a follow-on `docs(project): ...`
  commit on top of `9335105`.

### Untracked items to **never** commit

- `DESIGN.md` — scratch design notes, not for the public repo.
- `Template Dump/` — fixture XLSX / HTML / PDF data, large and
  copyrighted-by-vendor in places.
- `plans/reports/gate-a1-260502-seed.xlsx` — operator-only seed.
- DB backups (`*.dump`).
- Secrets / `.env` / `cookies.txt`.
- SSH keys / `~/.ssh/config` (lives outside the repo, kept that way).

The `.gitignore` already covers most of these; the `git status`
warning at commit time is the safety net for the rest.

---

## 16. Safety boundaries

These rules are non-negotiable unless the operator approves explicitly:

- **No cleanup SQL.** The Gate-A1 cleanup plan exists at
  `plans/reports/gate-a1-260502-cleanup.sql` and is gated on
  operator approval.
- **No `DELETE` / `UPDATE` of confirmed `questions` / `imports`.**
  Re-staging `import_items` (staging data) is OK when the operator
  asks for it.
- **No internet fetch / scrape.** All parsers are local-file.
  External enrichment is Phase 21 territory.
- **No nginx / cloudflared / Postgres / Redis config edits.**
  Templates exist under `ops/` for a future hand-off; nothing in
  this repo writes to those configs.
- **No blog / unrelated service touching.** Only
  `exam-platform-web.service` is in scope for restart.
- **Always backup the DB before a forward migration.** See § 14.
- **Always use the `exam-lxc` SSH alias.** Never guess
  `user@host`. The `ssh` skill diagnoses connectivity issues.
- **Never commit secrets / dumps / backups / private keys / `.env`.**
  Keep large fixture data in `Template Dump/` (gitignored).

---

## 17. Final current status

- **Milestone 1 import / parser:** done and deployed. Multi-format
  (XLSX / HTML / PDF / TXT) lands rows end-to-end. 137 / 138 / 139
  fixture imports green.
- **Excel #142 mapping / validator fix:** done and deployed.
  `combined_options` no longer trips the option_a/b required check;
  `one_choice` / `multi_choice` / `choice` qtype values resolve;
  numeric `1..6` correct_answer maps to A..F. #142 went from
  40 errors → 4 ok + 35 duplicate + 1 legitimate edge-case error.
- **Recent imports UX:** done and deployed. Imported count column
  + Review questions link + duplicate-context banner on preview +
  source_import context header on `/admin/questions`.
- **Browser QA:** **pending** operator verification (no admin
  cookie in agent sessions).
- **Practice exam flow (admin or guest):** **not done yet.**
  Phases 17–18.
- **Result / review UX polish:** **not done yet.** Phase 19.
- **CDEA / external enrichment:** **future phase.** Phases 20–21.
- **Cleanup / ops hardening:** **future phase.** Phase 22.

The repo is in a green state as of commit `9335105`: all 326 hermetic
tests pass, mypy is clean, ruff is clean, and the LXC service is
active with `db=ok` and `redis=ok`. The next operator can pick up at
§ 12 with no surprises.
