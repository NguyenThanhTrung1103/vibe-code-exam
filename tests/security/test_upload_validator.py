"""Phase 09 — XLSX upload validator unit tests."""

from __future__ import annotations

import pytest

from app.security.upload_validator import (
    XLSX_MAGIC,
    UploadValidationError,
    validate_xlsx_bytes,
)


def _good_xlsx(payload_size: int = 1024) -> bytes:
    # Magic + filler — enough to look like a real ZIP body without being one.
    return XLSX_MAGIC + b"\x00" * (payload_size - len(XLSX_MAGIC))


def test_accepts_small_well_formed_xlsx() -> None:
    validate_xlsx_bytes(_good_xlsx(), max_bytes=10_000, filename="ok.xlsx")


def test_rejects_empty_filename() -> None:
    with pytest.raises(UploadValidationError, match="filename is required"):
        validate_xlsx_bytes(_good_xlsx(), max_bytes=10_000, filename="")


def test_rejects_disallowed_extension() -> None:
    with pytest.raises(UploadValidationError, match="unsupported extension"):
        validate_xlsx_bytes(_good_xlsx(), max_bytes=10_000, filename="bad.csv")


def test_rejects_executable_renamed_xlsx() -> None:
    fake = b"MZ\x90\x00" + b"\x00" * 100  # Windows PE header magic
    with pytest.raises(UploadValidationError, match="bad magic bytes"):
        validate_xlsx_bytes(fake, max_bytes=10_000, filename="hidden.xlsx")


def test_rejects_oversized_file() -> None:
    big = _good_xlsx(payload_size=5_000)
    with pytest.raises(UploadValidationError, match="file too large"):
        validate_xlsx_bytes(big, max_bytes=1_000, filename="big.xlsx")


def test_rejects_empty_file() -> None:
    with pytest.raises(UploadValidationError, match="file is empty"):
        validate_xlsx_bytes(b"", max_bytes=10_000, filename="empty.xlsx")


def test_rejects_text_file_renamed_xlsx() -> None:
    txt = b"hello world this is plain text" * 4
    with pytest.raises(UploadValidationError, match="bad magic bytes"):
        validate_xlsx_bytes(txt, max_bytes=10_000, filename="notes.xlsx")


def test_extension_check_is_case_insensitive() -> None:
    validate_xlsx_bytes(_good_xlsx(), max_bytes=10_000, filename="OK.XLSX")
