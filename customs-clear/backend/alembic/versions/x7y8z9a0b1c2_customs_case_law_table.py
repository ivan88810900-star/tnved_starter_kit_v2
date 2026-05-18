"""Add customs_case_law table for precedent RAG.

Revision ID: x7y8z9a0b1c2
Revises: w2x3y4z5a6b
Create Date: 2026-04-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x7y8z9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "w2x3y4z5a6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customs_case_law",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="court"),
        sa.Column("case_number", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("hs_code_prefix", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("recommended_hs_code", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("keywords", sa.Text(), nullable=False, server_default=""),
        sa.Column("product_scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("legal_basis", sa.Text(), nullable=False, server_default=""),
        sa.Column("opi_applied", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("reasoning_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("decision_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_date", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("embedding_model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "case_number", name="uq_customs_case_law_source_case"),
    )
    op.create_index("ix_customs_case_law_hs_prefix", "customs_case_law", ["hs_code_prefix"], unique=False)
    op.create_index("ix_customs_case_law_recommended_hs", "customs_case_law", ["recommended_hs_code"], unique=False)
    op.create_index("ix_customs_case_law_source_type", "customs_case_law", ["source_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_customs_case_law_source_type", table_name="customs_case_law")
    op.drop_index("ix_customs_case_law_recommended_hs", table_name="customs_case_law")
    op.drop_index("ix_customs_case_law_hs_prefix", table_name="customs_case_law")
    op.drop_table("customs_case_law")
