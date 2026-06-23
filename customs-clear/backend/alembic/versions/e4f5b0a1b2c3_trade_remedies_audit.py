"""Trade remedies audit: drop legacy rows, add needs_verification / is_official (#170).

Revision ID: e4f5b0a1b2c3
Revises: d3e4f5b0a1b2
Create Date: 2026-06-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4f5b0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "d3e4f5b0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REMEDIES_URL = "https://remedies.eaeunion.org/dimd/ru"
_REVISION = "anti-dumping:2026-06-23"
_SOURCE = "EEC_ANTI_DUMPING"

_NEW_MEASURES: tuple[dict[str, object], ...] = (
    {
        "hs_code_prefix": "7607",
        "origin_country": "CN",
        "rate_percent": 20.24,
        "regulatory_act": "Решение Коллегии ЕЭК № 97 от 14.10.2025",
        "product_description": (
            "Алюминиевая фольга (прочие производители; 17,16–20,24% по изготовителю, ЕЭК №97)"
        ),
        "effective_from": "2025-10-14",
        "effective_to": "2030-10-14",
        "needs_verification": False,
    },
    {
        "hs_code_prefix": "3206",
        "origin_country": "CN",
        "rate_percent": 16.25,
        "regulatory_act": "Решение Коллегии ЕЭК № 96 от 14.10.2025",
        "product_description": (
            "Диоксид титана / пигменты TiO2 (до 16,25% по изготовителю, ЕЭК №96)"
        ),
        "effective_from": "2025-11-16",
        "effective_to": "2030-10-14",
        "needs_verification": False,
    },
    {
        "hs_code_prefix": "7607",
        "origin_country": "AZ",
        "rate_percent": 16.18,
        "regulatory_act": "Решение Коллегии ЕЭК № 62 от 25.05.2026 (продление № 115)",
        "product_description": "Алюминиевая лента",
        "effective_from": "2020-09-22",
        "effective_to": "2031-05-24",
        "needs_verification": False,
    },
    {
        "hs_code_prefix": "730640",
        "origin_country": "CN",
        "rate_percent": 17.28,
        "regulatory_act": "Решение Коллегии ЕЭК № 12 от 09.02.2021; продлено № 4 от 20.01.2026",
        "product_description": (
            "Трубы сварные из нержавеющей стали (до 17,28% по изготовителю, ЕЭК №12)"
        ),
        "effective_from": "2021-02-09",
        "effective_to": "2026-11-12",
        "needs_verification": False,
    },
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM special_duties WHERE id IN (1, 2, 4, 5, 6)"))

    with op.batch_alter_table("special_duties") as batch:
        batch.add_column(
            sa.Column("needs_verification", sa.Boolean(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("classification_rulings") as batch:
        batch.add_column(
            sa.Column("is_official", sa.Boolean(), nullable=False, server_default="1")
        )

    conn.execute(
        sa.text(
            """
            UPDATE classification_rulings
            SET is_official = CASE
                WHEN agency IN ('FTS', 'KTS', 'EEC') THEN 1
                ELSE 0
            END
            """
        )
    )

    for row in _NEW_MEASURES:
        exists = conn.execute(
            sa.text(
                """
                SELECT 1 FROM special_duties
                WHERE hs_code_prefix = :hs
                  AND origin_country = :oc
                  AND regulatory_act = :act
                LIMIT 1
                """
            ),
            {
                "hs": row["hs_code_prefix"],
                "oc": row["origin_country"],
                "act": row["regulatory_act"],
            },
        ).fetchone()
        if exists:
            continue
        conn.execute(
            sa.text(
                """
                INSERT INTO special_duties (
                    hs_code_prefix, origin_country, rate_percent, rate_specific,
                    currency_code, regulatory_act, measure_type,
                    manufacturer_exporter, product_description,
                    effective_from, effective_to,
                    source_code, source_revision, source_url,
                    needs_verification
                ) VALUES (
                    :hs_code_prefix, :origin_country, :rate_percent, 0,
                    'USD', :regulatory_act, 'anti_dumping',
                    '', :product_description,
                    :effective_from, :effective_to,
                    :source_code, :source_revision, :source_url,
                    :needs_verification
                )
                """
            ),
            {
                **row,
                "source_code": _SOURCE,
                "source_revision": _REVISION,
                "source_url": _REMEDIES_URL,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    for row in _NEW_MEASURES:
        conn.execute(
            sa.text(
                """
                DELETE FROM special_duties
                WHERE hs_code_prefix = :hs
                  AND origin_country = :oc
                  AND regulatory_act = :act
                """
            ),
            {
                "hs": row["hs_code_prefix"],
                "oc": row["origin_country"],
                "act": row["regulatory_act"],
            },
        )
    with op.batch_alter_table("classification_rulings") as batch:
        batch.drop_column("is_official")
    with op.batch_alter_table("special_duties") as batch:
        batch.drop_column("needs_verification")
