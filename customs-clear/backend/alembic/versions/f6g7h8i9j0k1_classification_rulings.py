"""Add classification_rulings table.

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-06-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6g7h8i9j0k1"
down_revision: Union[str, Sequence[str], None] = "e5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "classification_rulings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ruling_number", sa.String(length=128), nullable=False),
        sa.Column("ruling_date", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("agency", sa.String(length=50), nullable=False, server_default="FTS"),
        sa.Column("goods_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("assigned_hs_code", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_url", sa.String(length=512), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ruling_number", name="uq_classification_rulings_number"),
    )
    op.create_index("ix_classification_rulings_hs", "classification_rulings", ["assigned_hs_code"])


def downgrade() -> None:
    op.drop_index("ix_classification_rulings_hs", table_name="classification_rulings")
    op.drop_table("classification_rulings")
