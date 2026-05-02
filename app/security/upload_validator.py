"""Upload validation — extension + magic-bytes + size cap.

Used by Phase 05 admin import upload (`admin/imports`). Originally
XLSX-only; Milestone 1 of the multi-format import refactor extended it
to also accept saved HTML pages, PDFs, and plain-text dumps. We
deliberately do not trust the `Content-Type` browser header; check the
bytes themselves.

Public API:
    `validate_xlsx_bytes(...)`   — XLSX-only (kept for legacy callers).
    `validate_upload_bytes(...)` — multi-format dispatcher used by the
                                   wizard.
"""

from __future__ import annotations

import os

XLSX_MAGIC: bytes = b"PK\x03\x04"
PDF_MAGIC: bytes = b"%PDF-"

# Allowed extensions per format family — drives the multi-format
# dispatcher below. Keep ALLOWED_EXTS as the legacy XLSX-only tuple so
# any caller still importing it observes the same behaviour as before.
ALLOWED_EXTS: tuple[str, ...] = (".xlsx",)
ALLOWED_EXTS_MULTIFORMAT: tuple[str, ...] = (
    ".xlsx",
    ".html",
    ".htm",
    ".pdf",
    ".txt",
    ".text",
)


class UploadValidationError(ValueError):
    """User-fixable error in an uploaded file."""


def _ext_of(name: str) -> str:
    return os.path.splitext(name.lower())[1]


def _ext_ok(name: str) -> bool:
    return _ext_of(name) in ALLOWED_EXTS


def validate_xlsx_bytes(
    data: bytes,
    *,
    max_bytes: int,
    filename: str,
) -> None:
    """Validate XLSX bytes. Raises `UploadValidationError` on any failure."""
    if not filename:
        raise UploadValidationError("filename is required")
    if not _ext_ok(filename):
        raise UploadValidationError(f"unsupported extension: {filename!r}; allowed: {ALLOWED_EXTS}")
    n = len(data)
    if n == 0:
        raise UploadValidationError("file is empty")
    if n > max_bytes:
        raise UploadValidationError(f"file too large: {n} bytes > {max_bytes}")
    if not data.startswith(XLSX_MAGIC):
        # Either the file is not a real ZIP/XLSX, or someone renamed an
        # executable to .xlsx. Either way: reject hard.
        raise UploadValidationError("file is not a valid .xlsx (bad magic bytes)")


def validate_upload_bytes(
    data: bytes,
    *,
    max_bytes: int,
    filename: str,
) -> str:
    """Validate any of the supported upload formats and return the family.

    Returns one of `xlsx` / `html` / `pdf` / `txt`. Raises
    `UploadValidationError` on extension/magic/size failures. Magic-byte
    checks per family:
        * xlsx → ZIP local-file-header `PK\\x03\\x04`
        * pdf  → `%PDF-`
        * html → first non-whitespace bytes must be `<` (very loose; saved
          pages frequently have a doctype/comment/script preamble)
        * txt  → no magic check beyond UTF-8/Latin-1 decodability — we
          just refuse files that contain a NUL in the first 4 KB.
    """
    if not filename:
        raise UploadValidationError("filename is required")
    ext = _ext_of(filename)
    if ext not in ALLOWED_EXTS_MULTIFORMAT:
        raise UploadValidationError(
            f"unsupported extension: {filename!r}; allowed: {ALLOWED_EXTS_MULTIFORMAT}"
        )
    n = len(data)
    if n == 0:
        raise UploadValidationError("file is empty")
    if n > max_bytes:
        raise UploadValidationError(f"file too large: {n} bytes > {max_bytes}")

    head = data[:4096]
    if ext == ".xlsx":
        if not data.startswith(XLSX_MAGIC):
            raise UploadValidationError("file is not a valid .xlsx (bad magic bytes)")
        return "xlsx"
    if ext == ".pdf":
        if not data.startswith(PDF_MAGIC):
            raise UploadValidationError("file is not a valid .pdf (bad magic bytes)")
        return "pdf"
    if ext in (".html", ".htm"):
        # Skip leading whitespace + UTF-8 BOM, then expect '<'.
        stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
        if not stripped.startswith(b"<"):
            raise UploadValidationError("file is not a valid HTML page (no '<' in head)")
        return "html"
    # .txt / .text — refuse if the head looks like a binary blob.
    if b"\x00" in head:
        raise UploadValidationError("text upload contains NUL bytes (binary file?)")
    return "txt"


__all__ = [
    "ALLOWED_EXTS",
    "ALLOWED_EXTS_MULTIFORMAT",
    "PDF_MAGIC",
    "UploadValidationError",
    "XLSX_MAGIC",
    "validate_upload_bytes",
    "validate_xlsx_bytes",
]
