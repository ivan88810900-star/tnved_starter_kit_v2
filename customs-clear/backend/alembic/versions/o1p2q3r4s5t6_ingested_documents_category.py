"""Колонка category у ingested_documents (law.tks.ru краулер).

Revision ID: o1p2q3r4s5t6
Revises: n5o6p7q8r9s0
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "o1p2q3r4s5t6"
down_revision: Union[str, Sequence[str], None] = "n5o6p7q8r9s0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("ingested_documents")}
    if "category" not in cols:
        with op.batch_alter_table("ingested_documents") as batch_op:
            batch_op.add_column(
                sa.Column("category", sa.String(length=512), nullable=False, server_default=""),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("ingested_documents")}
    if "category" in cols:
        with op.batch_alter_table("ingested_documents") as batch_op:
            batch_op.drop_column("category")
