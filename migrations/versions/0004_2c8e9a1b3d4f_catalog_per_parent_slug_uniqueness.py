"""catalog-per-parent-slug-uniqueness

Revision ID: 2c8e9a1b3d4f
Revises: 4a7e1c2b9d8f
Create Date: 2026-04-29 17:05:00

Phase 04 plan §Key Insights: slug uniqueness scoped to parent, not global.

  * courses.slug          unique per provider
  * exams.slug            unique per course
  * topics.slug           unique per exam
  * product_versions      unique on (provider_id, product_name, product_version)
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2c8e9a1b3d4f"
down_revision: str | None = "4a7e1c2b9d8f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_courses_provider_slug", "courses", ["provider_id", "slug"]
    )
    op.create_unique_constraint(
        "uq_exams_course_slug", "exams", ["course_id", "slug"]
    )
    op.create_unique_constraint(
        "uq_topics_exam_slug", "topics", ["exam_id", "slug"]
    )
    op.create_unique_constraint(
        "uq_product_versions_provider_name_version",
        "product_versions",
        ["provider_id", "product_name", "product_version"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_product_versions_provider_name_version",
        "product_versions",
        type_="unique",
    )
    op.drop_constraint("uq_topics_exam_slug", "topics", type_="unique")
    op.drop_constraint("uq_exams_course_slug", "exams", type_="unique")
    op.drop_constraint("uq_courses_provider_slug", "courses", type_="unique")
