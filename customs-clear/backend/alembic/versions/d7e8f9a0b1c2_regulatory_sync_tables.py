"""regulatory_sync: state, AI extracts, UI log events.

Revision ID: d7e8f9a0b1c2
Revises: 6e714a1a9b05
Create Date: 2026-04-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "6e714a1a9b05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table_exists("regulatory_sync_state"):
        op.create_table(
            "regulatory_sync_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("last_completed_at", sa.DateTime(), nullable=True),
            sa.Column("last_trigger", sa.String(length=32), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=False),
            sa.Column("rows_upserted", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _table_exists("regulatory_ai_extracts"):
        op.create_table(
            "regulatory_ai_extracts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("hs_code_norm", sa.String(length=12), nullable=False),
            sa.Column("measure_type", sa.String(length=32), nullable=False),
            sa.Column("document_name", sa.String(length=512), nullable=False),
            sa.Column("source_excerpt", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "hs_code_norm",
                "document_name",
                "measure_type",
                name="uq_regulatory_ai_extracts_natural",
            ),
        )
        with op.batch_alter_table("regulatory_ai_extracts", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_regulatory_ai_extracts_hs_code_norm"),
                ["hs_code_norm"],
                unique=False,
            )
            batch_op.create_index(
                batch_op.f("ix_regulatory_ai_extracts_measure_type"),
                ["measure_type"],
                unique=False,
            )

    if not _table_exists("regulatory_sync_events"):
        op.create_table(
            "regulatory_sync_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("level", sa.String(length=16), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("regulatory_sync_events", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_regulatory_sync_events_created_at"),
                ["created_at"],
                unique=False,
            )
            batch_op.create_index(
                batch_op.f("ix_regulatory_sync_events_level"),
                ["level"],
                unique=False,
            )


def downgrade() -> None:
    if _table_exists("regulatory_sync_events"):
        op.drop_table("regulatory_sync_events")
    if _table_exists("regulatory_ai_extracts"):
        op.drop_table("regulatory_ai_extracts")
    if _table_exists("regulatory_sync_state"):
        op.drop_table("regulatory_sync_state")
