"""Phase 05 — text normalization + sanitization for imported rows.

Applied per-cell BEFORE storage. Goals:
  * Strip HTML tags + scripts (`bleach` with empty allowlist).
  * Normalise Unicode (NFKC).
  * Remove zero-width / RTL / LTR override chars.
  * Collapse internal whitespace; strip leading/trailing.

Safe to call on `None` (returns None).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import bleach  # type: ignore[import-untyped]

# Zero-width and bidi-override chars often used in obfuscated payloads.
_INVISIBLE_CHARS = re.compile(
    "["
    "​‌‍‎‏"  # zero-width / LRM / RLM
    "‪‫‬‭‮"  # bidi overrides
    "⁠⁡⁢⁣⁤"  # word/function joiners
    "﻿"  # BOM
    "]"
)
_INTERNAL_WS = re.compile(r"[ \t\r\f\v]+")
_LINE_RUN = re.compile(r"\n{3,}")


def normalize_text(value: str | None) -> str | None:
    """Return the cleaned, sanitized version of `value`. None passes through."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    # 1. Strip HTML / scripts via bleach with empty allowlist (full-strip).
    cleaned = bleach.clean(value, tags=[], attributes={}, strip=True)
    # 2. Unicode NFKC normalisation.
    cleaned = unicodedata.normalize("NFKC", cleaned)
    # 3. Remove invisible / direction-override chars.
    cleaned = _INVISIBLE_CHARS.sub("", cleaned)
    # 4. Whitespace collapse.
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _INTERNAL_WS.sub(" ", cleaned)
    cleaned = _LINE_RUN.sub("\n\n", cleaned)
    cleaned = cleaned.strip()
    return cleaned or None


def normalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply `normalize_text` to every string-valued field in `raw`.

    Non-string values (numbers, bools, dates) pass through untouched. Lists are
    normalised element-wise.
    """
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, str):
            out[k] = normalize_text(v)
        elif isinstance(v, list):
            out[k] = [normalize_text(x) if isinstance(x, str) else x for x in v]
        else:
            out[k] = v
    return out
