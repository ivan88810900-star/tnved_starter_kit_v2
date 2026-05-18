"""Расширить tnved_chapters.code до 16 символов (группы 0101 и т.д.)

Revision ID: f0a1b2c3d4e5
Revises: d1e2f3a4b5c6
Create Date: 2026-04-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("tnved_chapters"):
        return
    with op.batch_alter_table("tnved_chapters") as batch_op:
        batch_op.alter_column(
            "code",
            existing_type=sa.String(length=2),
            type_=sa.String(length=16),
            existing_nullable=False,
        )


def downgrade() -> None:
    if not _has_table("tnved_chapters"):
        return
    with op.batch_alter_table("tnved_chapters") as batch_op:
        batch_op.alter_column(
            "code",
            existing_type=sa.String(length=16),
            type_=sa.String(length=2),
            existing_nullable=False,
        )
