"""Isolated legacy parsing/storage and specific-duty arithmetic, never legal admission."""
from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.core import HsRate, SourceStatus, SyncLog
from app.models.tnved import Chapter, Commodity, HsDutyRule, Section
from app.services.duty_rules_backfill import (
    _backfill_fixture_duty_rules,
    backfill_duty_rules_from_hs_rates,
)
from app.services.payment_engine import _find_duty_rule_for_hs


class IsolatedDutyFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.stack = ExitStack()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.stack.close)
        for target in ("app.services.payment_engine.SessionLocal", "app.services.normative_store.SessionLocal"):
            self.stack.enter_context(patch(target, self.sessions))
        with self.sessions() as db:
            section = Section(roman_number="FIXTURE", title="Synthetic, no legal authority")
            db.add(section)
            db.flush()
            chapter = Chapter(section_id=section.id, code="63", title="Synthetic fixture")
            db.add(chapter)
            db.flush()
            db.add(Commodity(chapter_id=chapter.id, code="6303929000", description="Synthetic arithmetic fixture"))
            db.add(HsRate(
                hs_code="6303929000", hs_prefix="", duty_rate="0,61 евро/кг",
                vat_import_rate=22, source_revision="bulk-ai-fixture-unreviewed", source_url="",
            ))
            db.commit()

    def store_fixture(self, *, only_missing=True):
        with self.sessions() as db:
            self.assertEqual(db.get_bind().url.database, ":memory:")
            stats = _backfill_fixture_duty_rules(db, only_missing=only_missing)
            db.commit()
            self.assertEqual(db.query(SourceStatus).count(), 0)
            self.assertEqual(db.query(SyncLog).count(), 0)
            return stats


class DutyRulesBackfillTests(IsolatedDutyFixture):
    def test_backfill_creates_specific_rule_for_6303929000(self) -> None:
        # The public method cannot promote the identical unreviewed source.
        with self.sessions() as db:
            blocked = backfill_duty_rules_from_hs_rates(db, only_missing=True)
            self.assertEqual(blocked["status"], "manual_review_required")
            self.assertEqual(db.query(HsDutyRule).count(), 0)
        stats = self.store_fixture()
        with self.sessions() as db:
            row = db.query(HsDutyRule).filter(HsDutyRule.commodity_code == "6303929000").one()

        self.assertEqual(stats["created"], 1)
        self.assertEqual(row.type, "specific")
        self.assertAlmostEqual(float(row.specific_amount or 0), 0.61)
        self.assertEqual(row.specific_currency, "EUR")
        self.assertEqual(row.specific_uom, "kg")
        rule, match_len = _find_duty_rule_for_hs("6303929000")
        self.assertEqual(match_len, 10)
        self.assertIsNotNone(rule)
        assert rule is not None
        self.assertEqual(rule.type, "specific")
        self.assertAlmostEqual(float(rule.specific_amount or 0), 0.61)

    def test_fixture_only_missing_and_update_preserve_exact_arithmetic(self) -> None:
        self.assertEqual(self.store_fixture()["created"], 1)
        self.assertEqual(self.store_fixture()["skipped"], 1)
        with self.sessions() as db:
            db.query(HsRate).one().duty_rate = "7,5%"
            db.commit()
            blocked = backfill_duty_rules_from_hs_rates(db, only_missing=False)
            self.assertFalse(blocked["db_mutated"])
            self.assertEqual(db.query(HsDutyRule).one().type, "specific")
        self.assertEqual(self.store_fixture(only_missing=False)["updated"], 1)
        with self.sessions() as db:
            row = db.query(HsDutyRule).one()
            self.assertEqual(row.type, "ad_valorem")
            self.assertEqual(row.ad_valorem_pct, 7.5)
            self.assertIsNone(row.specific_amount)


class SpecificDutyComputeTests(IsolatedDutyFixture):
    def test_compute_6303929000_with_net_weight(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.calculator import router

        self.store_fixture()
        app = FastAPI()
        app.include_router(router, prefix="/api/calculator")
        # Fixed synthetic FX isolates arithmetic from current CBR/network state.
        self.stack.enter_context(patch("app.api.calculator.get_rates_map", return_value={"RUB": 1, "EUR": 82.8}))
        self.stack.enter_context(patch("app.services.rate_display.resolve_excise_for_hs", return_value=("none", 0, "")))
        with TestClient(app) as client:
            resp = client.post(
                "/api/calculator/compute",
                json={
                    "hs_code": "6303929000", "customs_value": 331400.92,
                    "currency": "RUB", "country_of_origin": "CN",
                    "quantity": 1, "net_weight_kg": 1860.84, "save_history": False,
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        breakdown = data.get("breakdown") or {}
        duty = float(breakdown.get("duty") or 0)
        self.assertGreater(duty, 90000.0)
        self.assertLess(abs(duty - 93962.90), 4000.0)
        self.assertAlmostEqual(duty, round(0.61 * 1860.84 * 82.8, 2), places=2)
        auto = data.get("auto_detected") or {}
        self.assertEqual(auto.get("duty_rule_type"), "specific")


if __name__ == "__main__":
    unittest.main()
