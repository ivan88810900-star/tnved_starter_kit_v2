"""Tests for commodity group regulatory documents."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal


class TestCommodityGroupDocs:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def _count_docs_with_prefix(self, prefix: str) -> int:
        return self.db.execute(text(
            "SELECT COUNT(DISTINCT m.doc_id) FROM regulatory_doc_hs_mapping m "
            "WHERE m.hs_prefix LIKE :pat"
        ), {"pat": f"{prefix}%"}).scalar()

    def test_electronics_has_crypto_notifications(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents "
            "WHERE agency IN ('FSB') AND title LIKE '%отификаци%'"
        )).scalar()
        assert count >= 8, f"Expected >= 8 FSB crypto notifications, got {count}"

    def test_automobiles_has_otts_docs(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents WHERE title LIKE '%ОТТС%'"
        )).scalar()
        assert count >= 5, f"Expected >= 5 OTTS docs, got {count}"

    def test_food_has_country_vet_requirements(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents "
            "WHERE agency = 'RSN' AND title LIKE '%етеринарн%требован%импорт%'"
        )).scalar()
        assert count >= 5, f"Expected >= 5 country-specific vet docs, got {count}"

    def test_pharma_has_ru_docs(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents "
            "WHERE agency = 'ROSZDRAV' AND title LIKE '%егистрац%'"
        )).scalar()
        assert count >= 3, f"Expected >= 3 registration docs, got {count}"

    def test_precious_metals_has_kimberley(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents WHERE title LIKE '%имберли%'"
        )).scalar()
        assert count >= 1

    def test_weapons_has_license_docs(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents "
            "WHERE title LIKE '%ицензиров%импорт%оруж%'"
        )).scalar()
        assert count >= 3

    def test_clothing_has_honest_mark(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents WHERE title LIKE '%естный Знак%'"
        )).scalar()
        assert count >= 3

    def test_chemicals_has_safety_sheets(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents WHERE title LIKE '%аспорт%безопасн%'"
        )).scalar()
        assert count >= 1
