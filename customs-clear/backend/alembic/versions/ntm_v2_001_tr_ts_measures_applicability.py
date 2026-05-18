"""NTM v2: measures + applicability rules (ТР ТС СС/ДС из каталога).

Revision ID: ntm_v2_001_tr_ts
Revises: p9q0r1s2t3u4
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "ntm_v2_001_tr_ts"
down_revision: Union[str, Sequence[str], None] = "p9q0r1s2t3u4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("ntm_measures_v2"):
        op.create_table(
            "ntm_measures_v2",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("measure_kind", sa.String(length=64), nullable=False),
            sa.Column("permit_type", sa.String(length=8), nullable=False),
            sa.Column("title", sa.String(length=512), nullable=False),
            sa.Column("short_description", sa.Text(), nullable=False, server_default=""),
            sa.Column("tr_ts_act_code", sa.String(length=32), nullable=False),
            sa.Column("regulatory_document_id", sa.String(length=64), nullable=True),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("source_kind", sa.String(length=64), nullable=False),
            sa.Column("source_ref", sa.String(length=255), nullable=False),
            sa.Column("import_key", sa.String(length=192), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("import_key", name="uq_ntm_measures_v2_import_key"),
        )
        op.create_index("ix_ntm_measures_v2_permit_type", "ntm_measures_v2", ["permit_type"])
        op.create_index("ix_ntm_measures_v2_measure_kind", "ntm_measures_v2", ["measure_kind"])
        op.create_index("ix_ntm_measures_v2_tr_ts_act_code", "ntm_measures_v2", ["tr_ts_act_code"])
        op.create_index("ix_ntm_measures_v2_status", "ntm_measures_v2", ["status"])

    if not _has_table("ntm_applicability_rules_v2"):
        op.create_table(
            "ntm_applicability_rules_v2",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("measure_id", sa.Integer(), nullable=False),
            sa.Column("direction", sa.String(length=16), nullable=False, server_default="import"),
            sa.Column("country_iso", sa.String(length=8), nullable=True),
            sa.Column("hs_scope_mode", sa.String(length=32), nullable=False, server_default="prefix"),
            sa.Column("hs_code", sa.String(length=16), nullable=False),
            sa.Column("excluded_hs_json", sa.JSON(), nullable=True),
            sa.Column("description_match_json", sa.JSON(), nullable=True),
            sa.Column("applicability", sa.String(length=32), nullable=False, server_default="definite"),
            sa.Column("requires_manual_review", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("source_kind", sa.String(length=64), nullable=False),
            sa.Column("source_ref", sa.String(length=255), nullable=False),
            sa.Column("rule_import_key", sa.String(length=256), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(
                ["measure_id"],
                ["ntm_measures_v2.id"],
                name="fk_ntm_applicability_rules_v2_measure",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("rule_import_key", name="uq_ntm_applicability_rules_v2_rule_import_key"),
        )
        op.create_index("ix_ntm_applicability_rules_v2_measure_id", "ntm_applicability_rules_v2", ["measure_id"])
        op.create_index("ix_ntm_applicability_rules_v2_hs_code", "ntm_applicability_rules_v2", ["hs_code"])
        op.create_index(
            "ix_ntm_applicability_rules_v2_hs_scope_hs",
            "ntm_applicability_rules_v2",
            ["hs_scope_mode", "hs_code"],
        )
        op.create_index("ix_ntm_applicability_rules_v2_direction", "ntm_applicability_rules_v2", ["direction"])
        op.create_index("ix_ntm_applicability_rules_v2_valid_from", "ntm_applicability_rules_v2", ["valid_from"])
        op.create_index("ix_ntm_applicability_rules_v2_valid_to", "ntm_applicability_rules_v2", ["valid_to"])


def downgrade() -> None:
    if _has_table("ntm_applicability_rules_v2"):
        op.drop_table("ntm_applicability_rules_v2")
    if _has_table("ntm_measures_v2"):
        op.drop_table("ntm_measures_v2")
