"""permits_verify_jobs: владелец задания (JWT sub) для изоляции между пользователями.

Revision ID: p9q0r1s2t3u4
Revises: a9b8c7d6e5f4
Create Date: 2026-05-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "p9q0r1s2t3u4"
down_revision: Union[str, Sequence[str], None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = [c["name"] for c in insp.get_columns("permits_verify_jobs")]
    if "created_by_username" not in cols:
        op.add_column(
            "permits_verify_jobs",
            sa.Column("created_by_username", sa.String(length=128), nullable=True),
        )
        op.create_index(
            "ix_permits_verify_jobs_created_by_username",
            "permits_verify_jobs",
            ["created_by_username"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = [c["name"] for c in insp.get_columns("permits_verify_jobs")]
    if "created_by_username" in cols:
        op.drop_index("ix_permits_verify_jobs_created_by_username", table_name="permits_verify_jobs")
        op.drop_column("permits_verify_jobs", "created_by_username")
