"""Таблица preliminary_decisions: предварительные решения по классификации (ifcg.ru).

Revision ID: r3s4t5u6v7w8
Revises: p2q3r4s5t6u7
Create Date: 2026-04-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r3s4t5u6v7w8"
down_revision: Union[str, Sequence[str], None] = "p2q3r4s5t6u7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "preliminary_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hs_code", sa.String(length=10), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="ifcg"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_preliminary_decisions_hs_code"),
        "preliminary_decisions",
        ["hs_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_preliminary_decisions_hs_code"), table_name="preliminary_decisions")
    op.drop_table("preliminary_decisions")
