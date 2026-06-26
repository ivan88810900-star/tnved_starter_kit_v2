"""historical_crawl_checkpoints для автономного краулера нормативки.

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d6
Create Date: 2026-04-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table_exists("historical_crawl_checkpoints"):
        op.create_table(
            "historical_crawl_checkpoints",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("url_hash", sa.String(length=64), nullable=False),
            sa.Column("canonical_url", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("measures_applied", sa.Integer(), nullable=False),
            sa.Column("error_note", sa.Text(), nullable=False),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("historical_crawl_checkpoints", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_historical_crawl_checkpoints_status"),
                ["status"],
                unique=False,
            )
            batch_op.create_index(
                batch_op.f("ix_historical_crawl_checkpoints_url_hash"),
                ["url_hash"],
                unique=True,
            )


def downgrade() -> None:
    if _table_exists("historical_crawl_checkpoints"):
        op.drop_table("historical_crawl_checkpoints")
