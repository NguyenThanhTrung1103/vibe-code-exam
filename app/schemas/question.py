"""Phase 06 — Pydantic input schemas for the question editor.

Validation rules tighter than the import pipeline because admin-typed
content does not get a normalize-on-import pass.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.models.enums import QuestionDifficulty, QuestionType

QuestionTypeStr = Literal["single", "multiple", "true_false"]
DifficultyStr = Literal["easy", "medium", "hard"]


class OptionIn(BaseModel):
    label: Annotated[str, Field(min_length=1, max_length=1)]
    text: Annotated[str, Field(min_length=1, max_length=1000)]


class QuestionCreate(BaseModel):
    exam_id: int = Field(ge=1)
    question_text: Annotated[str, Field(min_length=1, max_length=4000)]
    question_type: QuestionTypeStr = "single"
    difficulty: DifficultyStr | None = None
    topic_id: int | None = Field(default=None, ge=1)
    options: list[OptionIn] = Field(min_length=2, max_length=5)
    correct_answer: list[Annotated[str, Field(min_length=1, max_length=1)]] = Field(
        min_length=1, max_length=5
    )
    overall_explanation: Annotated[str | None, Field(default=None, max_length=4000)] = None

    def to_service_kwargs(self) -> dict:
        return {
            "exam_id": self.exam_id,
            "question_text": self.question_text,
            "question_type": QuestionType(self.question_type),
            "difficulty": (QuestionDifficulty(self.difficulty) if self.difficulty else None),
            "topic_id": self.topic_id,
            "options": [(o.label.upper(), o.text) for o in self.options],
            "correct_answer": [c.upper() for c in self.correct_answer],
            "overall_explanation": self.overall_explanation,
        }


class QuestionUpdate(BaseModel):
    question_text: Annotated[str | None, Field(default=None, max_length=4000)] = None
    question_type: QuestionTypeStr | None = None
    difficulty: DifficultyStr | None = None
    topic_id: int | None = Field(default=None, ge=0)  # 0 → clear
    status: (
        Literal[
            "imported",
            "needs_review",
            "verified_high",
            "verified_medium",
            "verified_low",
            "published",
            "retired",
            "flagged",
        ]
        | None
    ) = None


class OptionsReplace(BaseModel):
    options: list[OptionIn] = Field(min_length=2, max_length=5)
    correct_answer: list[Annotated[str, Field(min_length=1, max_length=1)]] = Field(
        min_length=1, max_length=5
    )


class ExplanationIn(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=4000)]


class RetireIn(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=500)]
