"""seed-baseline-data

Revision ID: 8f2d3a4b5c6e
Revises: c3961a3f2aa0
Create Date: 2026-04-29 08:40:00

Seeds the minimum data Phase 1 needs so subsequent phases have a working
catalog and a few canonical source domains:
  - 1 provider: Fortinet
  - 1 product_version: FortiOS 7.4
  - 1 course + 1 exam stub: NSE4
  - ~5 source_domains (full trust list deferred to Phase 2)

Idempotent via `ON CONFLICT DO NOTHING` on slug / domain unique constraints.
For tables without a natural unique key (`product_versions`), an explicit
NOT EXISTS guard on (provider_id, product_name, product_version) is used.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f2d3a4b5c6e"
down_revision: str | None = "c3961a3f2aa0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Provider: Fortinet (slug UNIQUE → ON CONFLICT idempotent).
    bind.execute(
        sa.text(
            """
            INSERT INTO providers (name, slug, description)
            VALUES (:name, :slug, :description)
            ON CONFLICT (slug) DO NOTHING
            """
        ),
        {
            "name": "Fortinet",
            "slug": "fortinet",
            "description": "Network security vendor — firewalls, secure access, NSE certifications.",
        },
    )

    # 2. Product version: FortiOS 7.4 (no UNIQUE on (provider_id,name,version)
    #    in schema, so explicit guard via NOT EXISTS in a CTE).
    bind.execute(
        sa.text(
            """
            WITH p AS (SELECT id FROM providers WHERE slug = 'fortinet')
            INSERT INTO product_versions
                (provider_id, product_name, product_version, documentation_base_url)
            SELECT p.id, 'FortiOS', '7.4',
                   'https://docs.fortinet.com/product/fortigate/7.4'
            FROM p
            WHERE NOT EXISTS (
                SELECT 1 FROM product_versions pv
                WHERE pv.provider_id = (SELECT id FROM p)
                  AND pv.product_name = 'FortiOS'
                  AND pv.product_version = '7.4'
            )
            """
        )
    )

    # 3. Course: NSE4 stub under Fortinet (courses.slug not unique in schema, so
    #    use NOT EXISTS).
    bind.execute(
        sa.text(
            """
            INSERT INTO courses (provider_id, name, slug, description, level, status)
            SELECT p.id,
                   'NSE 4 — Network Security Professional',
                   'fortinet-nse4',
                   'Fortinet NSE 4 certification track (FortiGate Security + Infrastructure).',
                   'professional',
                   'active'
            FROM providers p
            WHERE p.slug = 'fortinet'
              AND NOT EXISTS (SELECT 1 FROM courses WHERE slug = 'fortinet-nse4')
            """
        )
    )

    # 4. Exam stub: NSE4 (exams.slug not unique in schema, so use NOT EXISTS).
    bind.execute(
        sa.text(
            """
            INSERT INTO exams
                (course_id, code, name, slug, description, exam_version,
                 vendor_exam_code, time_limit_seconds, passing_score_percent,
                 visibility, publish_status)
            SELECT c.id,
                   'NSE4',
                   'NSE 4 — FortiGate Security',
                   'fortinet-nse4-fgt-security',
                   'Vendor exam stub for NSE 4. Phase 1 placeholder.',
                   1,
                   'NSE4_FGT-7.4',
                   7200,
                   70.0,
                   CAST('private' AS visibility),
                   CAST('draft' AS exam_publish_status)
            FROM courses c
            WHERE c.slug = 'fortinet-nse4'
              AND NOT EXISTS (SELECT 1 FROM exams WHERE slug = 'fortinet-nse4-fgt-security')
            """
        )
    )

    # 5. Minimal source domains (domain UNIQUE → ON CONFLICT idempotent).
    seed_domains = [
        ("docs.fortinet.com", "official_vendor", "high"),
        ("learn.microsoft.com", "official_vendor", "high"),
        ("docs.aws.amazon.com", "official_vendor", "high"),
        ("kubernetes.io", "official_vendor", "high"),
        ("ietf.org", "rfc_standard", "high"),
    ]
    for domain, source_type, trust_level in seed_domains:
        bind.execute(
            sa.text(
                """
                INSERT INTO source_domains
                    (domain, source_type, trust_level, allowed_for_verification)
                VALUES (:domain,
                        CAST(:source_type AS source_type),
                        CAST(:trust_level AS trust_level),
                        TRUE)
                ON CONFLICT (domain) DO NOTHING
                """
            ),
            {
                "domain": domain,
                "source_type": source_type,
                "trust_level": trust_level,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM source_domains WHERE domain IN ("
            "'docs.fortinet.com','learn.microsoft.com','docs.aws.amazon.com',"
            "'kubernetes.io','ietf.org')"
        )
    )
    bind.execute(
        sa.text("DELETE FROM exams WHERE slug = 'fortinet-nse4-fgt-security'")
    )
    bind.execute(sa.text("DELETE FROM courses WHERE slug = 'fortinet-nse4'"))
    bind.execute(
        sa.text(
            "DELETE FROM product_versions pv USING providers p "
            "WHERE pv.provider_id = p.id AND p.slug = 'fortinet' "
            "AND pv.product_name = 'FortiOS' AND pv.product_version = '7.4'"
        )
    )
    bind.execute(sa.text("DELETE FROM providers WHERE slug = 'fortinet'"))
