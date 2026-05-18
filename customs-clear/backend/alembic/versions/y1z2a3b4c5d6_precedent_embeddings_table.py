"""Add precedent_embeddings vector index table.

Revision ID: y1z2a3b4c5d6
Revises: x7y8z9a0b1c2
Create Date: 2026-04-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "y1z2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "x7y8z9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "precedent_embeddings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_table", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("hs_code", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("text_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding_model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_table", "source_id", name="uq_precedent_embeddings_source"),
    )
    op.create_index("ix_precedent_embeddings_hs_code", "precedent_embeddings", ["hs_code"], unique=False)
    op.create_index(
        "ix_precedent_embeddings_source_table",
        "precedent_embeddings",
        ["source_table"],
        unique=False,
    )
    op.create_index("ix_precedent_embeddings_source_id", "precedent_embeddings", ["source_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_precedent_embeddings_source_id", table_name="precedent_embeddings")
    op.drop_index("ix_precedent_embeddings_source_table", table_name="precedent_embeddings")
    op.drop_index("ix_precedent_embeddings_hs_code", table_name="precedent_embeddings")
    op.drop_table("precedent_embeddings")
