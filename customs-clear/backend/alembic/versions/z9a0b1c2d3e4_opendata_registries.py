"""Opendata registries: fsa_certificates, opendata_sync_log, customs_doc_masks.

Revision ID: z9a0b1c2d3e4
Revises: a7b8c9d0e1f2
Create Date: 2026-06-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z9a0b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "opendata_sync_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_key", sa.String(length=32), nullable=False),
        sa.Column("dataset_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("snapshot_id", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("file_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("file_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("synced_at", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("data_as_of", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_opendata_sync_log_source_key", "opendata_sync_log", ["source_key"], unique=False)
    op.create_index(
        "ix_opendata_sync_log_snapshot", "opendata_sync_log", ["source_key", "snapshot_id"], unique=False
    )

    op.create_table(
        "fsa_certificates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("registry_number", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("doc_type", sa.String(length=8), nullable=False, server_default="СС"),
        sa.Column("status", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("applicant", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("manufacturer", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("product_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("tn_ved_codes", sa.Text(), nullable=False, server_default=""),
        sa.Column("tr_ts", sa.Text(), nullable=False, server_default=""),
        sa.Column("issue_date", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("expiry_date", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("fsa_record_id", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("source_snapshot", sa.String(length=256), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registry_number", name="uq_fsa_certificates_registry_number"),
    )
    op.create_index("ix_fsa_certificates_doc_type", "fsa_certificates", ["doc_type"], unique=False)
    op.create_index("ix_fsa_certificates_status", "fsa_certificates", ["status"], unique=False)

    op.create_table(
        "customs_doc_masks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sid_smev", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("kod", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("mask_number", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
        sa.Column("mask_pattern", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("valid_from", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("valid_to", sa.String(length=32), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customs_doc_masks_kod", "customs_doc_masks", ["kod"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_customs_doc_masks_kod", table_name="customs_doc_masks")
    op.drop_table("customs_doc_masks")
    op.drop_index("ix_fsa_certificates_status", table_name="fsa_certificates")
    op.drop_index("ix_fsa_certificates_doc_type", table_name="fsa_certificates")
    op.drop_table("fsa_certificates")
    op.drop_index("ix_opendata_sync_log_snapshot", table_name="opendata_sync_log")
    op.drop_index("ix_opendata_sync_log_source_key", table_name="opendata_sync_log")
    op.drop_table("opendata_sync_log")
