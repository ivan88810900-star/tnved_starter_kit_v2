"""Remove incorrect vat_preferences overrides (audit #161).

Revision ID: b1c2d3e4f5b0
Revises: z9a0b1c2d3e4
Create Date: 2026-06-22

Deletes over-broad tamdoc prefixes 27/92/95, fixes 9018 (0% -> 10% per PP688),
adds precise 9503 prefix (PP908 children toys).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5b0"
down_revision: Union[str, Sequence[str], None] = "z9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BAD_PREFIXES = ("27", "92", "95")

_9018_ROW = {
    "hs_code_prefix": "9018",
    "vat_rate": 10,
    "decree_info": "ПП РФ № 688 от 15.09.2008 (медицинские товары)",
    "comment": "Инструменты и аппаратура медицинские",
}

_9503_ROW = {
    "hs_code_prefix": "9503",
    "vat_rate": 10,
    "decree_info": "ПП РФ № 908 от 31.12.2004 (товары для детей)",
    "comment": "Игрушки",
}


def upgrade() -> None:
    conn = op.get_bind()
    for prefix in _BAD_PREFIXES:
        conn.execute(
            sa.text("DELETE FROM vat_preferences WHERE hs_code_prefix = :p"),
            {"p": prefix},
        )
    conn.execute(sa.text("DELETE FROM vat_preferences WHERE hs_code_prefix = '9018'"))
    conn.execute(
        sa.text(
            """
            INSERT INTO vat_preferences (hs_code_prefix, vat_rate, decree_info, comment)
            VALUES (:hs_code_prefix, :vat_rate, :decree_info, :comment)
            """
        ),
        _9018_ROW,
    )
    existing = conn.execute(
        sa.text(
            """
            SELECT 1 FROM vat_preferences
            WHERE hs_code_prefix = :hs_code_prefix AND vat_rate = :vat_rate
              AND decree_info = :decree_info
            """
        ),
        _9503_ROW,
    ).fetchone()
    if not existing:
        conn.execute(
            sa.text(
                """
                INSERT INTO vat_preferences (hs_code_prefix, vat_rate, decree_info, comment)
                VALUES (:hs_code_prefix, :vat_rate, :decree_info, :comment)
                """
            ),
            _9503_ROW,
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM vat_preferences WHERE hs_code_prefix = '9503' AND vat_rate = 10")
    )
    conn.execute(sa.text("DELETE FROM vat_preferences WHERE hs_code_prefix = '9018' AND vat_rate = 10"))
