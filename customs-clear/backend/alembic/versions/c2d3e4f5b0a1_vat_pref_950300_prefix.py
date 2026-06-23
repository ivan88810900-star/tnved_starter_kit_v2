"""vat_preferences: replace prefix 9503 with 950300 (PP908 «из 9503 00»).

Revision ID: c2d3e4f5b0a1
Revises: b1c2d3e4f5b0
Create Date: 2026-06-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5b0a1"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_950300_ROW = {
    "hs_code_prefix": "950300",
    "vat_rate": 10,
    "decree_info": "ПП РФ № 908 от 31.12.2004 (из 9503 00 — игрушки для детей)",
    "comment": "Игрушки (субпозиция 950300, не вся глава 95)",
}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM vat_preferences WHERE hs_code_prefix = '9503' AND vat_rate = 10")
    )
    existing = conn.execute(
        sa.text(
            """
            SELECT 1 FROM vat_preferences
            WHERE hs_code_prefix = :hs_code_prefix AND vat_rate = :vat_rate
            """
        ),
        {"hs_code_prefix": "950300", "vat_rate": 10},
    ).fetchone()
    if not existing:
        conn.execute(
            sa.text(
                """
                INSERT INTO vat_preferences (hs_code_prefix, vat_rate, decree_info, comment)
                VALUES (:hs_code_prefix, :vat_rate, :decree_info, :comment)
                """
            ),
            _950300_ROW,
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM vat_preferences WHERE hs_code_prefix = '950300' AND vat_rate = 10")
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO vat_preferences (hs_code_prefix, vat_rate, decree_info, comment)
            VALUES ('9503', 10, 'ПП РФ № 908 от 31.12.2004 (товары для детей)', 'Игрушки')
            """
        )
    )
