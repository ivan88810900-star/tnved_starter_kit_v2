"""Tests for classification rulings database — Issue #88."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.services.normative_store import find_classification_rulings


class TestClassificationRulingsData:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def test_total_entries_50(self) -> None:
        total = self.db.execute(text("SELECT COUNT(*) FROM classification_rulings")).scalar()
        assert total == 50

    def test_fts_rulings(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_rulings WHERE agency = 'FTS'"
        )).scalar()
        assert count >= 25

    def test_eec_rulings(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_rulings WHERE agency = 'EEC'"
        )).scalar()
        assert count >= 5

    def test_kts_rulings(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_rulings WHERE agency = 'KTS'"
        )).scalar()
        assert count >= 5

    def test_all_have_rationale(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_rulings WHERE rationale IS NULL OR rationale = ''"
        )).scalar()
        assert missing == 0

    def test_unique_ruling_numbers(self) -> None:
        dupes = self.db.execute(text("""
            SELECT ruling_number, COUNT(*) c
            FROM classification_rulings
            GROUP BY ruling_number HAVING c > 1
        """)).fetchall()
        assert len(dupes) == 0

    def test_all_have_hs_code(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_rulings WHERE assigned_hs_code IS NULL OR assigned_hs_code = ''"
        )).scalar()
        assert missing == 0


class TestClassificationRulingsLookup:
    def test_lookup_smartphone_8517(self) -> None:
        results = find_classification_rulings("8517120000")
        assert len(results) >= 1
        has_smartphone = any("смартфон" in r["goods_description"].lower() or "телефон" in r["goods_description"].lower() for r in results)
        assert has_smartphone

    def test_lookup_notebook_8471(self) -> None:
        results = find_classification_rulings("8471300000")
        assert len(results) >= 1

    def test_lookup_car_8703(self) -> None:
        results = find_classification_rulings("8703220000")
        assert len(results) >= 1

    def test_sorted_by_date_desc(self) -> None:
        results = find_classification_rulings("8517000000")
        if len(results) >= 2:
            dates = [r["ruling_date"] for r in results if r["ruling_date"]]
            assert dates == sorted(dates, reverse=True)

    def test_limit_works(self) -> None:
        results = find_classification_rulings("8517000000", limit=1)
        assert len(results) <= 1

    def test_no_results_for_rare_code(self) -> None:
        results = find_classification_rulings("0101210000")
        assert isinstance(results, list)
