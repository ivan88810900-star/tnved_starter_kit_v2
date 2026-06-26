"""permits_verify_jobs persistent async FSA verify queue

Revision ID: b7c8d9e0f1a2
Revises: 9a0b1c2d3e4f
Create Date: 2026-03-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "9a0b1c2d3e4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    def has_table(name: str) -> bool:
        return inspect(op.get_bind()).has_table(name)

    if not has_table("permits_verify_jobs"):
        op.create_table(
            "permits_verify_jobs",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("summary", sa.JSON(), nullable=True),
            sa.Column("items", sa.JSON(), nullable=True),
            sa.Column("request_payload", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_permits_verify_jobs_status", "permits_verify_jobs", ["status"])
        op.create_index("ix_permits_verify_jobs_created_at", "permits_verify_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_permits_verify_jobs_created_at", table_name="permits_verify_jobs")
    op.drop_index("ix_permits_verify_jobs_status", table_name="permits_verify_jobs")
    op.drop_table("permits_verify_jobs")
