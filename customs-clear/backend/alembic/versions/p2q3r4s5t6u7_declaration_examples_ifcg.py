"""Таблица declaration_examples: примеры декларирования (ifcg.ru и др.).

Revision ID: p2q3r4s5t6u7
Revises: o1p2q3r4s5t6
Create Date: 2026-04-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p2q3r4s5t6u7"
down_revision: Union[str, Sequence[str], None] = "o1p2q3r4s5t6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "declaration_examples",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hs_code", sa.String(length=10), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="ifcg"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_declaration_examples_hs_code"),
        "declaration_examples",
        ["hs_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_declaration_examples_hs_code"), table_name="declaration_examples")
    op.drop_table("declaration_examples")
