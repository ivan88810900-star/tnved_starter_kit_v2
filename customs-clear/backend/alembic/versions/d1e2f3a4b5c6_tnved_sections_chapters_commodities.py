"""tnved_sections, tnved_chapters, tnved_commodities — структура ТН ВЭД

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-04-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("tnved_sections"):
        op.create_table(
            "tnved_sections",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("roman_number", sa.String(length=16), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_tnved_sections_roman_number", "tnved_sections", ["roman_number"])

    if not _has_table("tnved_chapters"):
        op.create_table(
            "tnved_chapters",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("section_id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=2), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["section_id"], ["tnved_sections.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("section_id", "code", name="uq_tnved_chapters_section_code"),
        )
        op.create_index("ix_tnved_chapters_section_id", "tnved_chapters", ["section_id"])
        op.create_index("ix_tnved_chapters_code", "tnved_chapters", ["code"])

    if not _has_table("tnved_commodities"):
        op.create_table(
            "tnved_commodities",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("chapter_id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=32), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("unit", sa.String(length=64), nullable=False),
            sa.Column("import_duty", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["chapter_id"], ["tnved_chapters.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("chapter_id", "code", name="uq_tnved_commodities_chapter_code"),
        )
        op.create_index("ix_tnved_commodities_chapter_id", "tnved_commodities", ["chapter_id"])
        op.create_index("ix_tnved_commodities_code", "tnved_commodities", ["code"])


def downgrade() -> None:
    if _has_table("tnved_commodities"):
        op.drop_index("ix_tnved_commodities_code", table_name="tnved_commodities")
        op.drop_index("ix_tnved_commodities_chapter_id", table_name="tnved_commodities")
        op.drop_table("tnved_commodities")
    if _has_table("tnved_chapters"):
        op.drop_index("ix_tnved_chapters_code", table_name="tnved_chapters")
        op.drop_index("ix_tnved_chapters_section_id", table_name="tnved_chapters")
        op.drop_table("tnved_chapters")
    if _has_table("tnved_sections"):
        op.drop_index("ix_tnved_sections_roman_number", table_name="tnved_sections")
        op.drop_table("tnved_sections")
