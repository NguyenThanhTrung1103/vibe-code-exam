"""Phase 05 — per-row validator. Pure functions, no DB.

Returns a `ValidationResult` per row. Caller persists it onto the
matching `import_items` row.

Phase 13 extension: optional community-signal columns (`discussion_url`,
`external_question_id`, `discussion_count`, `vote_a..vote_f`) are accepted
when present and surfaced under `canonical['community']`. Invalid community
data degrades to a row-level warning (not error) and is dropped — the
core question import still proceeds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import ImportItemStatus
from app.services.import_community import extract_community_payload

ALLOWED_DIFFICULTY = {"easy", "medium", "hard"}
ALLOWED_QTYPE = {"single", "multiple", "true_false"}
OPTION_LABELS = ("A", "B", "C", "D", "E")  # 1:1 with option_a..option_e
MAX_QUESTION_LEN = 4000
MAX_OPTION_LEN = 1000


@dataclass(slots=True)
class ValidationResult:
    status: ImportItemStatus
    error_message: str | None = None
    warning_message: str | None = None
    canonical: dict[str, Any] = field(default_factory=dict)


def validate_row(normalized: dict[str, Any]) -> ValidationResult:
    """Validate a normalized row. `normalized` may have None values."""
    errors: list[str] = []
    warnings: list[str] = []

    q = normalized.get("question_text")
    if not q:
        errors.append("question_text required")
    elif len(q) > MAX_QUESTION_LEN:
        errors.append(f"question_text exceeds {MAX_QUESTION_LEN} chars")

    options = _collect_options(normalized, errors)
    correct = _collect_correct_answer(normalized, options, errors)

    qtype = normalized.get("question_type") or _infer_question_type(correct)
    if qtype not in ALLOWED_QTYPE:
        errors.append(f"question_type {qtype!r} not in {sorted(ALLOWED_QTYPE)}")

    difficulty = (normalized.get("difficulty") or "medium").lower() or "medium"
    if difficulty not in ALLOWED_DIFFICULTY:
        warnings.append(
            f"difficulty {difficulty!r} not in {sorted(ALLOWED_DIFFICULTY)} — defaulted to 'medium'"
        )
        difficulty = "medium"

    # Phase 13 — optional community signal. Mutates `warnings` in place;
    # bad URL / bad votes downgrade the row to warning but never to error.
    community = extract_community_payload(normalized, warnings=warnings)

    canonical: dict[str, Any] = {
        "question_text": q,
        "question_type": qtype,
        "difficulty": difficulty,
        "topic": normalized.get("topic"),
        "options": options,  # list[(label, text)]
        "correct_answer": correct,  # list[label]
        "explanation": normalized.get("explanation"),
        "reference": normalized.get("reference"),
        "tags": normalized.get("tags"),
    }
    if community is not None:
        canonical["community"] = community

    if errors:
        return ValidationResult(
            status=ImportItemStatus.error,
            error_message="; ".join(errors),
            canonical=canonical,
        )
    if warnings:
        return ValidationResult(
            status=ImportItemStatus.warning,
            warning_message="; ".join(warnings),
            canonical=canonical,
        )
    return ValidationResult(status=ImportItemStatus.ok, canonical=canonical)


def _collect_options(normalized: dict[str, Any], errors: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for label in OPTION_LABELS:
        key = f"option_{label.lower()}"
        v = normalized.get(key)
        if v:
            text = v if isinstance(v, str) else str(v)
            if len(text) > MAX_OPTION_LEN:
                errors.append(f"option {label} exceeds {MAX_OPTION_LEN} chars")
            out.append((label, text))
    if len(out) < 2:
        errors.append("at least two options required")
    return out


def _collect_correct_answer(
    normalized: dict[str, Any],
    options: list[tuple[str, str]],
    errors: list[str],
) -> list[str]:
    """Normalize a correct_answer cell against the parsed options.

    Accepts (in order of fallback):
      1. Letter labels:  A / B / ... / F  (single or multi via ; , space)
      2. Numeric labels: 1..6 → A..F
      3. Verbatim option text matching one of `options` (case-fold compare)

    Anything that fails all three lands as a row-level error with the
    message `Cannot resolve correct_answer from value: <value>`.
    """
    raw = normalized.get("correct_answer")
    if not raw:
        errors.append("correct_answer required")
        return []
    if isinstance(raw, list):
        entries = [str(x).strip() for x in raw if str(x).strip()]
    else:
        text = str(raw)
        # Split on , ; newline. Don't split on spaces — option text often
        # contains spaces (e.g. "Sample answer A").
        entries = [
            s.strip() for s in text.replace(";", ",").replace("\n", ",").split(",") if s.strip()
        ]
    # Multi-answer convenience: PDF/HTML dumps frequently express multi-select
    # answers as a contiguous run of A–F letters (e.g. "BD", "ACE") with no
    # separator. Expand any such entry into individual single-letter entries
    # so the per-letter resolution path below sees them as A, C, E.
    expanded: list[str] = []
    for entry in entries:
        u = entry.upper()
        if 2 <= len(u) <= 6 and all(ch in "ABCDEF" for ch in u):
            expanded.extend(u)
        else:
            expanded.append(entry)
    entries = expanded
    valid_labels = {label for label, _ in options}
    text_to_label: dict[str, str] = {
        opt_text.casefold().strip(): label for label, opt_text in options if opt_text
    }
    chosen: list[str] = []
    for entry in entries:
        u = entry.upper()
        # 1. Single alpha → letter label path (keeps "unknown label" wording
        #    for things like 'Z' / 'X' that look like labels but aren't A..F).
        if len(u) == 1 and u.isalpha():
            if u not in OPTION_LABELS:
                errors.append(f"correct_answer label {u!r} unknown")
                continue
            if u not in valid_labels:
                errors.append(f"correct_answer label {u!r} has no matching option")
                continue
            if u not in chosen:
                chosen.append(u)
            continue
        # 2. Numeric 1..N
        if u.isdigit():
            n = int(u)
            if 1 <= n <= len(OPTION_LABELS):
                letter = OPTION_LABELS[n - 1]
                if letter in valid_labels and letter not in chosen:
                    chosen.append(letter)
                    continue
                errors.append(f"correct_answer numeric {u!r} → {letter!r} has no matching option")
                continue
            errors.append(f"correct_answer numeric {u!r} out of range")
            continue
        # 3. Verbatim option text (case-insensitive)
        match = text_to_label.get(entry.casefold().strip())
        if match and match not in chosen:
            chosen.append(match)
            continue
        errors.append(f"Cannot resolve correct_answer from value: {entry!r}")
    if not chosen and "correct_answer required" not in errors:
        errors.append("correct_answer must reference at least one option")
    return chosen


def _infer_question_type(correct: list[str]) -> str:
    if len(correct) > 1:
        return "multiple"
    return "single"
