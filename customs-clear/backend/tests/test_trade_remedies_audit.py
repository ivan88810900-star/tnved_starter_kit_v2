"""Trade remedies audit — migration e4f5b0a1b2c3 (Issue #170)."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal


class TestTradeRemediesAudit:
    @pytest.fixture(autouse=True)
    def _db(self):
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
