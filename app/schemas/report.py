"""Phase 08 — student question-report form."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

ReasonStr = Literal["wrong_answer", "ambiguous", "outdated", "typo", "other"]


class QuestionReportForm(BaseModel):
    reason: ReasonStr
    comment: Annotated[str | None, Field(default=None, max_length=2000)] = None
