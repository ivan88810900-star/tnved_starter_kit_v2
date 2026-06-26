"""Seed declaration_documents chapter-specific rows from JSON.

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-06-24
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence, Union

revision: str = "h3i4j5k6l7m8"
down_revision: Union[str, Sequence[str], None] = "g2h3i4j5k6l7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BACKEND = Path(__file__).resolve().parents[2]


def upgrade() -> None:
    sys.path.insert(0, str(_BACKEND))
    from scripts.seed_declaration_documents import seed

    seed()


def downgrade() -> None:
    pass
