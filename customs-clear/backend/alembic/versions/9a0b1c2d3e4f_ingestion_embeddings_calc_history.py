"""ingested documents, parsed lines, tnved embeddings, calculation history

Revision ID: 9a0b1c2d3e4f
Revises: 8f1a2b3c4d5e
Create Date: 2026-03-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "9a0b1c2d3e4f"
down_revision: Union[str, Sequence[str], None] = "8f1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    def has_table(name: str) -> bool:
        return inspect(op.get_bind()).has_table(name)

    if not has_table("ingested_documents"):
        op.create_table(
            "ingested_documents",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("original_filename", sa.String(length=512), nullable=False),
            sa.Column("mime_type", sa.String(length=128), nullable=False),
            sa.Column("storage_uri", sa.Text(), nullable=False),
            sa.Column("file_sha256", sa.String(length=64), nullable=False),
            sa.Column("detected_lang", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=False),
            sa.Column("raw_text", sa.Text(), nullable=False),
            sa.Column("structured_payload", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_ingested_documents_file_sha256"), "ingested_documents", ["file_sha256"], unique=False)
        op.create_index(op.f("ix_ingested_documents_status"), "ingested_documents", ["status"], unique=False)

    if not has_table("parsed_invoice_lines"):
        op.create_table(
            "parsed_invoice_lines",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("line_no", sa.Integer(), nullable=False),
            sa.Column("description_original", sa.Text(), nullable=False),
            sa.Column("description_ru", sa.Text(), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=False),
            sa.Column("unit", sa.String(length=32), nullable=False),
            sa.Column("unit_price", sa.Float(), nullable=False),
            sa.Column("line_total", sa.Float(), nullable=False),
            sa.Column("weight_net_kg", sa.Float(), nullable=False),
            sa.Column("weight_gross_kg", sa.Float(), nullable=False),
            sa.Column("packages_count", sa.Float(), nullable=False),
            sa.Column("attributes", sa.JSON(), nullable=True),
            sa.Column("suggested_hs_code", sa.String(length=12), nullable=False),
            sa.Column("hs_confidence", sa.Float(), nullable=True),
            sa.Column("hs_rag_snippet_ids", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(["document_id"], ["ingested_documents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_parsed_invoice_lines_document_id"), "parsed_invoice_lines", ["document_id"], unique=False)
        op.create_index(op.f("ix_parsed_invoice_lines_suggested_hs_code"), "parsed_invoice_lines", ["suggested_hs_code"], unique=False)
        op.create_index("ix_pil_document_line", "parsed_invoice_lines", ["document_id", "line_no"], unique=False)

    if not has_table("tnved_entry_embeddings"):
        op.create_table(
            "tnved_entry_embeddings",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tnved_entry_id", sa.Integer(), nullable=False),
            sa.Column("embedding_model", sa.String(length=128), nullable=False),
            sa.Column("embedding_dim", sa.Integer(), nullable=False),
            sa.Column("embedding", sa.JSON(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tnved_entry_id"], ["tnved_entries.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_tnved_entry_embeddings_tnved_entry_id"), "tnved_entry_embeddings", ["tnved_entry_id"], unique=True)

    if not has_table("customs_calculation_history"):
        op.create_table(
            "customs_calculation_history",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=True),
            sa.Column("user_ref", sa.String(length=128), nullable=False),
            sa.Column("input_payload", sa.JSON(), nullable=False),
            sa.Column("output_payload", sa.JSON(), nullable=False),
            sa.Column("currency", sa.String(length=8), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["ingested_documents.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_customs_calculation_history_created_at"), "customs_calculation_history", ["created_at"], unique=False)
        op.create_index(op.f("ix_customs_calculation_history_document_id"), "customs_calculation_history", ["document_id"], unique=False)
        op.create_index(op.f("ix_customs_calculation_history_user_ref"), "customs_calculation_history", ["user_ref"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    for t in (
        "customs_calculation_history",
        "tnved_entry_embeddings",
        "parsed_invoice_lines",
        "ingested_documents",
    ):
        if insp.has_table(t):
            op.drop_table(t)
