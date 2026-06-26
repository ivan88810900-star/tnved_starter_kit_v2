"""Таблица trois_registry: реестр ТРОИС (Альта-Софт), upsert по reg_number.

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-04-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m3n4o5p6q7r8"
down_revision: Union[str, Sequence[str], None] = "l2m3n4o5p6q7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trois_registry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trademark", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("right_holder", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("reg_number", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=128), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reg_number", name="uq_trois_registry_reg_number"),
    )
    op.create_index("ix_trois_registry_trademark", "trois_registry", ["trademark"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_trois_registry_trademark", table_name="trois_registry")
    op.drop_table("trois_registry")
