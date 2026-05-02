"""imports-add-title

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-02 14:55:00

Adds a nullable `title` column to `imports` so admins can give an upload a
human-readable label distinct from the original file name. Empty/null falls
back to `file_name` in the UI (no application logic required for fallback —
the template handles it).

Backward compatible: existing rows keep `title = NULL` and continue to render
via `file_name` as before.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "imports",
        sa.Column("title", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("imports", "title")
