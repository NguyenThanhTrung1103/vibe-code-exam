"""pg_trgm + question_text trigram index

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-05-04 23:30:00

Enables the `pg_trgm` extension and creates a partial GIN index on
`questions.question_text` (active rows only) so the import pipeline can
flag near-duplicates without full-text scans.

Reversible: downgrade drops the index and the extension.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: str | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Index built CONCURRENTLY so the migration is a no-op for live traffic on
# the questions table. CONCURRENTLY cannot run inside a transaction, so we
# use Alembic's autocommit_block().
INDEX_NAME = "ix_questions_question_text_trgm"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX_NAME,
            "questions",
            ["question_text"],
            postgresql_using="gin",
            postgresql_ops={"question_text": "gin_trgm_ops"},
            postgresql_concurrently=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX_NAME,
            table_name="questions",
            postgresql_concurrently=True,
            if_exists=True,
        )
    # Only drop the extension if no other index depends on it. Cheaper to
    # leave it installed; this is dev-grade hygiene only.
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
