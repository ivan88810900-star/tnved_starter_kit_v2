"""sync_schema_with_orm: таблицы из ORM + колонки tnved_commodities (SQLite batch).

Revision ID: 6e714a1a9b05
Revises: 362469881239
Create Date: 2026-04-13 11:20:06.787174

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "6e714a1a9b05"
down_revision: Union[str, Sequence[str], None] = "362469881239"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    if not inspect(bind).has_table(table):
        return False
    cols = {c["name"] for c in inspect(bind).get_columns(table)}
    return column in cols


def upgrade() -> None:
    if not _table_exists("exchange_rates"):
        op.create_table(
            "exchange_rates",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("currency_code", sa.String(length=8), nullable=False),
            sa.Column("rate", sa.Float(), nullable=False),
            sa.Column("nominal", sa.Float(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("exchange_rates", schema=None) as batch_op:
            batch_op.create_index("ix_exchange_rates_currency_code", ["currency_code"], unique=True)
            batch_op.create_index(batch_op.f("ix_exchange_rates_updated_at"), ["updated_at"], unique=False)

    if not _table_exists("intellectual_properties"):
        op.create_table(
            "intellectual_properties",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("brand_name", sa.String(length=255), nullable=False),
            sa.Column("hs_code_prefix", sa.String(length=6), nullable=False),
            sa.Column("reg_number", sa.String(length=128), nullable=False),
            sa.Column("right_holder", sa.String(length=255), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "brand_name",
                "hs_code_prefix",
                "reg_number",
                name="uq_intellectual_properties_brand_prefix_reg",
            ),
        )
        with op.batch_alter_table("intellectual_properties", schema=None) as batch_op:
            batch_op.create_index("ix_intellectual_properties_brand", ["brand_name"], unique=False)
            batch_op.create_index("ix_intellectual_properties_hs_prefix", ["hs_code_prefix"], unique=False)

    if not _table_exists("normative_notes"):
        op.create_table(
            "normative_notes",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("scope_type", sa.String(length=16), nullable=False),
            sa.Column("scope_value", sa.String(length=12), nullable=False),
            sa.Column("category", sa.String(length=32), nullable=False),
            sa.Column("title", sa.String(length=512), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("source_revision", sa.String(length=128), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("normative_notes", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_normative_notes_category"), ["category"], unique=False)
            batch_op.create_index(batch_op.f("ix_normative_notes_scope_type"), ["scope_type"], unique=False)
            batch_op.create_index(batch_op.f("ix_normative_notes_scope_value"), ["scope_value"], unique=False)

    if not _table_exists("special_duties"):
        op.create_table(
            "special_duties",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("hs_code_prefix", sa.String(length=16), nullable=False),
            sa.Column("origin_country", sa.String(length=8), nullable=False),
            sa.Column("rate_percent", sa.Float(), nullable=False),
            sa.Column("rate_specific", sa.Float(), nullable=False),
            sa.Column("currency_code", sa.String(length=8), nullable=False),
            sa.Column("regulatory_act", sa.String(length=255), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("special_duties", schema=None) as batch_op:
            batch_op.create_index("ix_special_duties_hs_prefix", ["hs_code_prefix"], unique=False)
            batch_op.create_index("ix_special_duties_origin_country", ["origin_country"], unique=False)

    if not _table_exists("tamdoc_sync_candidates"):
        op.create_table(
            "tamdoc_sync_candidates",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("doc_url", sa.String(length=512), nullable=False),
            sa.Column("doc_title", sa.String(length=255), nullable=False),
            sa.Column("doc_type", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("hs_prefix", sa.String(length=16), nullable=False),
            sa.Column("country_codes", sa.String(length=128), nullable=False),
            sa.Column("vat_rates", sa.String(length=32), nullable=False),
            sa.Column("percent_rates", sa.String(length=64), nullable=False),
            sa.Column("measure_type_hint", sa.String(length=32), nullable=False),
            sa.Column("excerpt", sa.Text(), nullable=False),
            sa.Column("error_message", sa.String(length=512), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("tamdoc_sync_candidates", schema=None) as batch_op:
            batch_op.create_index("ix_tamdoc_candidates_doc_url", ["doc_url"], unique=False)
            batch_op.create_index("ix_tamdoc_candidates_hs_prefix", ["hs_prefix"], unique=False)
            batch_op.create_index("ix_tamdoc_candidates_status", ["status"], unique=False)

    if not _table_exists("tnved_entries"):
        op.create_table(
            "tnved_entries",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("hs_code", sa.String(length=12), nullable=False),
            sa.Column("parent_hs", sa.String(length=12), nullable=False),
            sa.Column("level", sa.Integer(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("chapter", sa.String(length=4), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("source_revision", sa.String(length=128), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("tnved_entries", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_tnved_entries_chapter"), ["chapter"], unique=False)
            batch_op.create_index(batch_op.f("ix_tnved_entries_hs_code"), ["hs_code"], unique=True)
            batch_op.create_index(batch_op.f("ix_tnved_entries_parent_hs"), ["parent_hs"], unique=False)

    if not _table_exists("tr_ts_acts"):
        op.create_table(
            "tr_ts_acts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("act_code", sa.String(length=32), nullable=False),
            sa.Column("short_name", sa.String(length=512), nullable=False),
            sa.Column("full_title", sa.Text(), nullable=False),
            sa.Column("edition_note", sa.Text(), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("source_revision", sa.String(length=128), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("tr_ts_acts", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_tr_ts_acts_act_code"), ["act_code"], unique=True)

    if not _table_exists("vat_preferences"):
        op.create_table(
            "vat_preferences",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("hs_code_prefix", sa.String(length=16), nullable=False),
            sa.Column("vat_rate", sa.Integer(), nullable=False),
            sa.Column("decree_info", sa.String(length=255), nullable=False),
            sa.Column("comment", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "hs_code_prefix",
                "vat_rate",
                "decree_info",
                name="uq_vat_preferences_prefix_rate_decree",
            ),
        )
        with op.batch_alter_table("vat_preferences", schema=None) as batch_op:
            batch_op.create_index("ix_vat_preferences_hs_prefix", ["hs_code_prefix"], unique=False)
            batch_op.create_index("ix_vat_preferences_vat_rate", ["vat_rate"], unique=False)

    if _table_exists("tnved_commodities"):
        add_supp = not _column_exists("tnved_commodities", "supp_unit")
        add_wc = not _column_exists("tnved_commodities", "weight_coeff")
        if add_supp or add_wc:
            with op.batch_alter_table("tnved_commodities", schema=None) as batch_op:
                if add_supp:
                    batch_op.add_column(
                        sa.Column(
                            "supp_unit",
                            sa.String(length=16),
                            nullable=False,
                            server_default=sa.text("''"),
                        )
                    )
                if add_wc:
                    batch_op.add_column(
                        sa.Column(
                            "weight_coeff",
                            sa.Float(),
                            nullable=False,
                            server_default=sa.text("0"),
                        )
                    )


def downgrade() -> None:
    if _table_exists("tnved_commodities"):
        with op.batch_alter_table("tnved_commodities", schema=None) as batch_op:
            if _column_exists("tnved_commodities", "weight_coeff"):
                batch_op.drop_column("weight_coeff")
            if _column_exists("tnved_commodities", "supp_unit"):
                batch_op.drop_column("supp_unit")

    if _table_exists("vat_preferences"):
        with op.batch_alter_table("vat_preferences", schema=None) as batch_op:
            batch_op.drop_index("ix_vat_preferences_vat_rate")
            batch_op.drop_index("ix_vat_preferences_hs_prefix")
        op.drop_table("vat_preferences")

    if _table_exists("tr_ts_acts"):
        with op.batch_alter_table("tr_ts_acts", schema=None) as batch_op:
            batch_op.drop_index(batch_op.f("ix_tr_ts_acts_act_code"))
        op.drop_table("tr_ts_acts")

    if _table_exists("tnved_entries"):
        with op.batch_alter_table("tnved_entries", schema=None) as batch_op:
            batch_op.drop_index(batch_op.f("ix_tnved_entries_parent_hs"))
            batch_op.drop_index(batch_op.f("ix_tnved_entries_hs_code"))
            batch_op.drop_index(batch_op.f("ix_tnved_entries_chapter"))
        op.drop_table("tnved_entries")

    if _table_exists("tamdoc_sync_candidates"):
        with op.batch_alter_table("tamdoc_sync_candidates", schema=None) as batch_op:
            batch_op.drop_index("ix_tamdoc_candidates_status")
            batch_op.drop_index("ix_tamdoc_candidates_hs_prefix")
            batch_op.drop_index("ix_tamdoc_candidates_doc_url")
        op.drop_table("tamdoc_sync_candidates")

    if _table_exists("special_duties"):
        with op.batch_alter_table("special_duties", schema=None) as batch_op:
            batch_op.drop_index("ix_special_duties_origin_country")
            batch_op.drop_index("ix_special_duties_hs_prefix")
        op.drop_table("special_duties")

    if _table_exists("normative_notes"):
        with op.batch_alter_table("normative_notes", schema=None) as batch_op:
            batch_op.drop_index(batch_op.f("ix_normative_notes_scope_value"))
            batch_op.drop_index(batch_op.f("ix_normative_notes_scope_type"))
            batch_op.drop_index(batch_op.f("ix_normative_notes_category"))
        op.drop_table("normative_notes")

    if _table_exists("intellectual_properties"):
        with op.batch_alter_table("intellectual_properties", schema=None) as batch_op:
            batch_op.drop_index("ix_intellectual_properties_hs_prefix")
            batch_op.drop_index("ix_intellectual_properties_brand")
        op.drop_table("intellectual_properties")

    if _table_exists("exchange_rates"):
        with op.batch_alter_table("exchange_rates", schema=None) as batch_op:
            batch_op.drop_index(batch_op.f("ix_exchange_rates_updated_at"))
            batch_op.drop_index("ix_exchange_rates_currency_code")
        op.drop_table("exchange_rates")
