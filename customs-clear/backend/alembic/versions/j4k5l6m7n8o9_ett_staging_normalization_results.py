"""No-op compatibility revision for the superseded draft migration.

Revision ID: j4k5l6m7n8o9
Revises: i4j5k6l7m8n9

The first draft placed staging-only DDL in the product Alembic graph. It was
published but never applied. The actual caller-bound staging migration now
lives in scripts/staging_migrations/ett_normalization_results_v1.py.

This revision intentionally performs no DDL so a product Alembic upgrade can
never create or alter the external tariff_ingest schema.
"""

from typing import Sequence, Union


revision: str = "j4k5l6m7n8o9"
down_revision: Union[str, Sequence[str], None] = "i4j5k6l7m8n9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

