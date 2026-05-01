"""add-users-last-password-at

Revision ID: 4a7e1c2b9d8f
Revises: 8f2d3a4b5c6e
Create Date: 2026-04-29 16:13:00

Phase 03: track when each user last set/typed their password so admin role
re-prompts at 24 hours. NULL = "never," treated as "needs re-prompt" by the
auth layer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a7e1c2b9d8f"
down_revision: str | None = "8f2d3a4b5c6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "last_password_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "last_password_at")
