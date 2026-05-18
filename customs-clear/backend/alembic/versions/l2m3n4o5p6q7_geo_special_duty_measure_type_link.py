"""geo_special_duties: measure_type, document_link, уникальность (префикс, основание, страна).

Revision ID: l2m3n4o5p6q7
Revises: k0l1m2n3o4p5
Create Date: 2026-04-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, Sequence[str], None] = "k0l1m2n3o4p5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("geo_special_duties"):
        return
    conn = op.get_bind()
    insp = inspect(conn)
    cols = {c["name"] for c in insp.get_columns("geo_special_duties")}
    uq_names = {u["name"] for u in insp.get_unique_constraints("geo_special_duties")}
    with op.batch_alter_table("geo_special_duties", schema=None) as batch_op:
        if "measure_type" not in cols:
            batch_op.add_column(
                sa.Column(
                    "measure_type",
                    sa.String(length=32),
                    nullable=False,
                    server_default="increased_duty",
                )
            )
        if "document_link" not in cols:
            batch_op.add_column(
                sa.Column(
                    "document_link",
                    sa.Text(),
                    nullable=False,
                    server_default="",
                )
            )
        if "uq_geo_special_duties_prefix_basis_country" not in uq_names:
            batch_op.create_unique_constraint(
                "uq_geo_special_duties_prefix_basis_country",
                ["hs_code_prefix", "document_basis", "country_iso"],
            )


def downgrade() -> None:
    if not _has_table("geo_special_duties"):
        return
    bind = op.get_bind()
    insp = inspect(bind)
    uq_names = {u["name"] for u in insp.get_unique_constraints("geo_special_duties")}
    cols = {c["name"] for c in insp.get_columns("geo_special_duties")}
    with op.batch_alter_table("geo_special_duties", schema=None) as batch_op:
        if "uq_geo_special_duties_prefix_basis_country" in uq_names:
            batch_op.drop_constraint("uq_geo_special_duties_prefix_basis_country", type_="unique")
        if "document_link" in cols:
            batch_op.drop_column("document_link")
        if "measure_type" in cols:
            batch_op.drop_column("measure_type")
