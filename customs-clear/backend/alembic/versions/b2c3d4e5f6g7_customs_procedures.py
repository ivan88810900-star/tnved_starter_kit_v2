"""Add customs_procedures table.

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customs_procedures",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("procedure_code", sa.String(length=10), nullable=False),
        sa.Column("name_ru", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("direction", sa.String(length=10), nullable=False, server_default="import"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("legal_ref", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("duty_applies", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("vat_applies", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("excise_applies", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("customs_fee_applies", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("time_limit_months", sa.Integer(), nullable=True),
        sa.Column("documents_required", sa.Text(), nullable=False, server_default=""),
        sa.Column("conditions", sa.Text(), nullable=False, server_default=""),
        sa.Column("hs_restrictions", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("procedure_code", name="uq_customs_procedures_code"),
    )
    op.create_index("ix_customs_procedures_code", "customs_procedures", ["procedure_code"])


def downgrade() -> None:
    op.drop_index("ix_customs_procedures_code", table_name="customs_procedures")
    op.drop_table("customs_procedures")
