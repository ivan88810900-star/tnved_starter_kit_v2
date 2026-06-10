"""hs_rates: VAT-specific row provenance fields (vat_source_*).

Revision ID: r5s6t7u8v9w0
Revises: q4r5s6t7u8v9
Create Date: 2026-06-09

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r5s6t7u8v9w0"
down_revision: Union[str, Sequence[str], None] = "q4r5s6t7u8v9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("hs_rates") as batch:
        batch.add_column(sa.Column("vat_source_code", sa.String(length=50), nullable=False, server_default=""))
        batch.add_column(sa.Column("vat_source_revision", sa.String(length=128), nullable=False, server_default=""))
        batch.add_column(sa.Column("vat_source_url", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("vat_synced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hs_rates") as batch:
        batch.drop_column("vat_synced_at")
        batch.drop_column("vat_source_url")
        batch.drop_column("vat_source_revision")
        batch.drop_column("vat_source_code")
