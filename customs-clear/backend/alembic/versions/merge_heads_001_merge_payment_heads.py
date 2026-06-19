"""Merge divergent migration heads into a single linear head.

Revision ID: merge_heads_001
Revises: v9w0x1y2z3a4, f6g7h8i9j0k1, a1b2c3d4e5f7
Create Date: 2026-06-19

История миграций исторически разветвлялась на три головы:
- v9w0x1y2z3a4 — special_duties countervailing provenance (payment-провенанс цепочка)
- f6g7h8i9j0k1 — classification_rulings (ветка customs_procedures)
- a1b2c3d4e5f7 — country_tariff_preferences (ветка sanctions lists)

Эта merge-миграция объединяет их в единый head. Схему не меняет (no-op).
Имя ревизии сохранено как merge_heads_001 для совместимости с уже
застемпленными базами. См. issue #112.
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "merge_heads_001"
down_revision: Union[str, Sequence[str], None] = (
    "v9w0x1y2z3a4",
    "f6g7h8i9j0k1",
    "a1b2c3d4e5f7",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Слияние веток — изменений схемы нет."""
    pass


def downgrade() -> None:
    """Разделение веток — изменений схемы нет."""
    pass
