"""Add import_restrictions table.

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-06-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6g7h8i9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6g7h8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_restrictions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hs_prefix", sa.String(length=10), nullable=False),
        sa.Column("restriction_type", sa.String(length=30), nullable=False),
        sa.Column("country_code", sa.String(length=10), nullable=False, server_default="ALL"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("legal_ref", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("effective_from", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("effective_to", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="warning"),
        sa.Column("source_url", sa.String(length=512), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_restrictions_hs", "import_restrictions", ["hs_prefix"])
    op.create_index("ix_import_restrictions_type", "import_restrictions", ["restriction_type"])


def downgrade() -> None:
    op.drop_index("ix_import_restrictions_type", table_name="import_restrictions")
    op.drop_index("ix_import_restrictions_hs", table_name="import_restrictions")
    op.drop_table("import_restrictions")
