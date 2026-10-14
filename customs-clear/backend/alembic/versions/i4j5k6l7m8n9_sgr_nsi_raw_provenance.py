"""Preserve immutable NSI-1995 SGR source revisions and normalized provenance.

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-10-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i4j5k6l7m8n9"
down_revision: Union[str, Sequence[str], None] = "h3i4j5k6l7m8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sgr_registry_raw_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sgr_number", sa.String(length=128), nullable=False),
        sa.Column("source_record_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("source_version_id", sa.String(length=128), nullable=True),
        sa.Column("date_time_from", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("date_time_to", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("update_datetime", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("date_time_updated", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sgr_registry_raw_revisions_sgr_number",
        "sgr_registry_raw_revisions",
        ["sgr_number"],
        unique=False,
    )
    op.create_index(
        "ix_sgr_registry_raw_revisions_source_record_id",
        "sgr_registry_raw_revisions",
        ["source_record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sgr_registry_raw_revisions_raw_sha256",
        "sgr_registry_raw_revisions",
        ["raw_sha256"],
        unique=True,
    )

    with op.batch_alter_table("sgr_certificates") as batch:
        batch.add_column(sa.Column("doc_norm", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("doc_usearea", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("source_raw_sha256", sa.String(length=64), nullable=True))
        batch.create_foreign_key(
            "fk_sgr_certificates_source_raw_sha256",
            "sgr_registry_raw_revisions",
            ["source_raw_sha256"],
            ["raw_sha256"],
        )
        batch.create_index("ix_sgr_certificates_source_raw_sha256", ["source_raw_sha256"])


def downgrade() -> None:
    with op.batch_alter_table("sgr_certificates") as batch:
        batch.drop_index("ix_sgr_certificates_source_raw_sha256")
        batch.drop_constraint("fk_sgr_certificates_source_raw_sha256", type_="foreignkey")
        batch.drop_column("source_raw_sha256")
        batch.drop_column("doc_usearea")
        batch.drop_column("doc_norm")

    op.drop_index(
        "ix_sgr_registry_raw_revisions_raw_sha256",
        table_name="sgr_registry_raw_revisions",
    )
    op.drop_index(
        "ix_sgr_registry_raw_revisions_source_record_id",
        table_name="sgr_registry_raw_revisions",
    )
    op.drop_index(
        "ix_sgr_registry_raw_revisions_sgr_number",
        table_name="sgr_registry_raw_revisions",
    )
    op.drop_table("sgr_registry_raw_revisions")
