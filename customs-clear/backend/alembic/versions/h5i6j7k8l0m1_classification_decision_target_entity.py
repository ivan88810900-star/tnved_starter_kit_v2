"""classification_decisions.target_entity — главный объект для умного поиска.

Revision ID: h5i6j7k8l0m1
Revises: g4h5i6j7k8l9
Create Date: 2026-04-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "h5i6j7k8l0m1"
down_revision: Union[str, Sequence[str], None] = "g4h5i6j7k8l9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _column_exists(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table(table):
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if _table_exists("classification_decisions") and not _column_exists("classification_decisions", "target_entity"):
        with op.batch_alter_table("classification_decisions", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("target_entity", sa.String(length=512), nullable=False, server_default=""),
            )


def downgrade() -> None:
    if _column_exists("classification_decisions", "target_entity"):
        with op.batch_alter_table("classification_decisions", schema=None) as batch_op:
            batch_op.drop_column("target_entity")
