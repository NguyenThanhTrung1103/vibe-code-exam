"""imports-target-mapping-filepath

Revision ID: a1b2c3d4e5f6
Revises: 2c8e9a1b3d4f
Create Date: 2026-04-29 22:30:00

Phase 05 — extends `imports` with the columns the pipeline needs:
  * target_exam_id  — which exam the parsed rows go into
  * column_mapping  — JSONB Excel-header -> canonical-field map
  * file_path       — disk path of the saved upload (outside public dir)

All NULLABLE on add (existing rows in `imports` would otherwise break);
the application enforces non-null at confirm time.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "2c8e9a1b3d4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "imports",
        sa.Column("target_exam_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_imports_target_exam_id",
        "imports",
        "exams",
        ["target_exam_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "imports",
        sa.Column("column_mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "imports",
        sa.Column("file_path", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("imports", "file_path")
    op.drop_column("imports", "column_mapping")
    op.drop_constraint("fk_imports_target_exam_id", "imports", type_="foreignkey")
    op.drop_column("imports", "target_exam_id")
