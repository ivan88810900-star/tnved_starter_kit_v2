"""special_duties: anti-dumping measure provenance fields.

Revision ID: s6t7u8v9w0x1
Revises: r5s6t7u8v9w0
Create Date: 2026-06-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s6t7u8v9w0x1"
down_revision: Union[str, Sequence[str], None] = "r5s6t7u8v9w0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("special_duties") as batch:
        batch.add_column(
            sa.Column("measure_type", sa.String(length=32), nullable=False, server_default="anti_dumping")
        )
        batch.add_column(sa.Column("manufacturer_exporter", sa.String(length=512), nullable=False, server_default=""))
        batch.add_column(sa.Column("product_description", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("effective_from", sa.String(length=20), nullable=False, server_default=""))
        batch.add_column(sa.Column("effective_to", sa.String(length=20), nullable=False, server_default=""))
        batch.add_column(sa.Column("source_code", sa.String(length=50), nullable=False, server_default=""))
        batch.add_column(sa.Column("source_revision", sa.String(length=128), nullable=False, server_default=""))
        batch.add_column(sa.Column("source_url", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("synced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("special_duties") as batch:
        batch.drop_column("synced_at")
        batch.drop_column("source_url")
        batch.drop_column("source_revision")
        batch.drop_column("source_code")
        batch.drop_column("effective_to")
        batch.drop_column("effective_from")
        batch.drop_column("product_description")
        batch.drop_column("manufacturer_exporter")
        batch.drop_column("measure_type")
