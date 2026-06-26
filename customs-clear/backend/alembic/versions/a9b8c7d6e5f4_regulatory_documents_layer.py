"""regulatory_documents: ведомственные приказы/письма и привязка к HS.

Revision ID: a9b8c7d6e5f4
Revises: z3a4b5c6d7e8
Create Date: 2026-05-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, Sequence[str], None] = "z3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table_exists("regulatory_documents"):
        op.create_table(
            "regulatory_documents",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("agency", sa.String(length=64), nullable=False),
            sa.Column("doc_type", sa.String(length=64), nullable=False),
            sa.Column("doc_number", sa.String(length=256), nullable=True),
            sa.Column("doc_date", sa.Date(), nullable=True),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("source_url", sa.String(length=2048), nullable=False),
            sa.Column("source_html_path", sa.String(length=1024), nullable=True),
            sa.Column("source_pdf_path", sa.String(length=1024), nullable=True),
            sa.Column("language", sa.String(length=16), nullable=True, server_default="ru"),
            sa.Column("status", sa.String(length=32), nullable=True, server_default="active"),
            sa.Column("supersedes_doc_id", sa.String(length=64), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=True),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("topic_tags", sa.JSON(), nullable=True),
            sa.Column("ai_extracted", sa.JSON(), nullable=True),
            sa.Column("quality", sa.String(length=32), nullable=True, server_default="normal"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_url", name="uq_regulatory_documents_source_url"),
        )
        op.create_index(
            "ix_regdoc_agency_date",
            "regulatory_documents",
            ["agency", "doc_date"],
            unique=False,
        )
        op.create_index("ix_regdoc_status", "regulatory_documents", ["status"], unique=False)
        op.create_index("ix_regdoc_doc_type", "regulatory_documents", ["doc_type"], unique=False)

    if not _table_exists("regulatory_doc_hs_mapping"):
        op.create_table(
            "regulatory_doc_hs_mapping",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("doc_id", sa.String(length=64), nullable=False),
            sa.Column("hs_prefix", sa.String(length=16), nullable=False),
            sa.Column("scope", sa.String(length=32), nullable=True, server_default="import"),
            sa.Column("relevance", sa.String(length=32), nullable=True, server_default="direct"),
            sa.Column("confidence", sa.Float(), nullable=True, server_default="1.0"),
            sa.Column("source", sa.String(length=32), nullable=True, server_default="ai"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("approved", sa.Boolean(), nullable=True, server_default=sa.text("0")),
            sa.Column("approved_by", sa.String(length=128), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(
                ["doc_id"],
                ["regulatory_documents.id"],
                name="fk_regulatory_doc_hs_mapping_doc_id",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_regdoc_map_hs_prefix",
            "regulatory_doc_hs_mapping",
            ["hs_prefix"],
            unique=False,
        )
        op.create_index(
            "ix_regdoc_map_doc_id",
            "regulatory_doc_hs_mapping",
            ["doc_id"],
            unique=False,
        )

    if not _table_exists("regulatory_sync_log"):
        op.create_table(
            "regulatory_sync_log",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("agency", sa.String(length=64), nullable=False),
            sa.Column("source_url", sa.String(length=2048), nullable=True),
            sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=64), nullable=True),
            sa.Column("docs_added", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("docs_updated", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("docs_skipped", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    if _table_exists("regulatory_sync_log"):
        op.drop_table("regulatory_sync_log")
    if _table_exists("regulatory_doc_hs_mapping"):
        op.drop_table("regulatory_doc_hs_mapping")
    if _table_exists("regulatory_documents"):
        op.drop_table("regulatory_documents")
