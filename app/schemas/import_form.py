"""Phase 05 — Pydantic input schemas for the admin import wizard."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from app.services.excel_parser import CANONICAL_FIELDS


class ImportUploadForm(BaseModel):
    """First-step form: target exam + attestation. File handled separately."""

    target_exam_id: int = Field(ge=1)
    attestation: Annotated[str, Field(min_length=4, max_length=2000)]


class ImportMappingForm(BaseModel):
    """User-submitted mapping table — header label -> canonical field-or-empty."""

    column_mapping: dict[str, str | None]

    def cleaned(self) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for header, canonical in self.column_mapping.items():
            v = (canonical or "").strip() or None
            if v is not None and v not in CANONICAL_FIELDS:
                raise ValueError(f"unknown canonical field: {v!r}")
            out[header] = v
        return out
