"""initial-schema

Revision ID: c3961a3f2aa0
Revises:
Create Date: 2026-04-29 08:36:35

Hand-edited from `alembic revision --autogenerate` output to:
  1. Resolve the circular FK between `questions` and `question_duplicate_groups`
     (defer `question_duplicate_groups.canonical_question_id` FK to ALTER).
  2. Create shared ENUM types (`visibility`, `source_type`, `trust_level`) once
     up-front; columns reference them with `create_type=False`.
  3. Drop ALL Postgres ENUM types in `downgrade()` so round-trip
     `downgrade base` → `upgrade head` works on a clean DB.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3961a3f2aa0"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Every Postgres ENUM type this migration introduces. Listed once for easy
# DROP TYPE in downgrade.
_ENUM_TYPE_NAMES: tuple[str, ...] = (
    "user_role",
    "visibility",
    "exam_publish_status",
    "import_publish_status",
    "question_type",
    "question_difficulty",
    "question_status",
    "confidence_level",
    "stale_status",
    "import_status",
    "import_item_status",
    "attempt_mode",
    "report_reason",
    "report_status",
    "actor_type",
    "source_type",
    "trust_level",
    "fetch_status",
    "ai_verification_status",
    "evidence_fetcher",
    "explanation_status",
    "detection_method",
    "glossary_status",
)


# Enum value tuples — kept in module scope so we can both pre-create the shared
# types up-front AND reference them with `create_type=False` in columns.
_VISIBILITY_VALUES = ("private", "public")
_SOURCE_TYPE_VALUES = (
    "official_vendor",
    "rfc_standard",
    "official_forum",
    "community",
    "blog",
    "docs_other",
    "dump_site_blocked",
)
_TRUST_LEVEL_VALUES = ("high", "medium", "low", "excluded")


def _enum_visibility(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_VISIBILITY_VALUES, name="visibility", create_type=create_type
    )


def _enum_source_type(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_SOURCE_TYPE_VALUES, name="source_type", create_type=create_type
    )


def _enum_trust_level(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_TRUST_LEVEL_VALUES, name="trust_level", create_type=create_type
    )


def upgrade() -> None:
    bind = op.get_bind()

    # --- shared ENUM types: create once, reuse in many CREATE TABLE statements
    _enum_visibility(create_type=True).create(bind, checkfirst=False)
    _enum_source_type(create_type=True).create(bind, checkfirst=False)
    _enum_trust_level(create_type=True).create(bind, checkfirst=False)

    # ------------------------------------------------------------------
    # Tables — order respects FK dependencies. The cycle between
    # `questions` and `question_duplicate_groups` is broken by deferring
    # `question_duplicate_groups.canonical_question_id` FK to an ALTER.
    # ------------------------------------------------------------------

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "instructor", "student", "system", name="user_role"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )

    op.create_table(
        "providers",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "product_versions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("provider_id", sa.BigInteger(), nullable=False),
        sa.Column("product_name", sa.String(length=128), nullable=False),
        sa.Column("product_version", sa.String(length=64), nullable=False),
        sa.Column("documentation_base_url", sa.String(length=1024), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "courses",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("provider_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("level", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "exams",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("course_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("exam_version", sa.Integer(), nullable=False),
        sa.Column("vendor_exam_code", sa.String(length=64), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=True),
        sa.Column("passing_score_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("visibility", _enum_visibility(), nullable=False),
        sa.Column(
            "publish_status",
            sa.Enum("draft", "published", "archived", name="exam_publish_status"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "topics",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("exam_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("weight", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "imports",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "uploaded",
                "parsed",
                "needs_mapping",
                "normalized",
                "ai_processing",
                "partially_verified",
                "ready_to_publish",
                "published",
                "failed",
                name="import_status",
            ),
            nullable=False,
        ),
        sa.Column("visibility", _enum_visibility(), nullable=False),
        sa.Column(
            "publish_status",
            sa.Enum("draft", "published", name="import_publish_status"),
            nullable=False,
        ),
        sa.Column("total_questions", sa.Integer(), nullable=True),
        sa.Column("parsed_questions", sa.Integer(), nullable=True),
        sa.Column("failed_questions", sa.Integer(), nullable=True),
        sa.Column("duplicates_detected", sa.Integer(), nullable=False),
        sa.Column("verification_budget_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("verification_spent_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("import_source_claim", sa.Text(), nullable=True),
        sa.Column("error_log", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    # `question_duplicate_groups` is created WITHOUT the FK to questions.id;
    # the FK is added later via ALTER once `questions` exists.
    op.create_table(
        "question_duplicate_groups",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_question_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "detection_method",
            sa.Enum("hash", "embedding", "manual", name="detection_method"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "questions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("exam_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_id", sa.BigInteger(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "question_type",
            sa.Enum("single", "multiple", "true_false", name="question_type"),
            nullable=False,
        ),
        sa.Column(
            "difficulty",
            sa.Enum("easy", "medium", "hard", name="question_difficulty"),
            nullable=True,
        ),
        sa.Column("question_version", sa.Integer(), nullable=False),
        sa.Column("product_version_id", sa.BigInteger(), nullable=True),
        sa.Column("source_version", sa.String(length=64), nullable=True),
        sa.Column("verified_against_version", sa.String(length=64), nullable=True),
        sa.Column("superseded_by_question_id", sa.BigInteger(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("duplicate_group_id", sa.BigInteger(), nullable=True),
        sa.Column("canonical_question_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "imported",
                "parsed",
                "normalized",
                "pending_ai_verification",
                "needs_review",
                "verified_high",
                "verified_medium",
                "verified_low",
                "answer_conflict",
                "missing_reference",
                "published",
                "reported",
                "reverify_required",
                "retired",
                "flagged",
                name="question_status",
            ),
            nullable=False,
        ),
        sa.Column("source_import_id", sa.BigInteger(), nullable=True),
        sa.Column("given_answer", sa.String(length=20), nullable=True),
        sa.Column("ai_verified_answer", sa.String(length=20), nullable=True),
        sa.Column("confidence_score", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "confidence_level",
            sa.Enum("high", "medium", "low", "unknown", name="confidence_level"),
            nullable=True,
        ),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False),
        sa.Column("review_reason", sa.String(length=64), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_verification_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_ttl_days", sa.Integer(), nullable=False),
        sa.Column(
            "stale_status",
            sa.Enum("fresh", "stale", "reverify_required", name="stale_status"),
            nullable=False,
        ),
        sa.Column("source_locator", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["product_version_id"], ["product_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_question_id"], ["questions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_group_id"], ["question_duplicate_groups.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["canonical_question_id"], ["questions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["source_import_id"], ["imports.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_questions_exam_status_deleted",
        "questions",
        ["exam_id", "status", "deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_questions_review_queue",
        "questions",
        ["needs_human_review", "confidence_level"],
        unique=False,
    )
    op.create_index(
        "ix_questions_content_hash",
        "questions",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        "ix_questions_due_partial",
        "questions",
        ["next_verification_due_at"],
        unique=False,
        postgresql_where=sa.text("stale_status <> 'fresh'"),
    )

    # Now that `questions` exists, add the deferred FK on
    # `question_duplicate_groups.canonical_question_id`.
    op.create_foreign_key(
        "fk_question_duplicate_groups_canonical_question_id",
        "question_duplicate_groups",
        "questions",
        ["canonical_question_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "question_options",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.CHAR(length=1), nullable=True),
        sa.Column("option_text", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("ai_is_correct", sa.Boolean(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "question_explanations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("correct_explanation", sa.Text(), nullable=True),
        sa.Column("overall_explanation", sa.Text(), nullable=True),
        sa.Column("ai_model", sa.String(length=64), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "ai_generated",
                "approved",
                "superseded",
                "retired",
                name="explanation_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "source_domains",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("source_type", _enum_source_type(), nullable=False),
        sa.Column("trust_level", _enum_trust_level(), nullable=False),
        sa.Column("allowed_for_verification", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain"),
    )

    op.create_table(
        "question_references",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("source_domain_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("source_type", _enum_source_type(), nullable=True),
        sa.Column("trust_level", _enum_trust_level(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cached_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetch_status",
            sa.Enum(
                "ok", "404", "blocked", "timeout", "content_changed", name="fetch_status"
            ),
            nullable=True,
        ),
        sa.Column("trust_policy_version", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_domain_id"], ["source_domains.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_references_source_status",
        "question_references",
        ["source_domain_id", "fetch_status"],
        unique=False,
    )

    op.create_table(
        "evidence_fetch_logs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("http_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "fetcher",
            sa.Enum("worker", "manual", name="evidence_fetcher"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ai_verification_jobs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "retrying",
                name="ai_verification_status",
            ),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "import_items",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("import_id", sa.BigInteger(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("sheet_name", sa.String(length=64), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "normalized_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "status",
            sa.Enum(
                "parsed",
                "ok",
                "duplicate",
                "warning",
                "error",
                "skipped",
                "imported",
                name="import_item_status",
            ),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("warning_message", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("question_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["import_id"], ["imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "import_id", "row_number", "sheet_name", name="uq_import_items_row"
        ),
    )
    op.create_index(
        "ix_import_items_import_status",
        "import_items",
        ["import_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_import_items_content_hash",
        "import_items",
        ["content_hash"],
        unique=False,
    )

    op.create_table(
        "attempts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("exam_id", sa.BigInteger(), nullable=False),
        sa.Column("exam_version", sa.Integer(), nullable=False),
        sa.Column(
            "mode",
            sa.Enum(
                "practice", "exam", "review", "weak", "flashcard", name="attempt_mode"
            ),
            nullable=False,
        ),
        sa.Column("score_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("total_questions", sa.Integer(), nullable=True),
        sa.Column("correct_count", sa.Integer(), nullable=True),
        sa.Column("wrong_count", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "attempt_answers",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("question_version", sa.Integer(), nullable=False),
        sa.Column("selected_options", sa.String(length=20), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("time_spent_seconds", sa.Integer(), nullable=True),
        sa.Column("flagged", sa.Boolean(), nullable=False),
        # Phase 02 plan addition: presentation order frozen at attempt start.
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id", "order_index", name="uq_attempt_answers_attempt_order"
        ),
    )
    op.create_index(
        "ix_attempt_answers_question_correct",
        "attempt_answers",
        ["question_id", "is_correct"],
        unique=False,
    )

    op.create_table(
        "question_reports",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "wrong_answer",
                "ambiguous",
                "outdated",
                "typo",
                "other",
                name="report_reason",
            ),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("open", "reviewing", "resolved", "rejected", name="report_status"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "actor_type",
            sa.Enum("user", "ai", "system", name="actor_type"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_logs_entity_recent",
        "audit_logs",
        ["entity_type", "entity_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "glossary_terms",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("term_en", sa.String(length=255), nullable=True),
        sa.Column("term_vi", sa.String(length=255), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("usage_note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("approved", "pending", name="glossary_status"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Drop tables in reverse dependency order.
    op.drop_table("glossary_terms")
    op.drop_index("ix_audit_logs_entity_recent", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("question_reports")
    op.drop_index(
        "ix_attempt_answers_question_correct", table_name="attempt_answers"
    )
    op.drop_table("attempt_answers")
    op.drop_table("attempts")
    op.drop_index("ix_import_items_content_hash", table_name="import_items")
    op.drop_index("ix_import_items_import_status", table_name="import_items")
    op.drop_table("import_items")
    op.drop_table("ai_verification_jobs")
    op.drop_table("evidence_fetch_logs")
    op.drop_index(
        "ix_question_references_source_status", table_name="question_references"
    )
    op.drop_table("question_references")
    op.drop_table("source_domains")
    op.drop_table("question_explanations")
    op.drop_table("question_options")
    # Drop the deferred FK first (back-edge), then `question_duplicate_groups`.
    op.drop_constraint(
        "fk_question_duplicate_groups_canonical_question_id",
        "question_duplicate_groups",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_questions_due_partial",
        table_name="questions",
        postgresql_where=sa.text("stale_status <> 'fresh'"),
    )
    op.drop_index("ix_questions_content_hash", table_name="questions")
    op.drop_index("ix_questions_review_queue", table_name="questions")
    op.drop_index("ix_questions_exam_status_deleted", table_name="questions")
    op.drop_table("questions")
    op.drop_table("question_duplicate_groups")
    op.drop_table("imports")
    op.drop_table("topics")
    op.drop_table("exams")
    op.drop_table("courses")
    op.drop_table("product_versions")
    op.drop_table("providers")
    op.drop_table("users")

    # Drop every Postgres ENUM type. Required so a fresh `upgrade head` after
    # `downgrade base` does not collide with leftover types.
    for type_name in _ENUM_TYPE_NAMES:
        bind.execute(sa.text(f'DROP TYPE IF EXISTS "{type_name}"'))
