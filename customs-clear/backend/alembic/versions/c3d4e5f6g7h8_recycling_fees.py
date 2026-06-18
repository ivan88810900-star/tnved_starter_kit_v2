"""Add recycling_fees table.

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-06-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6g7h8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recycling_fees",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hs_prefix", sa.String(length=10), nullable=False),
        sa.Column("vehicle_type", sa.String(length=50), nullable=False),
        sa.Column("is_new", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("base_rate", sa.Float(), nullable=False, server_default="20000.0"),
        sa.Column("coefficient", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("engine_volume_from", sa.Integer(), nullable=True),
        sa.Column("engine_volume_to", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("legal_ref", sa.String(length=255), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hs_prefix", "vehicle_type", "is_new", name="uq_recycling_fees"),
    )
    op.create_index("ix_recycling_fees_hs_prefix", "recycling_fees", ["hs_prefix"])


def downgrade() -> None:
    op.drop_index("ix_recycling_fees_hs_prefix", table_name="recycling_fees")
    op.drop_table("recycling_fees")
