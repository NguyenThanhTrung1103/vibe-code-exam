"""PDF dump parser for the `QUESTION N` block format.

Extracts text via `pdfminer.six` then delegates to `qblock_text_adapter`'s
pure parser. Imperfect extraction (page headers/footers, soft line breaks)
is tolerated by the underlying regex parser; rows that don't satisfy the
shape are silently skipped — no crash on a single bad page.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from app.services.parsers.base import ParsedQuestion
from app.services.parsers.qblock_text_adapter import parse_qblock_text

NAME = "qblock_pdf"
PRIORITY = 60


class QBlockPdfAdapter:
    name = NAME
    priority = PRIORITY

    def detect(self, *, filename: str, head_bytes: bytes) -> bool:
        if not filename.lower().endswith(".pdf"):
            return False
        # PDFs start with the literal '%PDF-' header.
        return head_bytes.startswith(b"%PDF-")

    def parse(
        self,
        *,
        file_path: Path,
        column_mapping: dict[str, str | None] | None = None,
    ) -> Iterator[ParsedQuestion]:
        try:
            from pdfminer.high_level import extract_text  # noqa: PLC0415
        except Exception as exc:  # pragma: no cover — dep not installed
            raise RuntimeError(
                "pdfminer.six is required for PDF parsing. "
                "Install with `uv add pdfminer.six` and redeploy."
            ) from exc
        text = extract_text(str(file_path)) or ""
        yield from parse_qblock_text(text, source_format=self.name, source_url=str(file_path))
