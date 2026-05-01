"""Phase 05 — per-row validator. Pure functions, no DB.

Returns a `ValidationResult` per row. Caller persists it onto the
matching `import_items` row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import ImportItemStatus

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

    canonical = {
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
    raw = normalized.get("correct_answer")
    if not raw:
        errors.append("correct_answer required")
        return []
    if isinstance(raw, list):
        labels_raw = raw
    else:
        # Accept "A", "A,B", "A;B", "A B"
        text = str(raw)
        labels_raw = [
            s.strip() for s in text.replace(";", ",").replace(" ", ",").split(",") if s.strip()
        ]
    valid_labels = {label for label, _ in options}
    chosen: list[str] = []
    for entry in labels_raw:
        u = str(entry).upper()
        if u not in OPTION_LABELS:
            errors.append(f"correct_answer label {u!r} unknown")
            continue
        if u not in valid_labels:
            errors.append(f"correct_answer label {u!r} has no matching option")
            continue
        if u not in chosen:
            chosen.append(u)
    if not chosen and "correct_answer required" not in errors:
        errors.append("correct_answer must reference at least one option")
    return chosen


def _infer_question_type(correct: list[str]) -> str:
    if len(correct) > 1:
        return "multiple"
    return "single"
