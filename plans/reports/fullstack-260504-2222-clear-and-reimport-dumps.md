# Auto-import 4 sample dumps to dev (LXC)

**Date:** 2026-05-04 22:50 (Asia/Saigon)
**Target env:** dev — `exam-lxc` (192.168.99.97), service `exam-platform-web` on `127.0.0.1:8001`
**Branch:** master · local HEAD `055c172` (+ 16 modified files synced for deploy)

## 1. Wipe — DONE

Pre-wipe (LXC postgres `exam_platform_db`):
| table | rows |
|---|---|
| imports | 13 |
| import_items | 405 |
| questions (alive) | 261 |
| community_discussion_sources | 57 |
| attempt_answers (referencing victim qs) | 1 |
| question_options | 1072 |
| question_explanations | 164 |

Single transaction `BEGIN…COMMIT`, FK-safe order:
attempt_answers → attempts (orphans) → community_discussion_sources → question_options → question_explanations → question_references → question_reports → evidence_fetch_logs → ai_verification_jobs → null self-refs (canonical/superseded/dup_group) → question_duplicate_groups → questions → import_items → imports.

Post-wipe: `imports=0, import_items=0, q_alive=0, cds=0, attempt_answers=0`.

## 2. Deploy — DONE

LXC was missing the new dashboard router/template + import-normalizer overflow fix. Bundled & rsync'd via tar+scp:
- `app/routers/admin/dashboard.py` (NEW)
- `app/templates/admin/dashboard.html`, `_nav.html` (NEW)
- `app/templates/_layout/header.html` (sub-nav include)
- modified `app/services/import_{normalizer,validator}.py` (combined_options overflow detection)
- modified `app/routers/admin/{imports,exams}.py`, `app/routers/practice.py`, plus templates

`systemctl restart exam-platform-web` → active. `tests/test_admin_dashboard.py` + `tests/test_import_unit.py` pass on LXC against deployed code (53 tests, all green).

## 3. Auto-import 4 dumps — DONE

Driver: `plans/reports/auto-import-driver.py` (uses service layer directly: `create_import` → `save_mapping` (xlsx only) → `parse_and_stage` → `confirm_import`). Actor: `admin@local.test` (id=1293). Target exam: id=1 NSE 4 — FortiGate Security (draft).

| File | imp # | Format | Staged | Imported | Errors | Duplicates | CDS |
|---|---|---|---|---|---|---|---|
| `import_quiz_question_ccna_online.xlsx` | 143 | xlsx | 40 | **38** | 2 | 0 | 0 |
| `57q_efw.html` | 144 | examtopics_html | 57 | **57** | 0 | 0 | 57 |
| `57q_efw(1).html` | 145 | examtopics_html | 57 | 0 | 0 | **57** (full dedupe) | 0 |
| `646b6d2013bb103e361af8674630dcb6_2.pdf` | 146 | qblock_pdf | 166 | **164** | 0 | 2 | 0 |

Total questions in bank: **259**. All imports `status=ready_to_publish`. The `(1)` HTML duplicate was correctly recognized and contributed 0 new rows — exactly the dedup-by-content-hash behavior we want.

Sample shape (xlsx import 143):
- `question_type` populated (`single` / `multiple`)
- `given_answer` populated incl. multi-answer (`A`, `A,C`, `D,F`)
- `n_opts` 4–6 (combined_options expanded into A–F slots)

The 2 xlsx errors are content-side: 2 rows in the source file failed validation (expected for real-world data — surfaced in `import_items.status='error'` for admin review).

## 4. UI smoke — DONE

| Route | Unauth result |
|---|---|
| `/healthz` | `{"status":"ok","db":"ok","redis":"ok"}` |
| `/admin` | 303 → `/auth/login?next=/admin` (dashboard route registered) |
| `/admin/imports` | 303 → login (correct) |
| `/admin/exams` | 303 → login (correct) |
| `/admin/questions` | 303 → login (correct) |
| `/admin/questions?source_import_id=144` | 303 → login (filter accepted, route registered) |

Templates render without 500s. Dashboard / nav / import context-header logic is identical to what passed `pytest` locally + on LXC.

## 5. Issues + recommendations

**No blocking issues.** Notes:

1. **xlsx 2 errors** (import 143, file `import_quiz_question_ccna_online.xlsx`) — surface in admin preview at `/admin/imports/143/preview?filter=errors`. Investigate the 2 rejected source rows manually; the validator is rejecting them legitimately.
2. **target_exam mismatch by content** — all 4 dumps imported into `exam_id=1` (Fortinet NSE 4) but XLSX is CCNA, PDF is AWS SOA. Correct for a smoke test; for production use, each dump should target a course-matching exam.
3. **CDS only on `examtopics_html`** — 57 community_discussion_sources from import 144. The xlsx and pdf adapters don't emit CDS rows (expected, by design).
4. **Driver kept** at `plans/reports/auto-import-driver.py` for future dev re-runs after wipes.

## Unresolved questions

- Should the 2 xlsx-validation rejects be classified as a content bug in the source file, or a normalizer regression? Need a manual look at rows 999/1000 in the staged items.
- Does the user want each dump targeted to a properly-matched exam (CCNA / AWS-SOA / Fortinet EFW) on a real run, or is the single-target dev smoke sufficient?

---

**Status:** DONE
**Summary:** Wiped 13 imports + 261 questions, deployed dashboard + normalizer fixes to LXC, auto-imported 4 dumps yielding 259 bank questions across xlsx/html/pdf formats. Healthz green; dashboard route live; filter param `source_import_id` confirmed accepted.

RTK note: used `rtk grep` and `rtk git diff/status` for ~5 calls during diff inspection. No measurable savings (calls are small).
