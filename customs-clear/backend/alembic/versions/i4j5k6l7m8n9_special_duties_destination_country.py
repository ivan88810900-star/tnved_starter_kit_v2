"""special_duties: national destination scope for EAEU exceptions.

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-10-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "i4j5k6l7m8n9"
down_revision: Union[str, Sequence[str], None] = "h3i4j5k6l7m8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("special_duties") as batch:
        batch.add_column(
            sa.Column("destination_country", sa.String(length=8), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("special_duties") as batch:
        batch.drop_column("destination_country")
