"""Add OFAC/EU sanctions and country rules tables.

Revision ID: z3a4b5c6d7e8
Revises: y1z2a3b4c5d6
Create Date: 2026-04-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "y1z2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ofac_sdn_list",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("type", sa.String(length=64), nullable=False, server_default="other"),
        sa.Column("origin_country", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("aliases", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "type", "origin_country", name="uq_ofac_sdn_name_type_country"),
    )
    op.create_index("ix_ofac_sdn_name", "ofac_sdn_list", ["name"], unique=False)
    op.create_index("ix_ofac_sdn_origin_country", "ofac_sdn_list", ["origin_country"], unique=False)
    op.create_index("ix_ofac_sdn_list_type", "ofac_sdn_list", ["type"], unique=False)

    op.create_table(
        "eu_sanctions_list",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hs_code", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("entity_name", sa.String(length=1024), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hs_code", "entity_name", "description", name="uq_eu_sanctions_natural"),
    )
    op.create_index("ix_eu_sanctions_hs_code", "eu_sanctions_list", ["hs_code"], unique=False)
    op.create_index("ix_eu_sanctions_entity_name", "eu_sanctions_list", ["entity_name"], unique=False)

    op.create_table(
        "country_specific_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("country_code", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("rule_type", sa.String(length=64), nullable=False, server_default="other"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("country_code", "rule_type", "description", name="uq_country_specific_rules_natural"),
    )
    op.create_index(
        "ix_country_specific_rules_country_code",
        "country_specific_rules",
        ["country_code"],
        unique=False,
    )
    op.create_index(
        "ix_country_specific_rules_rule_type",
        "country_specific_rules",
        ["rule_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_country_specific_rules_rule_type", table_name="country_specific_rules")
    op.drop_index("ix_country_specific_rules_country_code", table_name="country_specific_rules")
    op.drop_table("country_specific_rules")

    op.drop_index("ix_eu_sanctions_entity_name", table_name="eu_sanctions_list")
    op.drop_index("ix_eu_sanctions_hs_code", table_name="eu_sanctions_list")
    op.drop_table("eu_sanctions_list")

    op.drop_index("ix_ofac_sdn_list_type", table_name="ofac_sdn_list")
    op.drop_index("ix_ofac_sdn_origin_country", table_name="ofac_sdn_list")
    op.drop_index("ix_ofac_sdn_name", table_name="ofac_sdn_list")
    op.drop_table("ofac_sdn_list")
