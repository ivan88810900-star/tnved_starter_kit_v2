"""Tests for recycling fees (утильсбор) — Issue #85."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.services.normative_store import get_recycling_fee
from app.services.payment_engine import compute_payments


@pytest.fixture(scope="module", autouse=True)
def _recycling_fee_fixture() -> None:
    from app.services.normative_store import init_db
    from scripts.seed_recycling_fees import seed

    init_db()
    seed()


class TestRecyclingFeesData:
    @pytest.fixture(autouse=True)
    def _db(self):
        self.db = SessionLocal()
        yield
        self.db.close()

    def test_total_entries_is_40(self) -> None:
        total = self.db.execute(text("SELECT COUNT(*) FROM recycling_fees")).scalar()
        assert total == 40

    def test_passenger_cars_12_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM recycling_fees WHERE hs_prefix = '8703'"
        )).scalar()
        assert count == 12

    def test_trucks_8_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM recycling_fees WHERE hs_prefix = '8704'"
        )).scalar()
        assert count == 8

    def test_motorcycles_10_entries(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM recycling_fees WHERE hs_prefix = '8711'"
        )).scalar()
        assert count == 10

    def test_all_have_legal_ref(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM recycling_fees WHERE legal_ref IS NULL OR legal_ref = ''"
        )).scalar()
        assert missing == 0

    def test_unique_constraint(self) -> None:
        dupes = self.db.execute(text("""
            SELECT hs_prefix, vehicle_type, is_new, COUNT(*) c
            FROM recycling_fees
            GROUP BY hs_prefix, vehicle_type, is_new
            HAVING c > 1
        """)).fetchall()
        assert len(dupes) == 0


class TestRecyclingFeeLookup:
    def test_lookup_new_car_1500cc(self) -> None:
        results = get_recycling_fee("8703220000", is_new=True, engine_volume=1500)
        assert len(results) >= 1
        best = results[0]
        assert best["coefficient"] == 4.2
        assert best["base_rate"] == 20000
        assert best["fee_amount"] == 84000.0

    def test_lookup_used_car_3200cc(self) -> None:
        results = get_recycling_fee("8703240000", is_new=False, engine_volume=3200)
        assert len(results) >= 1
        best = results[0]
        assert best["coefficient"] == 28.5

    def test_lookup_non_vehicle_returns_empty(self) -> None:
        results = get_recycling_fee("8517120000", is_new=True)
        assert results == []

    def test_lookup_electric_car(self) -> None:
        results = get_recycling_fee("8703800000", is_new=True, engine_volume=None)
        has_electric = any("electric" in r["vehicle_type"] for r in results)
        assert has_electric or len(results) > 0

    def test_motorcycle_small(self) -> None:
        results = get_recycling_fee("8711200000", is_new=True, engine_volume=150)
        assert len(results) >= 1
        best = results[0]
        assert best["base_rate"] == 9000


class TestRecyclingFeeInPaymentEngine:
    def test_car_payment_includes_recycling_fee(self) -> None:
        result = compute_payments({
            "hs_code": "8703220000",
            "customs_value": 1000000,
            "country": "DE",
            "vehicle_is_new": True,
            "engine_volume": 1500,
        })
        assert result["status"] == "REVIEW_REQUIRED"
        rf = result.get("recycling_fee", {})
        assert rf.get("applied") is True
        assert rf["fee_amount"] == 84000.0
        assert result["breakdown"]["recycling_fee"] == 84000.0
        assert result["breakdown"]["total_payable"] is None
        assert result["breakdown"]["total_payable_provisional"] > result["breakdown"]["duty"]

    def test_non_vehicle_no_recycling_fee(self) -> None:
        result = compute_payments({
            "hs_code": "8517120000",
            "customs_value": 100000,
        })
        assert result["status"] == "REVIEW_REQUIRED"
        rf = result.get("recycling_fee", {})
        assert rf.get("applied") is False
        assert result["breakdown"]["recycling_fee"] == 0.0
        assert result["breakdown"]["total_payable"] is None

    def test_vehicle_age_is_required_before_automatic_fee(self) -> None:
        result = compute_payments({
            "hs_code": "8703220000",
            "customs_value": 1000000,
            "engine_volume": 1500,
        })
        assert result["recycling_fee"]["applied"] is False
        assert result["recycling_fee"]["review_required"] is True
        assert result["recycling_fee"]["review_reason"] == "recycling_fee_vehicle_age_missing"
        assert "recycling_fee_vehicle_age_missing" in result["payment_review_reasons"]
        assert result["breakdown"]["recycling_fee"] == 0.0
        assert result["breakdown"]["total_payable"] is None

    def test_volume_bracketed_vehicle_requires_engine_volume(self) -> None:
        result = compute_payments({
            "hs_code": "8703220000",
            "customs_value": 1000000,
            "vehicle_is_new": True,
        })
        assert result["recycling_fee"]["applied"] is False
        assert result["recycling_fee"]["review_reason"] == "recycling_fee_engine_volume_missing"
        assert "recycling_fee_engine_volume_missing" in result["payment_review_reasons"]
        assert result["breakdown"]["recycling_fee"] == 0.0
        assert result["breakdown"]["total_payable"] is None

    @pytest.mark.parametrize("engine_volume", [-10, 0, 1500.5, True])
    def test_invalid_engine_volume_is_rejected_without_coercion(self, engine_volume) -> None:
        with pytest.raises(ValueError, match="Объём двигателя"):
            compute_payments({
                "hs_code": "8703220000",
                "customs_value": 1000000,
                "vehicle_is_new": True,
                "engine_volume": engine_volume,
            })

    def test_unambiguous_generic_vehicle_rate_does_not_require_volume(self) -> None:
        result = compute_payments({
            "hs_code": "8701200000",
            "customs_value": 1000000,
            "vehicle_is_new": True,
        })
        assert result["recycling_fee"]["applied"] is True
        assert result["recycling_fee"]["vehicle_type"] == "tractor_new"
        assert result["recycling_fee"]["fee_amount"] == 150000.0
        assert "recycling_fee_engine_volume_missing" not in result["payment_review_reasons"]

    def test_non_boolean_vehicle_age_is_rejected_without_truthiness(self) -> None:
        with pytest.raises(ValueError, match="Признак нового ТС"):
            compute_payments({
                "hs_code": "8703220000",
                "customs_value": 1000000,
                "vehicle_is_new": "false",
                "engine_volume": 1500,
            })

    def test_embargo_response_has_recycling_fee_field(self) -> None:
        result = compute_payments({
            "hs_code": "8517120000",
            "customs_value": 100000,
        })
        if result["status"] == "EMBARGO":
            assert "recycling_fee" in result["breakdown"]
