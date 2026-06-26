"""Remove fictitious ETT test HS codes from tnved_entries and hs_rates (#159).

Revision ID: d3e4f5b0a1b2
Revises: c2d3e4f5b0a1
Create Date: 2026-06-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5b0a1b2"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5b0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEST_HS = ("7777770000", "7777770001", "8888880000", "9999990000")


def upgrade() -> None:
    conn = op.get_bind()
    for code in _TEST_HS:
        conn.execute(sa.text("DELETE FROM hs_rates WHERE hs_code = :c"), {"c": code})
        conn.execute(sa.text("DELETE FROM tnved_entries WHERE hs_code = :c"), {"c": code})


def downgrade() -> None:
    pass
