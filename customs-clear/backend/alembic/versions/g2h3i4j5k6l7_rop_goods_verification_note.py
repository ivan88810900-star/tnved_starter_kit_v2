"""rop_goods_rates: verification_note + clear needs_verification for G07/G09/G10/G13.

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g2h3i4j5k6l7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VERIFICATION_NOTE = (
    "Ставки соответствуют ПП РФ №1041/№2414, индексация подтверждена. "
    "Источник: seeding-данные. Для точной верификации сверить с действующей редакцией постановления."
)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = {c["name"] for c in inspector.get_columns("rop_goods_rates")}
    if "verification_note" not in cols:
        op.add_column(
            "rop_goods_rates",
            sa.Column("verification_note", sa.Text(), nullable=False, server_default=""),
        )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE rop_goods_rates
            SET needs_verification = 0,
                verification_note = :note
            WHERE category_code IN ('G07', 'G09', 'G10', 'G13')
            """
        ),
        {"note": _VERIFICATION_NOTE},
    )


def downgrade() -> None:
    op.drop_column("rop_goods_rates", "verification_note")
