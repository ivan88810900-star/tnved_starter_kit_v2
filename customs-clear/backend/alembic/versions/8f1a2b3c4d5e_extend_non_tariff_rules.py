"""extend non_tariff_rules: tr_ts_edition, exception_note, priority

Revision ID: 8f1a2b3c4d5e
Revises: 2e42161ccd78
Create Date: 2026-03-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "8f1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "2e42161ccd78"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    if not inspect(bind).has_table(table):
        return False
    cols = [c["name"] for c in inspect(bind).get_columns(table)]
    return column in cols


def upgrade() -> None:
    extras = [
        ("tr_ts_edition", sa.String(length=512), ""),
        ("exception_note", sa.Text(), ""),
        ("priority", sa.Integer(), "0"),
    ]
    if not inspect(op.get_bind()).has_table("non_tariff_rules"):
        return
    with op.batch_alter_table("non_tariff_rules", schema=None) as batch_op:
        for col_name, col_type, default in extras:
            if not _column_exists("non_tariff_rules", col_name):
                batch_op.add_column(
                    sa.Column(col_name, col_type, nullable=False, server_default=default),
                )


def downgrade() -> None:
    if not inspect(op.get_bind()).has_table("non_tariff_rules"):
        return
    with op.batch_alter_table("non_tariff_rules", schema=None) as batch_op:
        for col_name in ("priority", "exception_note", "tr_ts_edition"):
            if _column_exists("non_tariff_rules", col_name):
                batch_op.drop_column(col_name)
