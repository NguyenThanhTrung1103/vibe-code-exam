"""SQLAlchemy ORM models for the exam platform.

Importing this package side-effect-registers every model with `Base.metadata`,
which is what Alembic autogenerate compares against the live database.
"""

from __future__ import annotations

from app.models.ai import AIVerificationJob
from app.models.attempts import Attempt, AttemptAnswer
from app.models.audit import AuditLog
from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.catalog import Course, Exam, ProductVersion, Provider, Topic
from app.models.evidence import EvidenceFetchLog, QuestionReference, SourceDomain
from app.models.glossary import GlossaryTerm
from app.models.imports import Import, ImportItem
from app.models.questions import (
    Question,
    QuestionDuplicateGroup,
    QuestionExplanation,
    QuestionOption,
)
from app.models.reports import QuestionReport
from app.models.users import User

__all__ = [
    "AIVerificationJob",
    "Attempt",
    "AttemptAnswer",
    "AuditLog",
    "Base",
    "Course",
    "EvidenceFetchLog",
    "Exam",
    "GlossaryTerm",
    "Import",
    "ImportItem",
    "ProductVersion",
    "Provider",
    "Question",
    "QuestionDuplicateGroup",
    "QuestionExplanation",
    "QuestionOption",
    "QuestionReference",
    "QuestionReport",
    "SoftDeleteMixin",
    "SourceDomain",
    "TimestampMixin",
    "Topic",
    "User",
]
