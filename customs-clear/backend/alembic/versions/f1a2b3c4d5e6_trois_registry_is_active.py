"""trois_registry: is_active flag for expired trademark records.

Revision ID: f1a2b3c4d5e6
Revises: e4f5b0a1b2c3
Create Date: 2026-06-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e4f5b0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "trois_registry",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    # valid_until хранится как YYYY.MM.DD — нормализуем для сравнения с date('now').
    op.execute(
        """
        UPDATE trois_registry
        SET is_active = CASE
          WHEN valid_until IS NULL OR TRIM(valid_until) = '' THEN 1
          WHEN REPLACE(valid_until, '.', '-') >= date('now') THEN 1
          ELSE 0
        END
        """
    )


def downgrade() -> None:
    op.drop_column("trois_registry", "is_active")
