"""ved_intel_jobs: фоновый полный ВЭД-разбор

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-03-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    def has_table(name: str) -> bool:
        return inspect(op.get_bind()).has_table(name)

    if not has_table("ved_intel_jobs"):
        op.create_table(
            "ved_intel_jobs",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("request_payload", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ved_intel_jobs_status", "ved_intel_jobs", ["status"])
        op.create_index("ix_ved_intel_jobs_created_at", "ved_intel_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ved_intel_jobs_created_at", table_name="ved_intel_jobs")
    op.drop_index("ix_ved_intel_jobs_status", table_name="ved_intel_jobs")
    op.drop_table("ved_intel_jobs")
