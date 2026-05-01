"""All Postgres native ENUM types — one place, used across models.

Enum class names map to PG type names via `name=` on `sa.Enum(...)`. Migration
will `CREATE TYPE` once per `name` and reuse it.

Including values that are only used in Phase 2/3 today (e.g. AI verification
statuses) avoids future migration churn — the enum types ship in 0001.
"""

from __future__ import annotations

import enum


class UserRole(enum.StrEnum):
    admin = "admin"
    instructor = "instructor"
    student = "student"
    system = "system"


class Visibility(enum.StrEnum):
    """Shared between `exams.visibility` and `imports.visibility`."""

    private = "private"
    public = "public"


class ExamPublishStatus(enum.StrEnum):
    draft = "draft"
    published = "published"
    archived = "archived"


class ImportPublishStatus(enum.StrEnum):
    """Imports can only be `draft` or `published` (no `archived`)."""

    draft = "draft"
    published = "published"


class QuestionType(enum.StrEnum):
    single = "single"
    multiple = "multiple"
    true_false = "true_false"


class QuestionDifficulty(enum.StrEnum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class QuestionStatus(enum.StrEnum):
    imported = "imported"
    parsed = "parsed"
    normalized = "normalized"
    pending_ai_verification = "pending_ai_verification"
    needs_review = "needs_review"
    verified_high = "verified_high"
    verified_medium = "verified_medium"
    verified_low = "verified_low"
    answer_conflict = "answer_conflict"
    missing_reference = "missing_reference"
    published = "published"
    reported = "reported"
    reverify_required = "reverify_required"
    retired = "retired"
    flagged = "flagged"


class ConfidenceLevel(enum.StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class StaleStatus(enum.StrEnum):
    fresh = "fresh"
    stale = "stale"
    reverify_required = "reverify_required"


class ImportStatus(enum.StrEnum):
    uploaded = "uploaded"
    parsed = "parsed"
    needs_mapping = "needs_mapping"
    normalized = "normalized"
    ai_processing = "ai_processing"
    partially_verified = "partially_verified"
    ready_to_publish = "ready_to_publish"
    published = "published"
    failed = "failed"


class ImportItemStatus(enum.StrEnum):
    """Per-row state machine inside an import (Phase 02 plan §3)."""

    parsed = "parsed"
    ok = "ok"
    duplicate = "duplicate"
    warning = "warning"
    error = "error"
    skipped = "skipped"
    imported = "imported"


class AttemptMode(enum.StrEnum):
    practice = "practice"
    exam = "exam"
    review = "review"
    weak = "weak"
    flashcard = "flashcard"


class ReportReason(enum.StrEnum):
    wrong_answer = "wrong_answer"
    ambiguous = "ambiguous"
    outdated = "outdated"
    typo = "typo"
    other = "other"


class ReportStatus(enum.StrEnum):
    open = "open"
    reviewing = "reviewing"
    resolved = "resolved"
    rejected = "rejected"


class ActorType(enum.StrEnum):
    user = "user"
    ai = "ai"
    system = "system"


class SourceType(enum.StrEnum):
    official_vendor = "official_vendor"
    rfc_standard = "rfc_standard"
    official_forum = "official_forum"
    community = "community"
    blog = "blog"
    docs_other = "docs_other"
    dump_site_blocked = "dump_site_blocked"


class TrustLevel(enum.StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    excluded = "excluded"


class FetchStatus(enum.StrEnum):
    ok = "ok"
    not_found = "404"
    blocked = "blocked"
    timeout = "timeout"
    content_changed = "content_changed"


class AIVerificationStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    retrying = "retrying"


class EvidenceFetcher(enum.StrEnum):
    worker = "worker"
    manual = "manual"


class ExplanationStatus(enum.StrEnum):
    draft = "draft"
    ai_generated = "ai_generated"
    approved = "approved"
    superseded = "superseded"
    retired = "retired"


class DetectionMethod(enum.StrEnum):
    hash = "hash"
    embedding = "embedding"
    manual = "manual"


class GlossaryStatus(enum.StrEnum):
    approved = "approved"
    pending = "pending"
