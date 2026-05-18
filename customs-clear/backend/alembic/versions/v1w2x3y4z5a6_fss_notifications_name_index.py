"""Индекс по наименованию для ускорения поиска в fss_notifications.

Revision ID: v1w2x3y4z5a6
Revises: u1v2w3x4y5z6
Create Date: 2026-04-18

"""

from typing import Sequence, Union

from alembic import op

revision: str = "v1w2x3y4z5a6"
down_revision: Union[str, Sequence[str], None] = "u1v2w3x4y5z6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_fss_notifications_name", "fss_notifications", ["name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_fss_notifications_name", table_name="fss_notifications")
