"""Parser adapter layer (Phase 1 of multi-format import refactor).

Each adapter is a small module under this package that knows how to detect
its file family and convert it into a uniform stream of `ParsedQuestion`
dicts. The detector module picks one adapter per uploaded file; the chosen
adapter feeds `import_service.parse_and_stage` exactly as the legacy
`excel_parser.stream_rows` did, so all downstream code (normalizer,
validator, dedup, community-source upsert) is unchanged.
"""

from app.services.parsers.base import (
    CANONICAL_FIELDS,
    ParsedQuestion,
    ParserAdapter,
)
from app.services.parsers.detector import detect_adapter, list_adapters

__all__ = [
    "CANONICAL_FIELDS",
    "ParsedQuestion",
    "ParserAdapter",
    "detect_adapter",
    "list_adapters",
]
