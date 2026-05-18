"""Таблица classification_decisions (предварительные решения ФТС / TKS).

Revision ID: g4h5i6j7k8l9
Revises: f3a4b5c6d7e8
Create Date: 2026-04-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "g4h5i6j7k8l9"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table_exists("classification_decisions"):
        op.create_table(
            "classification_decisions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("hs_code", sa.String(length=10), nullable=False, server_default=""),
            sa.Column("product_name", sa.Text(), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("decision_number", sa.String(length=128), nullable=False),
            sa.Column("issue_date", sa.String(length=32), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("decision_number", name="uq_classification_decisions_decision_number"),
        )
        with op.batch_alter_table("classification_decisions", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_classification_decisions_hs_code"),
                ["hs_code"],
                unique=False,
            )


def downgrade() -> None:
    if _table_exists("classification_decisions"):
        op.drop_table("classification_decisions")
