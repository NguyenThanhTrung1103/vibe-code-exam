"""Filesystem path constants for the app package — no other imports."""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
