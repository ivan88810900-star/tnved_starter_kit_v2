"""special_duties: countervailing row provenance fields (countervailing_source_*).

Revision ID: v9w0x1y2z3a4
Revises: u8v9w0x1y2z3
Create Date: 2026-06-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v9w0x1y2z3a4"
down_revision: Union[str, Sequence[str], None] = "u8v9w0x1y2z3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("special_duties") as batch:
        batch.add_column(
            sa.Column("countervailing_source_code", sa.String(length=50), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("countervailing_source_revision", sa.String(length=128), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("countervailing_source_url", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("countervailing_synced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("special_duties") as batch:
        batch.drop_column("countervailing_synced_at")
        batch.drop_column("countervailing_source_url")
        batch.drop_column("countervailing_source_revision")
        batch.drop_column("countervailing_source_code")
