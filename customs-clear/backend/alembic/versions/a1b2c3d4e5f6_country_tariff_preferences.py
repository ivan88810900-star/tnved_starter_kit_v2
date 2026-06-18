"""Add country_tariff_preferences table.

Revision ID: a1b2c3d4e5f6
Revises: z3a4b5c6d7e8
Create Date: 2026-06-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "z3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "country_tariff_preferences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("preference_type", sa.String(length=20), nullable=False),
        sa.Column("duty_coefficient", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("legal_ref", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("effective_from", sa.String(length=20), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("country_code", name="uq_ctp_country_code"),
    )
    op.create_index("ix_ctp_country_code", "country_tariff_preferences", ["country_code"])


def downgrade() -> None:
    op.drop_index("ix_ctp_country_code", table_name="country_tariff_preferences")
    op.drop_table("country_tariff_preferences")
