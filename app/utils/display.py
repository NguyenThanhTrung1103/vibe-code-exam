"""Display helpers for templates.

Keeps presentation logic out of routes/services so we don't accidentally
mutate the DB just to fix a label.
"""

from __future__ import annotations


def pretty_vendor_name(name: str | None) -> str:
    """Human-readable vendor/provider name for public cards.

    Rules (KISS — no magic word lists):
      * None / empty → "" (caller decides fallback).
      * If the string already contains an upper-case letter (e.g. "AWS",
        "CompTIA", "Palo Alto"), trust the admin's casing and return as-is
        so acronyms are not mangled.
      * Otherwise (all lower-case input like "fortinet" or "palo alto"),
        title-case each whitespace-separated token.

    Single-letter junk like "p" or "P" is *not* auto-fixed here — that is
    a data problem; use `scripts/cleanup_providers.py` to rename it.
    """
    if not name:
        return ""
    cleaned = name.strip()
    if not cleaned:
        return ""
    if any(ch.isupper() for ch in cleaned):
        return cleaned
    return " ".join(token.capitalize() for token in cleaned.split())
