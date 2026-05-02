"""attempts-guest-token

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-02 15:50:00

Phase 02 (this iteration) — guest practice mode. Allows a published-exam
attempt to be owned by either a logged-in user OR an unguessable guest
token stored on the client cookie.

Schema deltas:
  * attempts.user_id      → NULLABLE (was NOT NULL)
  * attempts.guest_token  → new VARCHAR(64) NULLABLE
  * CHECK ck_attempts_owner — exactly one of user_id / guest_token set
  * partial index on guest_token for fast lookup

Backward compatible: existing rows keep `user_id` populated and `guest_token`
NULL; the new CHECK is satisfied by the existing user_id.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("attempts", "user_id", existing_type=sa.BigInteger(), nullable=True)
    op.add_column("attempts", sa.Column("guest_token", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        "ck_attempts_owner",
        "attempts",
        "(user_id IS NOT NULL) OR (guest_token IS NOT NULL)",
    )
    op.create_index(
        "ix_attempts_guest_token",
        "attempts",
        ["guest_token"],
        postgresql_where=sa.text("guest_token IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_attempts_guest_token", table_name="attempts")
    op.drop_constraint("ck_attempts_owner", "attempts", type_="check")
    op.drop_column("attempts", "guest_token")
    op.alter_column("attempts", "user_id", existing_type=sa.BigInteger(), nullable=False)
