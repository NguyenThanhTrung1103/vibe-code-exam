"""Format detector — picks the highest-priority adapter that claims a file.

Detection is signature-based and reads only the first kilobyte. The chosen
adapter is identified by `name` (also stored on `imports.detected_format`).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.services.parsers.base import ParserAdapter
from app.services.parsers.examtopics_html_adapter import ExamTopicsHtmlAdapter
from app.services.parsers.examtopics_pdf_adapter import (
    ExamTopicsPdfAdapter,
    detect_examtopics_pdf,
)
from app.services.parsers.qblock_pdf_adapter import QBlockPdfAdapter
from app.services.parsers.qblock_text_adapter import QBlockTextAdapter
from app.services.parsers.xlsx_adapter import XlsxAdapter

# Higher priority = tried first. ExamTopics PDF (80) beats HTML (70) and the
# generic QBLOCK PDF (60); HTML beats text-fallback for ExamTopics-style
# saves where both `.html` and the markers are present.
_REGISTRY: list[ParserAdapter] = [
    XlsxAdapter(),
    ExamTopicsPdfAdapter(),
    ExamTopicsHtmlAdapter(),
    QBlockPdfAdapter(),
    QBlockTextAdapter(),
]


def list_adapters() -> Iterable[ParserAdapter]:
    return tuple(_REGISTRY)


def detect_adapter(*, filename: str, file_path: Path) -> ParserAdapter | None:
    """Return the highest-priority adapter that claims this file, else None.

    Two-pass dispatch:
      1. Standard bytes-only `adapter.detect()` walk — fast, covers magic
         bytes + filename hints.
      2. Path-aware content sniff for ExamTopics PDFs whose filename
         doesn't mention `examtopics`. Runs only if pass 1 picked
         `qblock_pdf` (generic PDF) so we don't pay the pdfminer cost on
         every upload.
    """
    head = b""
    try:
        with open(file_path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return None
    chosen: ParserAdapter | None = None
    for adapter in sorted(_REGISTRY, key=lambda a: -a.priority):
        try:
            if adapter.detect(filename=filename, head_bytes=head):
                chosen = adapter
                break
        except Exception:  # pragma: no cover — adapter detect must never fail noisily
            continue
    if chosen is not None and chosen.name == "qblock_pdf":
        # Promote to ExamTopics PDF if the content actually looks like one.
        try:
            if detect_examtopics_pdf(filename=filename, file_path=file_path):
                for adapter in _REGISTRY:
                    if adapter.name == "examtopics_pdf":
                        return adapter
        except Exception:
            pass
    return chosen
