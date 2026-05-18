"""bulk_import_jobs + bulk_import_file_checkpoints для массового ИИ-импорта.

Revision ID: e1f2a3b4c5d6
Revises: d7e8f9a0b1c2
Create Date: 2026-04-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table_exists("bulk_import_jobs"):
        op.create_table(
            "bulk_import_jobs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("total_files", sa.Integer(), nullable=False),
            sa.Column("processed_files", sa.Integer(), nullable=False),
            sa.Column("measures_applied", sa.Integer(), nullable=False),
            sa.Column("current_file", sa.String(length=512), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("bulk_import_jobs", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_bulk_import_jobs_created_at"), ["created_at"], unique=False)
            batch_op.create_index(batch_op.f("ix_bulk_import_jobs_status"), ["status"], unique=False)

    if not _table_exists("bulk_import_file_checkpoints"):
        op.create_table(
            "bulk_import_file_checkpoints",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("file_sha256", sa.String(length=64), nullable=False),
            sa.Column("relative_path", sa.String(length=512), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("measures_applied", sa.Integer(), nullable=False),
            sa.Column("error_note", sa.Text(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("bulk_import_file_checkpoints", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_bulk_import_file_checkpoints_file_sha256"),
                ["file_sha256"],
                unique=True,
            )
            batch_op.create_index(
                batch_op.f("ix_bulk_import_file_checkpoints_job_id"),
                ["job_id"],
                unique=False,
            )
            batch_op.create_index(
                batch_op.f("ix_bulk_import_file_checkpoints_status"),
                ["status"],
                unique=False,
            )


def downgrade() -> None:
    if _table_exists("bulk_import_file_checkpoints"):
        op.drop_table("bulk_import_file_checkpoints")
    if _table_exists("bulk_import_jobs"):
        op.drop_table("bulk_import_jobs")
