"""Таблица sgr_certificates (Единый реестр свидетельств о государственной регистрации).

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-04-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "u1v2w3x4y5z6"
down_revision: Union[str, Sequence[str], None] = "t0u1v2w3x4y5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sgr_certificates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sgr_number", sa.String(length=128), nullable=False),
        sa.Column("product_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("manufacturer", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("brand", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("recipient", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("issue_date", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sgr_number", name="uq_sgr_certificates_sgr_number"),
    )
    op.create_index("ix_sgr_certificates_brand", "sgr_certificates", ["brand"], unique=False)
    op.create_index("ix_sgr_certificates_manufacturer", "sgr_certificates", ["manufacturer"], unique=False)
    op.create_index("ix_sgr_certificates_status", "sgr_certificates", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sgr_certificates_status", table_name="sgr_certificates")
    op.drop_index("ix_sgr_certificates_manufacturer", table_name="sgr_certificates")
    op.drop_index("ix_sgr_certificates_brand", table_name="sgr_certificates")
    op.drop_table("sgr_certificates")
