"""Add technical-only ETT normalization history to the staging schema.

Revision ID: j4k5l6m7n8o9
Revises: i4j5k6l7m8n9
Create Date: 2026-10-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "j4k5l6m7n8o9"
down_revision: Union[str, Sequence[str], None] = "i4j5k6l7m8n9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def normalization_results_table(
    metadata: sa.MetaData, *, schema: str | None = "tariff_ingest"
) -> sa.Table:
    prefix = f"{schema}." if schema else ""
    raw_key = f"{schema}.ett_collected_rows" if schema else "ett_collected_rows"
    if raw_key not in metadata.tables:
        sa.Table(
            "ett_collected_rows",
            metadata,
            sa.Column("source_id", sa.Text(), primary_key=True),
            sa.Column("row_sha256", sa.Text(), primary_key=True),
            schema=schema,
            extend_existing=True,
        )
    return sa.Table(
        "ett_normalization_results",
        metadata,
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("raw_row_sha256", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.Text(), nullable=False),
        sa.Column("hs_code", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("original_description", sa.Text(), nullable=False),
        sa.Column("original_supplementary_unit", sa.Text(), nullable=False),
        sa.Column("original_duty_text", sa.Text(), nullable=False),
        sa.Column("original_raw_line", sa.Text(), nullable=False),
        sa.Column("syntax_status", sa.Text(), nullable=False),
        sa.Column("normalized_rate_text", sa.Text(), nullable=True),
        sa.Column("is_ambiguous", sa.Boolean(), nullable=False),
        sa.Column("ambiguity_reason", sa.Text(), nullable=True),
        sa.Column("legal_status", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("admitted", sa.Boolean(), nullable=False),
        sa.Column("result_sha256", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("source_id", "raw_row_sha256", "parser_version"),
        sa.UniqueConstraint(
            "source_id",
            "ordinal",
            "parser_version",
            name="uq_ett_normalization_source_ordinal_version",
        ),
        sa.UniqueConstraint(
            "result_sha256", name="uq_ett_normalization_result_sha256"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "raw_row_sha256"],
            [
                f"{prefix}ett_collected_rows.source_id",
                f"{prefix}ett_collected_rows.row_sha256",
            ],
            name="fk_ett_normalization_raw_row",
        ),
        schema=schema,
    )


def create_normalization_results(bind, *, schema: str | None = "tariff_ingest") -> None:
    normalization_results_table(sa.MetaData(), schema=schema).create(bind=bind)


def drop_normalization_results(bind, *, schema: str | None = "tariff_ingest") -> None:
    normalization_results_table(sa.MetaData(), schema=schema).drop(bind=bind)


def upgrade() -> None:
    create_normalization_results(op.get_bind())


def downgrade() -> None:
    drop_normalization_results(op.get_bind())

