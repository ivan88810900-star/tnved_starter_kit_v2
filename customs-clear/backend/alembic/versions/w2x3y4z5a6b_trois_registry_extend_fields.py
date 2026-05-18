"""Extend trois_registry with brand, validity and representatives.

Revision ID: w2x3y4z5a6b
Revises: v1w2x3y4z5a6
Create Date: 2026-04-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "w2x3y4z5a6b"
down_revision: Union[str, Sequence[str], None] = "v1w2x3y4z5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "trois_registry",
        sa.Column("brand", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "trois_registry",
        sa.Column("valid_until", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column(
        "trois_registry",
        sa.Column("representatives", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_trois_registry_brand", "trois_registry", ["brand"], unique=False)
    # Backfill for existing rows.
    op.execute("UPDATE trois_registry SET brand = trademark WHERE brand = ''")


def downgrade() -> None:
    op.drop_index("ix_trois_registry_brand", table_name="trois_registry")
    op.drop_column("trois_registry", "representatives")
    op.drop_column("trois_registry", "valid_until")
    op.drop_column("trois_registry", "brand")
