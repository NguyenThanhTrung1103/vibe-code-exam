"""Upload validation — extension + magic-bytes + size cap.

Used by Phase 05 admin import upload (`admin/imports`). XLSX is a ZIP
container so the magic bytes are `PK\\x03\\x04`. We deliberately do not
trust the `Content-Type` browser header; check the bytes themselves.

`validate_xlsx_bytes(data, *, max_bytes, filename)` raises
`UploadValidationError` on any failure. It is the single source of truth
for "is this XLSX safe to accept on disk".
"""

from __future__ import annotations

import os

XLSX_MAGIC: bytes = b"PK\x03\x04"
ALLOWED_EXTS: tuple[str, ...] = (".xlsx",)


class UploadValidationError(ValueError):
    """User-fixable error in an uploaded file."""


def _ext_ok(name: str) -> bool:
    return os.path.splitext(name.lower())[1] in ALLOWED_EXTS


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


__all__ = ["ALLOWED_EXTS", "UploadValidationError", "XLSX_MAGIC", "validate_xlsx_bytes"]
