"""Таблицы fss_notifications и reo_registry (нотификации ФСБ, реестр РЭС).

Revision ID: t0u1v2w3x4y5
Revises: s4t5u6v7w8x9
Create Date: 2026-04-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "t0u1v2w3x4y5"
down_revision: Union[str, Sequence[str], None] = "s4t5u6v7w8x9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fss_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
        sa.Column("brand", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("expiry_date", sa.DateTime(), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number", name="uq_fss_notifications_number"),
    )
    op.create_index("ix_fss_notifications_brand", "fss_notifications", ["brand"], unique=False)
    op.create_index("ix_fss_notifications_status", "fss_notifications", ["status"], unique=False)

    op.create_table(
        "reo_registry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("brand", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("characteristics", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("expiry_date", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number", name="uq_reo_registry_number"),
    )
    op.create_index("ix_reo_registry_brand", "reo_registry", ["brand"], unique=False)
    op.create_index("ix_reo_registry_model_name", "reo_registry", ["model_name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_reo_registry_model_name", table_name="reo_registry")
    op.drop_index("ix_reo_registry_brand", table_name="reo_registry")
    op.drop_table("reo_registry")
    op.drop_index("ix_fss_notifications_status", table_name="fss_notifications")
    op.drop_index("ix_fss_notifications_brand", table_name="fss_notifications")
    op.drop_table("fss_notifications")
