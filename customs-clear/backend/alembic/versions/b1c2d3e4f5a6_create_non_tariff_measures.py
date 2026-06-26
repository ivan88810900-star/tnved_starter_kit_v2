"""create non_tariff_measures table

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-04-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_index(table: str, idx_name: str) -> bool:
    if not _has_table(table):
        return False
    return any(i.get("name") == idx_name for i in inspect(op.get_bind()).get_indexes(table))


def upgrade() -> None:
    if not _has_table("tnved_commodities"):
        return

    if not _has_table("non_tariff_measures"):
        op.create_table(
            "non_tariff_measures",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("commodity_code", sa.String(length=32), nullable=False),
            sa.Column("measure_type", sa.String(length=32), nullable=False, server_default="certificate"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("document_required", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("regulatory_act", sa.String(length=255), nullable=False, server_default=""),
            sa.ForeignKeyConstraint(
                ["commodity_code"],
                ["tnved_commodities.code"],
                ondelete="CASCADE",
                name="fk_non_tariff_measures_commodity_code",
            ),
        )

    if not _has_index("non_tariff_measures", "ix_non_tariff_measures_commodity_code"):
        op.create_index("ix_non_tariff_measures_commodity_code", "non_tariff_measures", ["commodity_code"])
    if not _has_index("non_tariff_measures", "ix_non_tariff_measures_type"):
        op.create_index("ix_non_tariff_measures_type", "non_tariff_measures", ["measure_type"])


def downgrade() -> None:
    if _has_table("non_tariff_measures"):
        if _has_index("non_tariff_measures", "ix_non_tariff_measures_type"):
            op.drop_index("ix_non_tariff_measures_type", table_name="non_tariff_measures")
        if _has_index("non_tariff_measures", "ix_non_tariff_measures_commodity_code"):
            op.drop_index("ix_non_tariff_measures_commodity_code", table_name="non_tariff_measures")
        op.drop_table("non_tariff_measures")

