"""Tests for FTS classification letters seed."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal


class TestFtsClassificationLetters:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def test_total_fts_letters_above_200(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents "
            "WHERE agency = 'FTS' AND doc_type = 'letter' AND doc_number LIKE '06-73/%'"
        )).scalar()
        assert count >= 200, f"Expected >= 200 FTS classification letters, got {count}"

    def test_electronics_category_exists(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_decisions "
            "WHERE decision_number LIKE 'FTS-06-73/12%'"
        )).scalar()
        assert count >= 25, f"Expected >= 25 electronics letters, got {count}"

    def test_parts_category_exists(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_decisions "
            "WHERE decision_number LIKE 'FTS-06-73/22%'"
        )).scalar()
        assert count >= 20, f"Expected >= 20 parts letters, got {count}"

    def test_kits_category_exists(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_decisions "
            "WHERE decision_number LIKE 'FTS-06-73/33%'"
        )).scalar()
        assert count >= 10, f"Expected >= 10 kits letters, got {count}"

    def test_used_goods_category_exists(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_decisions "
            "WHERE decision_number LIKE 'FTS-06-73/44%'"
        )).scalar()
        assert count >= 10, f"Expected >= 10 used goods letters, got {count}"

    def test_samples_category_exists(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_decisions "
            "WHERE decision_number LIKE 'FTS-06-73/55%'"
        )).scalar()
        assert count >= 10, f"Expected >= 10 samples letters, got {count}"

    def test_all_letters_have_hs_mapping(self) -> None:
        letters_with_mapping = self.db.execute(text("""
            SELECT COUNT(DISTINCT rd.id) FROM regulatory_documents rd
            JOIN regulatory_doc_hs_mapping m ON rd.id = m.doc_id
            WHERE rd.agency = 'FTS' AND rd.doc_number LIKE '06-73/%'
        """)).scalar()
        assert letters_with_mapping >= 190, f"Expected >= 190 letters with HS mapping, got {letters_with_mapping}"

    def test_all_decisions_have_rationale(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_decisions "
            "WHERE decision_number LIKE 'FTS-06-73/%' "
            "AND (description IS NULL OR description = '')"
        )).scalar()
        assert missing == 0, f"Found {missing} decisions without rationale"

    def test_electronics_covers_key_hs_codes(self) -> None:
        for prefix in ["8471", "8517", "8543", "8528"]:
            count = self.db.execute(text(
                "SELECT COUNT(*) FROM classification_decisions "
                "WHERE decision_number LIKE 'FTS-06-73/12%' "
                "AND hs_code LIKE :pat"
            ), {"pat": f"{prefix}%"}).scalar()
            assert count >= 1, f"Electronics should cover {prefix}"

    def test_food_pharma_category_exists(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM classification_decisions "
            "WHERE decision_number LIKE 'FTS-06-73/77%'"
        )).scalar()
        assert count >= 20, f"Expected >= 20 food/pharma letters, got {count}"
