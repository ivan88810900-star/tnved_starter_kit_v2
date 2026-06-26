"""Tests for NTM full sync — coverage across all 97 HS chapters."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal


class TestNtmFullCoverage:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def test_total_ntm_entries_above_42000(self) -> None:
        count = self.db.execute(
            text("SELECT COUNT(*) FROM non_tariff_measures")
        ).scalar()
        assert count >= 42000, f"Expected >= 42000 NTM entries, got {count}"

    def test_all_96_active_chapters_covered(self) -> None:
        rows = self.db.execute(text(
            "SELECT DISTINCT SUBSTR(commodity_code, 1, 2) FROM non_tariff_measures"
        )).fetchall()
        chapters = {r[0] for r in rows}
        for ch_num in range(1, 98):
            ch = f"{ch_num:02d}"
            if ch == "77":
                continue
            assert ch in chapters, f"Chapter {ch} has no NTM entries"

    def test_no_chapter_below_10_except_77(self) -> None:
        rows = self.db.execute(text("""
            SELECT SUBSTR(commodity_code, 1, 2) AS ch, COUNT(*) AS cnt
            FROM non_tariff_measures
            GROUP BY ch HAVING cnt < 10
        """)).fetchall()
        thin = {r[0]: r[1] for r in rows if r[0] != "77"}
        assert len(thin) == 0, f"Chapters with <10 entries: {thin}"

    def test_all_major_measure_types_present(self) -> None:
        rows = self.db.execute(text(
            "SELECT DISTINCT measure_type FROM non_tariff_measures"
        )).fetchall()
        types = {r[0] for r in rows}
        expected = {"certificate", "license", "tr_ts", "sgr", "vet_control", "phyto_control", "marking"}
        missing = expected - types
        assert not missing, f"Missing measure types: {missing}"

    def test_no_licence_typo_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM non_tariff_measures WHERE measure_type = 'licence'"
        )).scalar()
        assert count == 0, f"Found {count} stale 'licence' entries (should be 'license')"

    def test_thin_chapters_now_have_diverse_types(self) -> None:
        formerly_thin = ["09", "11", "14", "15", "18", "19", "31", "45",
                         "50", "51", "53", "54", "60", "66", "67"]
        for ch in formerly_thin:
            types = self.db.execute(text(
                "SELECT COUNT(DISTINCT measure_type) FROM non_tariff_measures "
                "WHERE SUBSTR(commodity_code, 1, 2) = :ch"
            ), {"ch": ch}).scalar()
            assert types >= 3, f"Chapter {ch} should have >= 3 measure types, got {types}"

    def test_certificate_is_most_common_type(self) -> None:
        top = self.db.execute(text(
            "SELECT measure_type, COUNT(*) AS cnt FROM non_tariff_measures "
            "GROUP BY measure_type ORDER BY cnt DESC LIMIT 1"
        )).fetchone()
        assert top[0] == "certificate", f"Expected certificate as top type, got {top[0]}"

    def test_new_entries_have_valid_commodity_codes(self) -> None:
        """New 10-digit entries must reference valid tnved_commodities codes."""
        orphans = self.db.execute(text("""
            SELECT COUNT(*) FROM non_tariff_measures nm
            LEFT JOIN tnved_commodities tc ON nm.commodity_code = tc.code
            WHERE tc.code IS NULL AND LENGTH(nm.commodity_code) = 10
        """)).scalar()
        assert orphans == 0, f"Found {orphans} 10-digit NTM entries with invalid commodity_code"

    def test_quality_distribution_balanced(self) -> None:
        normal = self.db.execute(text(
            "SELECT COUNT(*) FROM non_tariff_measures WHERE quality = 'normal'"
        )).scalar()
        assert normal >= 15000, f"Expected >= 15000 normal quality entries, got {normal}"
