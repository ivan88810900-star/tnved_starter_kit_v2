"""Add quality column to non_tariff_measures (ORM noise filter).

Revision ID: q4r5s6t7u8v9
Revises: ntm_v2_001_tr_ts
Create Date: 2026-05-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "q4r5s6t7u8v9"
down_revision: Union[str, Sequence[str], None] = "ntm_v2_001_tr_ts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _column_exists(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table(table):
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if _table_exists("non_tariff_measures") and not _column_exists("non_tariff_measures", "quality"):
        with op.batch_alter_table("non_tariff_measures", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "quality",
                    sa.String(length=16),
                    nullable=False,
                    server_default="normal",
                ),
            )


def downgrade() -> None:
    if _column_exists("non_tariff_measures", "quality"):
        with op.batch_alter_table("non_tariff_measures", schema=None) as batch_op:
            batch_op.drop_column("quality")
