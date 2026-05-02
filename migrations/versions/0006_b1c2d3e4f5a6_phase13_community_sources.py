"""phase13-community-sources

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-05-01 10:15:00

Phase 13 — CDEA Sprint-1 schema:

  1. CREATE TYPE for 4 new ENUMs:
     - community_source_name
     - community_fetch_status
     - community_consensus
     - community_confidence  (ORDER MATTERS: unknown < low < medium < high)
  2. CREATE TABLE community_discussion_sources with red-team v2 fixes:
     - FK question_id ON DELETE RESTRICT (red-team #6)
     - total_votes regular INT column (red-team #10, no GENERATED)
     - approved_at_confidence + row_version (red-team #11)
     - fetch_lease_expires_at (red-team #5)
     - UNIQUE (question_id, source_name, source_url)
     - CHECK jsonb_typeof(vote_distribution) = 'object'
     - 6 indexes including 3 partial
  3. ALTER TABLE questions ADD row_version INTEGER NOT NULL DEFAULT 0
     (red-team #11 — optimistic CAS for confidence-recompute race).

Downgrade drops everything cleanly so `downgrade -1 → upgrade head` is a
no-op.

This migration does NOT touch:
  * blogdb / blog role / non-exam DBs
  * `community_fetch_logs` (deferred to Phase 14)
  * `community_option_arguments` (Appendix A / Ollama only)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SOURCE_NAME_VALUES = ("examtopics", "vendor_forum", "reddit", "blog", "other")
_FETCH_STATUS_VALUES = (
    "pending",
    "fetching",
    "ok",
    "blocked",
    "not_found",
    "timeout",
    "parse_error",
    "rate_limited",
)
_CONSENSUS_VALUES = ("agrees_with_given", "disagrees_with_given", "split", "unknown")
# ORDER MATTERS: low → high so DESC gives high first.
_CONFIDENCE_VALUES = ("unknown", "low", "medium", "high")


def _enum_source_name(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_SOURCE_NAME_VALUES, name="community_source_name", create_type=create_type
    )


def _enum_fetch_status(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_FETCH_STATUS_VALUES, name="community_fetch_status", create_type=create_type
    )


def _enum_consensus(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(*_CONSENSUS_VALUES, name="community_consensus", create_type=create_type)


def _enum_confidence(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_CONFIDENCE_VALUES, name="community_confidence", create_type=create_type
    )


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Pre-create the 4 new ENUM types.
    _enum_source_name(create_type=True).create(bind, checkfirst=False)
    _enum_fetch_status(create_type=True).create(bind, checkfirst=False)
    _enum_consensus(create_type=True).create(bind, checkfirst=False)
    _enum_confidence(create_type=True).create(bind, checkfirst=False)

    # 2. CREATE TABLE community_discussion_sources.
    op.create_table(
        "community_discussion_sources",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "source_name",
            _enum_source_name(create_type=False),
            nullable=False,
            server_default=sa.text("'examtopics'"),
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("external_question_id", sa.String(length=255), nullable=True),
        sa.Column("discussion_count", sa.Integer(), nullable=True),
        sa.Column("vote_distribution", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("total_votes", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetch_status",
            _enum_fetch_status(create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("last_fetch_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetch_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("fetch_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("community_answer", sa.String(length=20), nullable=True),
        sa.Column(
            "community_confidence",
            _enum_confidence(create_type=False),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column(
            "community_consensus",
            _enum_consensus(create_type=False),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column(
            "answer_conflict",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("common_arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "approved_for_student",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("approved_at_confidence", _enum_confidence(create_type=False), nullable=True),
        sa.Column("ignored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id",
            "source_name",
            "source_url",
            name="uq_community_sources_question_url",
        ),
        sa.CheckConstraint(
            "vote_distribution IS NULL OR jsonb_typeof(vote_distribution) = 'object'",
            name="ck_vote_distribution_object",
        ),
    )

    # 3. Indexes (3 plain + 3 partial).
    op.create_index("ix_cds_question", "community_discussion_sources", ["question_id"])
    op.create_index("ix_cds_status", "community_discussion_sources", ["fetch_status"])
    op.create_index(
        "ix_cds_external_id", "community_discussion_sources", ["external_question_id"]
    )
    op.create_index(
        "ix_cds_review_queue",
        "community_discussion_sources",
        ["needs_review"],
        postgresql_where=sa.text("needs_review = TRUE"),
    )
    op.create_index(
        "ix_cds_approved",
        "community_discussion_sources",
        ["question_id"],
        postgresql_where=sa.text("approved_for_student = TRUE"),
    )
    op.create_index(
        "ix_cds_lease",
        "community_discussion_sources",
        ["fetch_lease_expires_at"],
        postgresql_where=sa.text("fetch_status IN ('fetching')"),
    )

    # 4. ALTER TABLE questions ADD row_version (red-team #11).
    op.add_column(
        "questions",
        sa.Column(
            "row_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("questions", "row_version")

    op.drop_index("ix_cds_lease", table_name="community_discussion_sources")
    op.drop_index("ix_cds_approved", table_name="community_discussion_sources")
    op.drop_index("ix_cds_review_queue", table_name="community_discussion_sources")
    op.drop_index("ix_cds_external_id", table_name="community_discussion_sources")
    op.drop_index("ix_cds_status", table_name="community_discussion_sources")
    op.drop_index("ix_cds_question", table_name="community_discussion_sources")

    op.drop_table("community_discussion_sources")

    bind = op.get_bind()
    _enum_confidence(create_type=False).drop(bind, checkfirst=False)
    _enum_consensus(create_type=False).drop(bind, checkfirst=False)
    _enum_fetch_status(create_type=False).drop(bind, checkfirst=False)
    _enum_source_name(create_type=False).drop(bind, checkfirst=False)
