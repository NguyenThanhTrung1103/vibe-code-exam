"""Slug helper — wraps python-slugify with project-specific limits.

Constraints (Phase 04):
  * lower-case, digits, hyphens
  * length ≤ 64
  * no leading/trailing hyphen
  * never empty
"""

from __future__ import annotations

import re

from slugify import slugify as _slugify

SLUG_REGEX = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SLUG_MAX_LENGTH = 64


def make_slug(value: str, *, max_length: int = SLUG_MAX_LENGTH) -> str:
    """Generate a slug from `value`. Falls back to "n-a" if input is empty."""
    s = _slugify(value, max_length=max_length, lowercase=True, separator="-")
    if not s:
        return "n-a"
    return s


def is_valid_slug(slug: str) -> bool:
    return bool(SLUG_REGEX.fullmatch(slug))
