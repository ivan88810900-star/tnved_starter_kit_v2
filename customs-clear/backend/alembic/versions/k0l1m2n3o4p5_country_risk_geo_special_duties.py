"""CountryRisk + GeoSpecialDuty; удаление country_regulations / increased_duties.

Revision ID: k0l1m2n3o4p5
Revises: j9k0l1m2n3o4
Create Date: 2026-04-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "k0l1m2n3o4p5"
down_revision: Union[str, Sequence[str], None] = "j9k0l1m2n3o4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    for t in ("increased_duties", "country_regulations"):
        if _has_table(t):
            op.drop_table(t)

    if not _has_table("country_risks"):
        op.create_table(
            "country_risks",
            sa.Column("iso_code", sa.String(length=2), nullable=False),
            sa.Column("name_ru", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("is_unfriendly", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("has_preference", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("required_cert", sa.String(length=128), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("iso_code", name="pk_country_risks_iso_code"),
        )

    if not _has_table("geo_special_duties"):
        op.create_table(
            "geo_special_duties",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("hs_code_prefix", sa.String(length=10), nullable=False),
            sa.Column("country_iso", sa.String(length=20), nullable=False, server_default=""),
            sa.Column("duty_rate", sa.Float(), nullable=False),
            sa.Column("document_basis", sa.String(length=512), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("geo_special_duties", schema=None) as batch_op:
            batch_op.create_index("ix_geo_special_duties_hs_code_prefix", ["hs_code_prefix"], unique=False)
            batch_op.create_index("ix_geo_special_duties_country_iso", ["country_iso"], unique=False)


def downgrade() -> None:
    if _has_table("geo_special_duties"):
        op.drop_table("geo_special_duties")
    if _has_table("country_risks"):
        op.drop_table("country_risks")
    # Восстановление country_regulations / increased_duties не выполняется — см. j9k0l1m2n3o4 при откате цепочки.
