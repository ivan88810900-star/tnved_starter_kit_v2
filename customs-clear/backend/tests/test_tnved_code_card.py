"""Unit-тесты сервиса карточки ТН ВЭД: предварительные решения."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.core import ClassificationDecision, PreliminaryDecision
from app.services.tnved_code_card import find_preliminary_decisions_for_hs, hs_prefix_candidates


class TnvedCodeCardServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[ClassificationDecision.__table__, PreliminaryDecision.__table__],
        )
        cls.Session = sessionmaker(bind=engine)
        with cls.Session() as db:
            db.add(
                ClassificationDecision(
                    hs_code="8471300000",
                    product_name="Ноутбук",
                    description="Портативный компьютер",
                    target_entity="Ноутбук",
                    decision_number="PKR-847130-1",
                    issue_date="2023-06-01",
                )
            )
            db.add(
                PreliminaryDecision(
                    hs_code="8471300000",
                    description="IFCG: ноутбук переносной",
                    source="ifcg",
                )
            )
            db.commit()

    def test_hs_prefix_candidates(self):
        self.assertEqual(hs_prefix_candidates("8471300000"), ["8471300000", "847130", "8471"])

    def test_find_decisions_merges_sources(self):
        with self.Session() as db:
            block = find_preliminary_decisions_for_hs(db, "8471300000")
        self.assertEqual(block["total_count"], 2)
        self.assertEqual(len(block["classification_decisions"]), 1)
        self.assertEqual(block["classification_decisions"][0]["decision_number"], "PKR-847130-1")
        self.assertEqual(len(block["preliminary_decisions"]), 1)

    def test_find_decisions_empty(self):
        with self.Session() as db:
            block = find_preliminary_decisions_for_hs(db, "0000000000")
        self.assertEqual(block["total_count"], 0)
        self.assertTrue(block["empty_message"])


if __name__ == "__main__":
    unittest.main()
