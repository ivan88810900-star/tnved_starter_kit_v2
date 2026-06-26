"""create hs_duty_rules and unique index for tnved_commodities.code

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-04-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_index(table: str, idx_name: str) -> bool:
    if not _has_table(table):
        return False
    indexes = inspect(op.get_bind()).get_indexes(table)
    return any(i.get("name") == idx_name for i in indexes)


def upgrade() -> None:
    if not _has_table("tnved_commodities"):
        return

    # Для FK на commodity_code нужна уникальность кодов товаров.
    if not _has_index("tnved_commodities", "uq_tnved_commodities_code"):
        op.create_index(
            "uq_tnved_commodities_code",
            "tnved_commodities",
            ["code"],
            unique=True,
        )

    if not _has_table("hs_duty_rules"):
        op.create_table(
            "hs_duty_rules",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("commodity_code", sa.String(length=32), nullable=False),
            sa.Column("type", sa.String(length=32), nullable=False, server_default="ad_valorem"),
            sa.Column("ad_valorem_pct", sa.Float(), nullable=True),
            sa.Column("specific_amount", sa.Float(), nullable=True),
            sa.Column("specific_currency", sa.String(length=8), nullable=False, server_default=""),
            sa.Column("specific_uom", sa.String(length=16), nullable=False, server_default=""),
            sa.ForeignKeyConstraint(
                ["commodity_code"],
                ["tnved_commodities.code"],
                ondelete="CASCADE",
                name="fk_hs_duty_rules_commodity_code",
            ),
            sa.UniqueConstraint("commodity_code", name="uq_hs_duty_rules_commodity_code"),
        )
        op.create_index("ix_hs_duty_rules_commodity_code", "hs_duty_rules", ["commodity_code"])


def downgrade() -> None:
    if _has_table("hs_duty_rules"):
        if _has_index("hs_duty_rules", "ix_hs_duty_rules_commodity_code"):
            op.drop_index("ix_hs_duty_rules_commodity_code", table_name="hs_duty_rules")
        op.drop_table("hs_duty_rules")

    if _has_table("tnved_commodities") and _has_index("tnved_commodities", "uq_tnved_commodities_code"):
        op.drop_index("uq_tnved_commodities_code", table_name="tnved_commodities")
