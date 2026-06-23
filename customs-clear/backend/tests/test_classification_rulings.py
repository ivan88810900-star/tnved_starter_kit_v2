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

    def test_total_entries_at_least_50(self) -> None:
        # Базовый курируемый набор (50) + опциональное расширение справочными
        # записями (scripts/expand_classification_rulings.py) → ≥ 50.
        total = self.db.execute(text("SELECT COUNT(*) FROM classification_rulings")).scalar()
        assert total >= 50

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

    def test_is_official_flags(self) -> None:
        official = self.db.execute(
            text("SELECT COUNT(*) FROM classification_rulings WHERE is_official = 1")
        ).scalar()
        reference = self.db.execute(
            text("SELECT COUNT(*) FROM classification_rulings WHERE is_official = 0")
        ).scalar()
        assert official >= 50
        assert reference >= 500
        tnved_ref = self.db.execute(
            text(
                "SELECT COUNT(*) FROM classification_rulings "
                "WHERE agency = 'ТНВЭД-REF' AND is_official = 0"
            )
        ).scalar()
        assert tnved_ref >= 500

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

    def test_lookup_includes_is_official(self) -> None:
        results = find_classification_rulings("8517120000", limit=5)
        assert results
        assert all("is_official" in r for r in results)


class TestClassificationRulingsExpansion:
    """Issue #125: генератор справочных решений из реального каталога ТН ВЭД."""

    def test_generator_yields_500_plus_real_catalog_rows(self) -> None:
        from scripts.expand_classification_rulings import _build_rows

        rows = _build_rows(target=520, per_chapter=8)
        assert len(rows) >= 500
        # Каждая запись привязана к реальному 10-значному коду и имеет обоснование.
        for r in rows:
            assert len(r["hs"]) == 10 and r["hs"].isdigit()
            assert r["desc"].strip()
            assert "ОПИ" in r["rationale"]
            # Справочные записи явно помечены (не выдаются за официальные ФТС/ЕЭК).
            assert r["agency"] == "ТНВЭД-REF"
            assert r["num"].startswith("REF-ТНВЭД-")

    def test_generator_rows_are_unique(self) -> None:
        from scripts.expand_classification_rulings import _build_rows

        rows = _build_rows(target=520, per_chapter=8)
        nums = [r["num"] for r in rows]
        assert len(nums) == len(set(nums))
