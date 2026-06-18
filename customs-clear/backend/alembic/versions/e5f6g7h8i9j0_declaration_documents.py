"""Add declaration_documents table.

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-06-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "declaration_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hs_prefix", sa.String(length=10), nullable=False),
        sa.Column("doc_type", sa.String(length=50), nullable=False),
        sa.Column("doc_name", sa.String(length=512), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("condition", sa.Text(), nullable=False, server_default=""),
        sa.Column("legal_ref", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=50), nullable=False, server_default="general"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_declaration_documents_hs", "declaration_documents", ["hs_prefix"])


def downgrade() -> None:
    op.drop_index("ix_declaration_documents_hs", table_name="declaration_documents")
    op.drop_table("declaration_documents")
