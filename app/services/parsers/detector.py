"""Format detector — picks the highest-priority adapter that claims a file.

Detection is signature-based and reads only the first kilobyte. The chosen
adapter is identified by `name` (also stored on `imports.detected_format`).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.services.parsers.base import ParserAdapter
from app.services.parsers.examtopics_html_adapter import ExamTopicsHtmlAdapter
from app.services.parsers.qblock_pdf_adapter import QBlockPdfAdapter
from app.services.parsers.qblock_text_adapter import QBlockTextAdapter
from app.services.parsers.xlsx_adapter import XlsxAdapter

# Higher priority = tried first. XLSX > HTML > PDF > TXT keeps existing
# canonical XLSX behaviour; HTML beats text-fallback for ExamTopics-style
# saves where both `.html` and the markers are present.
_REGISTRY: list[ParserAdapter] = [
    XlsxAdapter(),
    ExamTopicsHtmlAdapter(),
    QBlockPdfAdapter(),
    QBlockTextAdapter(),
]


def list_adapters() -> Iterable[ParserAdapter]:
    return tuple(_REGISTRY)


def detect_adapter(*, filename: str, file_path: Path) -> ParserAdapter | None:
    """Return the highest-priority adapter that claims this file, else None."""
    head = b""
    try:
        with open(file_path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return None
    for adapter in sorted(_REGISTRY, key=lambda a: -a.priority):
        try:
            if adapter.detect(filename=filename, head_bytes=head):
                return adapter
        except Exception:  # pragma: no cover — adapter detect must never fail noisily
            continue
    return None
