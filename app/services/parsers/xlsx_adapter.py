"""XLSX adapter — covers canonical *and* Vietnamese alias headers.

Wraps the existing `excel_parser.stream_rows` so the rest of the pipeline
sees the same canonical row dicts the Phase 05 importer always saw, but
through the new ParserAdapter contract. No new behaviour: the alias dict
in `excel_parser` already handles both English and Vietnamese headers,
plus the `combined_options` synthetic column.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from app.services.excel_parser import MAX_COLUMNS, stream_rows
from app.services.parsers.base import ParsedQuestion

NAME = "xlsx"
PRIORITY = 80

# `.xlsx` files are zip archives — first 4 bytes are the local file header.
_ZIP_MAGIC = b"PK\x03\x04"


class XlsxAdapter:
    name = NAME
    priority = PRIORITY

    def detect(self, *, filename: str, head_bytes: bytes) -> bool:
        if not filename.lower().endswith(".xlsx"):
            return False
        return head_bytes.startswith(_ZIP_MAGIC)

    def parse(
        self,
        *,
        file_path: Path,
        column_mapping: dict[str, str | None] | None = None,
    ) -> Iterator[ParsedQuestion]:
        # The existing stream_rows requires a column_mapping; the wizard
        # already collects it via the mapping page, so just forward.
        if column_mapping is None:
            return
        for parsed in stream_rows(
            file_path,
            column_mapping=column_mapping,
            max_rows=MAX_COLUMNS * 200,  # safety cap, matches Phase 05 ceiling
        ):
            row = dict(parsed.raw)
            row.setdefault("source_format", self.name)
            row.setdefault("source_url", str(file_path))
            row.setdefault("source_page", parsed.row_number)
            yield row
