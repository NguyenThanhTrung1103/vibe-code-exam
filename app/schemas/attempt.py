"""Phase 07 — Pydantic schemas for the practice/exam attempt routes."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

ModeStr = Literal["practice", "exam"]


class AttemptStartForm(BaseModel):
    """POST /attempts/start body."""

    exam_id: int = Field(ge=1)
    mode: ModeStr = "practice"


class AnswerSaveForm(BaseModel):
    """POST /attempts/{id}/q/{order}/answer body.

    `selected_options` accepts:
      * a single label ("B"),
      * comma-joined labels ("A,C"),
      * a list (HTMX multi-checkbox).
    Empty / null clears selection.
    """

    selected_options: list[Annotated[str, Field(min_length=1, max_length=1)]] | None = None
