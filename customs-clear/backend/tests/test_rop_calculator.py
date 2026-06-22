"""Tests for ROP eco fee calculator (PP 1041 / PP 2414)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from sqlalchemy import text

    from app.db import SessionLocal, engine
    from app.models.rop import RopGoodsRate, RopPackagingDefault, RopPackagingRate
    from app.services.rop_calculator import calculate_rop, detect_packaging_type, get_goods_rate
    from scripts.import_rop_rates import main as import_main

    _AVAILABLE = True
    _IMPORT_ERROR = ""
except ImportError as exc:
    _AVAILABLE = False
    _IMPORT_ERROR = str(exc)


def _ensure_schema_and_data() -> None:
    """Apply migration head + import JSON if tables empty."""
    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(cfg, "head")

    session = SessionLocal()
    try:
        count = session.query(RopGoodsRate).count()
    finally:
        session.close()
    if count == 0:
        import_main()


@unittest.skipIf(not _AVAILABLE, f"ROP tests require deps: {_IMPORT_ERROR}")
class RopCalculatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _ensure_schema_and_data()
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.close()

    def test_goods_rates_loaded(self) -> None:
        count = self.db.query(RopGoodsRate).filter(RopGoodsRate.calendar_year == 2026).count()
        self.assertEqual(count, 16)

    def test_packaging_rates_loaded(self) -> None:
        count = self.db.query(RopPackagingRate).filter(RopPackagingRate.calendar_year == 2026).count()
        self.assertEqual(count, 36)

    def test_coal_not_subject_to_rop(self) -> None:
        out = calculate_rop(self.db, "2701190000", 1000, 1000, calendar_year=2026)
        self.assertTrue(out["not_subject_to_rop"])
        self.assertEqual(out["total_rop_rub"], 0.0)

    def test_iron_ore_not_subject(self) -> None:
        out = calculate_rop(self.db, "2601110000", 50000, 50000, calendar_year=2026)
        self.assertTrue(out["not_subject_to_rop"])

    def test_clothing_category_and_calculation(self) -> None:
        rate = get_goods_rate(self.db, "6109100000", 2026)
        self.assertIsNotNone(rate)
        assert rate is not None
        self.assertEqual(rate.pp2414_group, 1)
        net_kg = 100.0
        gross_kg = 105.0
        out = calculate_rop(self.db, "6109100000", gross_kg, net_kg, calendar_year=2026)
        expected_goods = net_kg * rate.rate_per_ton * rate.recycling_norm / 1000.0
        self.assertAlmostEqual(out["goods_rop_rub"], round(expected_goods, 2))
        self.assertFalse(out["not_subject_to_rop"])
        self.assertIn("текстиль", out["goods_category"].lower())

    def test_smartphone_with_carton_packaging(self) -> None:
        out = calculate_rop(
            self.db, "8517120000", weight_gross_kg=110, weight_net_kg=100,
            packaging_type="carton", calendar_year=2026,
        )
        self.assertGreater(out["packaging_rop_rub"], 0)
        self.assertEqual(out["packaging_type"], "carton")

    def test_steel_roll_packaging_type(self) -> None:
        ptype, reason = detect_packaging_type(self.db, "7208510000")
        self.assertEqual(ptype, "roll")
        self.assertIsNotNone(reason)

    def test_grain_bag_packaging_type(self) -> None:
        ptype, _ = detect_packaging_type(self.db, "1001900000")
        self.assertEqual(ptype, "bag")

    def test_bulk_steel_no_packaging_fee(self) -> None:
        out = calculate_rop(
            self.db, "7201100000", weight_gross_kg=1000, weight_net_kg=1000,
            calendar_year=2026,
        )
        self.assertEqual(out["packaging_rop_rub"], 0.0)
        ptype, _ = detect_packaging_type(self.db, "7201100000")
        self.assertEqual(ptype, "none")

    def test_tires_goods_rop(self) -> None:
        out = calculate_rop(self.db, "4011100000", 120, 100, calendar_year=2026)
        self.assertFalse(out["not_subject_to_rop"])
        self.assertEqual(out["goods_pp2414_group"], 5)
        self.assertGreater(out["goods_rop_rub"], 0)

    def test_batteries_high_rate(self) -> None:
        out = calculate_rop(self.db, "8506100000", 50, 48, calendar_year=2026)
        self.assertEqual(out["goods_pp2414_group"], 11)
        self.assertGreater(out["goods_rop_rub"], 100)

    def test_total_sum(self) -> None:
        out = calculate_rop(self.db, "8471300000", 105, 100, calendar_year=2026)
        self.assertEqual(
            out["total_rop_rub"],
            round(out["goods_rop_rub"] + out["packaging_rop_rub"], 2),
        )

    def test_json_legal_ref_present(self) -> None:
        path = Path(__file__).resolve().parents[1] / "data" / "rop_rates_2024.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("1041", doc["legal_ref"])
        self.assertEqual(len(doc["goods"]), 16)
        self.assertEqual(len(doc["packaging_groups"]), 36)


if __name__ == "__main__":
    unittest.main()
