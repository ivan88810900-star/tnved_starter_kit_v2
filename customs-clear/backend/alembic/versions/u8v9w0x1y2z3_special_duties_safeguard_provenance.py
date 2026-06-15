"""special_duties: special-safeguard row provenance fields (safeguard_source_*).

Revision ID: u8v9w0x1y2z3
Revises: t7u8v9w0x1y2
Create Date: 2026-06-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "u8v9w0x1y2z3"
down_revision: Union[str, Sequence[str], None] = "t7u8v9w0x1y2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("special_duties") as batch:
        batch.add_column(sa.Column("safeguard_source_code", sa.String(length=50), nullable=False, server_default=""))
        batch.add_column(
            sa.Column("safeguard_source_revision", sa.String(length=128), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("safeguard_source_url", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("safeguard_synced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("special_duties") as batch:
        batch.drop_column("safeguard_synced_at")
        batch.drop_column("safeguard_source_url")
        batch.drop_column("safeguard_source_revision")
        batch.drop_column("safeguard_source_code")
