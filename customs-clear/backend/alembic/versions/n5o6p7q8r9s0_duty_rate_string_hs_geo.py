"""hs_rates.duty_rate и geo_special_duties.duty_rate — строка (полная формулировка ставки).

Revision ID: n5o6p7q8r9s0
Revises: m3n4o5p6q7r8
Create Date: 2026-04-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n5o6p7q8r9s0"
down_revision: Union[str, Sequence[str], None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        with op.batch_alter_table("hs_rates") as batch:
            batch.alter_column(
                "duty_rate",
                existing_type=sa.REAL(),
                type_=sa.String(length=2048),
                nullable=False,
                server_default="0",
            )
        with op.batch_alter_table("geo_special_duties") as batch:
            batch.alter_column(
                "duty_rate",
                existing_type=sa.REAL(),
                type_=sa.String(length=512),
                nullable=False,
                server_default="0",
            )
    else:
        op.execute(
            sa.text(
                "ALTER TABLE hs_rates ALTER COLUMN duty_rate TYPE VARCHAR(2048) "
                "USING trim(cast(duty_rate AS text))"
            )
        )
        op.execute(
            sa.text(
                "ALTER TABLE geo_special_duties ALTER COLUMN duty_rate TYPE VARCHAR(512) "
                "USING trim(cast(duty_rate AS text))"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        with op.batch_alter_table("hs_rates") as batch:
            batch.alter_column(
                "duty_rate",
                existing_type=sa.String(length=2048),
                type_=sa.REAL(),
                nullable=False,
                server_default="0",
            )
        with op.batch_alter_table("geo_special_duties") as batch:
            batch.alter_column(
                "duty_rate",
                existing_type=sa.String(length=512),
                type_=sa.REAL(),
                nullable=False,
                server_default="0",
            )
    else:
        op.execute(
            sa.text(
                "ALTER TABLE hs_rates ALTER COLUMN duty_rate TYPE double precision "
                "USING CASE "
                "WHEN trim(duty_rate) ~ '^[0-9]+\\.?[0-9]*$' THEN trim(duty_rate)::double precision "
                "ELSE 0 END"
            )
        )
        op.execute(
            sa.text(
                "ALTER TABLE geo_special_duties ALTER COLUMN duty_rate TYPE double precision "
                "USING CASE "
                "WHEN trim(duty_rate) ~ '^[0-9]+\\.?[0-9]*$' THEN trim(duty_rate)::double precision "
                "ELSE 0 END"
            )
        )
