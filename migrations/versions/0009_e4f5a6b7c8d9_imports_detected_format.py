"""imports-detected-format

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-02 15:51:00

Adds a nullable `detected_format` column to `imports` so the upload pipeline
can record which parser-adapter handled the file (`canonical_xlsx`,
`vn_xlsx`, `examtopics_html`, `qblock_pdf`, `qblock_text`, ...). Surfaced
in the admin import UI and used by enrichment to pick downstream policies.

Backward compatible: existing rows stay `NULL` and continue to render via
file_name as before.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "imports",
        sa.Column("detected_format", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("imports", "detected_format")
