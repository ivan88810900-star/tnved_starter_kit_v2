"""Таблица eco_fee_rates: тарифы экологического сбора (РОП).

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-04-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s4t5u6v7w8x9"
down_revision: Union[str, Sequence[str], None] = "r3s4t5u6v7w8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "eco_fee_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hs_code_prefix", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("material_type", sa.String(length=64), nullable=False),
        sa.Column("rate_rub_per_kg", sa.Float(), nullable=False, server_default="0"),
        sa.Column("normative_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("valid_from_year", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "hs_code_prefix",
            "material_type",
            "valid_from_year",
            name="uq_eco_fee_rates_prefix_material_year",
        ),
    )
    op.create_index(
        op.f("ix_eco_fee_rates_hs_code_prefix"),
        "eco_fee_rates",
        ["hs_code_prefix"],
        unique=False,
    )
    op.create_index(
        op.f("ix_eco_fee_rates_material_type"),
        "eco_fee_rates",
        ["material_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_eco_fee_rates_valid_from_year"),
        "eco_fee_rates",
        ["valid_from_year"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_eco_fee_rates_valid_from_year"), table_name="eco_fee_rates")
    op.drop_index(op.f("ix_eco_fee_rates_material_type"), table_name="eco_fee_rates")
    op.drop_index(op.f("ix_eco_fee_rates_hs_code_prefix"), table_name="eco_fee_rates")
    op.drop_table("eco_fee_rates")
