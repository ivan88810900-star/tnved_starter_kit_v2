"""Таблицы геополитики: country_regulations, increased_duties, sanction_import_risks + seed.

Revision ID: j9k0l1m2n3o4
Revises: h5i6j7k8l0m1
Create Date: 2026-04-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "j9k0l1m2n3o4"
down_revision: Union[str, Sequence[str], None] = "h5i6j7k8l0m1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table_exists("country_regulations"):
        op.create_table(
            "country_regulations",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("iso_code", sa.String(length=2), nullable=False),
            sa.Column("country_name", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("is_unfriendly", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("has_preferential_agreement", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("iso_code", name="uq_country_regulations_iso_code"),
        )
        with op.batch_alter_table("country_regulations", schema=None) as batch_op:
            batch_op.create_index("ix_country_regulations_iso_code", ["iso_code"], unique=False)

    if not _table_exists("increased_duties"):
        op.create_table(
            "increased_duties",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("hs_code_prefix", sa.String(length=10), nullable=False),
            sa.Column("country_iso", sa.String(length=4), nullable=False, server_default="*"),
            sa.Column("increased_rate", sa.Float(), nullable=False),
            sa.Column("source_note", sa.Text(), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("increased_duties", schema=None) as batch_op:
            batch_op.create_index("ix_increased_duties_hs_code_prefix", ["hs_code_prefix"], unique=False)
            batch_op.create_index("ix_increased_duties_country_iso", ["country_iso"], unique=False)

    if not _table_exists("sanction_import_risks"):
        op.create_table(
            "sanction_import_risks",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("hs_code_prefix", sa.String(length=10), nullable=False),
            sa.Column("jurisdiction", sa.String(length=8), nullable=False, server_default="EU"),
            sa.Column("risk_level", sa.String(length=16), nullable=False, server_default="risk"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("sanction_import_risks", schema=None) as batch_op:
            batch_op.create_index("ix_sanction_import_risks_hs_code_prefix", ["hs_code_prefix"], unique=False)
            batch_op.create_index("ix_sanction_import_risks_jurisdiction", ["jurisdiction"], unique=False)

    conn = op.get_bind()
    # idempotent seed: count rows
    def _seed_count(table: str) -> int:
        r = conn.execute(sa.text(f"SELECT COUNT(*) AS c FROM {table}")).mappings().first()
        return int(r["c"]) if r else 0

    if _table_exists("country_regulations") and _seed_count("country_regulations") == 0:
        countries = [
            ("US", "США", 1, 0),
            ("GB", "Великобритания", 1, 0),
            ("DE", "Германия", 1, 0),
            ("FR", "Франция", 1, 0),
            ("IT", "Италия", 1, 0),
            ("CA", "Канада", 1, 0),
            ("AU", "Австралия", 1, 0),
            ("JP", "Япония", 1, 0),
            ("PL", "Польша", 1, 0),
            ("UA", "Украина", 0, 0),
            ("VN", "Вьетнам", 0, 1),
            ("KZ", "Казахстан", 0, 1),
            ("BY", "Беларусь", 0, 1),
            ("AM", "Армения", 0, 1),
            ("KG", "Кыргызстан", 0, 1),
            ("CN", "Китай", 0, 0),
        ]
        for iso, name, unf, pref in countries:
            conn.execute(
                sa.text(
                    "INSERT INTO country_regulations (iso_code, country_name, is_unfriendly, has_preferential_agreement) "
                    "VALUES (:iso, :name, :unf, :pref)"
                ),
                {"iso": iso, "name": name, "unf": bool(unf), "pref": bool(pref)},
            )

    if _table_exists("increased_duties") and _seed_count("increased_duties") == 0:
        # Примеры повышенных ставок (демо, не юридическая консультация): косметика 33, оружие 93, станки 84/85
        duties = [
            ("3304", "US", 35.0, "Пример: косметика / личная химия — недружественная страна (см. актуальный перечень ПП РФ)"),
            ("3304", "DE", 35.0, "Пример: косметика из ЕС"),
            ("3304", "*", 32.0, "Пример: косметика — любая недружественная (* при совпадении со справочником стран)"),
            ("9305", "US", 50.0, "Пример: части и принадлежности к оружию"),
            ("9303", "GB", 50.0, "Пример: взрывное оружие / боеприпасы (категория)"),
            ("8457", "US", 30.0, "Пример: обрабатывающие центры"),
            ("8458", "DE", 30.0, "Пример: токарные станки"),
            ("8517", "US", 25.0, "Пример: телеком/связь (фрагмент главы 85)"),
        ]
        for pref, ciso, rate, note in duties:
            conn.execute(
                sa.text(
                    "INSERT INTO increased_duties (hs_code_prefix, country_iso, increased_rate, source_note) "
                    "VALUES (:p, :c, :r, :n)"
                ),
                {"p": pref, "c": ciso, "r": float(rate), "n": note},
            )

    if _table_exists("sanction_import_risks") and _seed_count("sanction_import_risks") == 0:
        risks = [
            ("9303", "EU", "forbidden", "Категория оружия/боеприпасы — перекрёстная проверка санкционных списков ЕС"),
            ("9304", "US", "risk", "Военное / гражданское оружие — экспортный контроль США"),
            ("8542", "US", "risk", "Микросхемы / полупроводники — режим US export controls"),
            ("8471", "US", "risk", "Вычислительная техника — лицензирование и списки"),
            ("8802", "EU", "risk", "Беспилотные системы — санкционные пакеты ЕС (пример)"),
            ("7102", "UK", "risk", "Драгоценные камни — пакеты ограничений UK (пример)"),
        ]
        for pref, jur, lvl, desc in risks:
            conn.execute(
                sa.text(
                    "INSERT INTO sanction_import_risks (hs_code_prefix, jurisdiction, risk_level, description) "
                    "VALUES (:p, :j, :l, :d)"
                ),
                {"p": pref, "j": jur, "l": lvl, "d": desc},
            )


def downgrade() -> None:
    for t in ("sanction_import_risks", "increased_duties", "country_regulations"):
        if _table_exists(t):
            op.drop_table(t)
