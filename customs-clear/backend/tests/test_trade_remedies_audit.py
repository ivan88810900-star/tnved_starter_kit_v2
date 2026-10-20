"""Trade remedies audit — migration e4f5b0a1b2c3 (Issue #170)."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


SessionLocal: sessionmaker | None = None


def _run_upgrade(backend: Path, env: dict[str, str], revision: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(backend / "alembic.ini"), "upgrade", revision],
        cwd=backend,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _seed_pre_audit_rows(database: Path) -> None:
    """Recreate the row-count/type boundary that migration e4f5 audits."""
    junk_ids = (1, 2, 4, 5, 6)
    retained_types = ("anti_dumping",) * 24 + ("special_safeguard",) * 3 + ("countervailing",) * 2
    rows = [
        (
            row_id,
            f"99{row_id:08d}"[-10:],
            "ZZ",
            1.0,
            0.0,
            "USD",
            f"TEST-LEGACY-{row_id}",
            "anti_dumping",
            "",
            "synthetic migration-boundary junk row",
            "2020-01-01",
            "2030-01-01",
            "LEGACY_TEST",
            "legacy-test",
            "https://example.invalid/legacy-test",
        )
        for row_id in junk_ids
    ]
    rows.extend(
        (
            100 + index,
            f"98{index:08d}"[-10:],
            "ZZ",
            1.0,
            0.0,
            "USD",
            f"TEST-RETAINED-{index}",
            measure_type,
            "",
            "synthetic migration-boundary retained row",
            "2020-01-01",
            "2030-01-01",
            "EEC_TEST" if measure_type == "anti_dumping" else "TEST",
            "retained-test",
            "https://example.invalid/retained-test",
        )
        for index, measure_type in enumerate(retained_types)
    )
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO special_duties (
                id, hs_code_prefix, origin_country, rate_percent, rate_specific,
                currency_code, regulatory_act, measure_type,
                manufacturer_exporter, product_description,
                effective_from, effective_to,
                source_code, source_revision, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


@pytest.fixture(scope="class", autouse=True)
def _trade_remedies_migration_fixture(tmp_path_factory: pytest.TempPathFactory):
    global SessionLocal

    backend = Path(__file__).resolve().parents[1]
    database = tmp_path_factory.mktemp("trade-remedies-audit") / "migration.sqlite"
    url = f"sqlite:///{database}"
    env = os.environ.copy()
    env["DATABASE_URL"] = url

    _run_upgrade(backend, env, "d3e4f5b0a1b2")
    _seed_pre_audit_rows(database)
    _run_upgrade(backend, env, "e4f5b0a1b2c3")

    engine = create_engine(url)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        yield
    finally:
        SessionLocal = None
        engine.dispose()


class TestTradeRemediesAudit:
    @pytest.fixture(autouse=True)
    def _db(self):
        assert SessionLocal is not None
        self.db = SessionLocal()
        yield
        self.db.close()

    def test_legacy_junk_rows_removed(self) -> None:
        rows = self.db.execute(
            text("SELECT id FROM special_duties WHERE id IN (1, 2, 4, 5, 6)")
        ).fetchall()
        assert len(rows) == 0

    def test_total_special_duties_count(self) -> None:
        total = self.db.execute(text("SELECT COUNT(*) FROM special_duties")).scalar()
        assert total == 33

    def test_new_measures_present(self) -> None:
        foil = self.db.execute(
            text(
                """
                SELECT rate_percent FROM special_duties
                WHERE hs_code_prefix = '7607' AND origin_country = 'CN'
                  AND regulatory_act LIKE '%№ 97%'
                """
            )
        ).fetchone()
        assert foil is not None
        assert float(foil[0]) == pytest.approx(20.24)

        tio2 = self.db.execute(
            text(
                """
                SELECT rate_percent FROM special_duties
                WHERE hs_code_prefix = '3206' AND origin_country = 'CN'
                  AND regulatory_act LIKE '%№ 96%'
                """
            )
        ).fetchone()
        assert tio2 is not None
        assert float(tio2[0]) == pytest.approx(16.25)

        tape_az = self.db.execute(
            text(
                """
                SELECT rate_percent, effective_to FROM special_duties
                WHERE hs_code_prefix = '7607' AND origin_country = 'AZ'
                """
            )
        ).fetchone()
        assert tape_az is not None
        assert float(tape_az[0]) == pytest.approx(16.18)
        assert str(tape_az[1]).startswith("2031")

        stainless = self.db.execute(
            text(
                """
                SELECT rate_percent FROM special_duties
                WHERE hs_code_prefix = '730640' AND origin_country = 'CN'
                """
            )
        ).fetchone()
        assert stainless is not None
        assert float(stainless[0]) == pytest.approx(17.28)

    def test_measure_type_breakdown(self) -> None:
        rows = self.db.execute(
            text(
                """
                SELECT measure_type, COUNT(*),
                  SUM(CASE WHEN source_code LIKE 'EEC%' THEN 1 ELSE 0 END) AS official
                FROM special_duties
                GROUP BY measure_type
                ORDER BY measure_type
                """
            )
        ).fetchall()
        by_type = {r[0]: (r[1], r[2]) for r in rows}
        assert by_type["anti_dumping"][0] == 28
        assert by_type["anti_dumping"][1] == 28
        assert by_type["special_safeguard"][0] == 3
        assert by_type["countervailing"][0] == 2

    def test_needs_verification_column_exists(self) -> None:
        row = self.db.execute(
            text(
                """
                SELECT needs_verification FROM special_duties
                WHERE hs_code_prefix = '7607' AND origin_country = 'CN'
                  AND regulatory_act LIKE '%№ 97%'
                """
            )
        ).fetchone()
        assert row is not None
        assert row[0] in (0, False)
