"""Add ROP eco fee rate tables (PP 1041 / PP 2414).

Revision ID: a7b8c9d0e1f2
Revises: merge_heads_001
Create Date: 2026-06-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "merge_heads_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rop_goods_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("category_code", sa.String(length=16), nullable=False),
        sa.Column("pp2414_group", sa.Integer(), nullable=False),
        sa.Column("category_name", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("hs_prefixes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("base_rate_per_ton", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ke_coefficient", sa.Float(), nullable=False, server_default="1"),
        sa.Column("rate_per_ton", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recycling_norm", sa.Float(), nullable=False, server_default="0"),
        sa.Column("calendar_year", sa.Integer(), nullable=False),
        sa.Column("legal_ref", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("needs_verification", sa.Boolean(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pp2414_group", "calendar_year", name="uq_rop_goods_group_year"),
    )
    op.create_index("ix_rop_goods_rates_category_code", "rop_goods_rates", ["category_code"])
    op.create_index("ix_rop_goods_rates_pp2414_group", "rop_goods_rates", ["pp2414_group"])
    op.create_index("ix_rop_goods_rates_calendar_year", "rop_goods_rates", ["calendar_year"])

    op.create_table(
        "rop_packaging_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("category_code", sa.String(length=16), nullable=False),
        sa.Column("pp2414_group", sa.Integer(), nullable=False),
        sa.Column("category_name", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("packaging_type", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("base_rate_per_ton", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ke_coefficient", sa.Float(), nullable=False, server_default="1"),
        sa.Column("rate_per_ton", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recycling_norm", sa.Float(), nullable=False, server_default="0"),
        sa.Column("calendar_year", sa.Integer(), nullable=False),
        sa.Column("legal_ref", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("needs_verification", sa.Boolean(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pp2414_group", "calendar_year", name="uq_rop_packaging_group_year"),
    )
    op.create_index("ix_rop_packaging_rates_category_code", "rop_packaging_rates", ["category_code"])
    op.create_index("ix_rop_packaging_rates_pp2414_group", "rop_packaging_rates", ["pp2414_group"])
    op.create_index("ix_rop_packaging_rates_packaging_type", "rop_packaging_rates", ["packaging_type"])
    op.create_index("ix_rop_packaging_rates_calendar_year", "rop_packaging_rates", ["calendar_year"])

    op.create_table(
        "rop_packaging_defaults",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hs_prefix", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("packaging_type", sa.String(length=32), nullable=False),
        sa.Column("pp2414_group", sa.Integer(), nullable=True),
        sa.Column("is_default_rule", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hs_prefix", name="uq_rop_packaging_defaults_prefix"),
    )
    op.create_index("ix_rop_packaging_defaults_hs_prefix", "rop_packaging_defaults", ["hs_prefix"])
    op.create_index("ix_rop_packaging_defaults_packaging_type", "rop_packaging_defaults", ["packaging_type"])


def downgrade() -> None:
    op.drop_index("ix_rop_packaging_defaults_packaging_type", table_name="rop_packaging_defaults")
    op.drop_index("ix_rop_packaging_defaults_hs_prefix", table_name="rop_packaging_defaults")
    op.drop_table("rop_packaging_defaults")

    op.drop_index("ix_rop_packaging_rates_calendar_year", table_name="rop_packaging_rates")
    op.drop_index("ix_rop_packaging_rates_packaging_type", table_name="rop_packaging_rates")
    op.drop_index("ix_rop_packaging_rates_pp2414_group", table_name="rop_packaging_rates")
    op.drop_index("ix_rop_packaging_rates_category_code", table_name="rop_packaging_rates")
    op.drop_table("rop_packaging_rates")

    op.drop_index("ix_rop_goods_rates_calendar_year", table_name="rop_goods_rates")
    op.drop_index("ix_rop_goods_rates_pp2414_group", table_name="rop_goods_rates")
    op.drop_index("ix_rop_goods_rates_category_code", table_name="rop_goods_rates")
    op.drop_table("rop_goods_rates")
