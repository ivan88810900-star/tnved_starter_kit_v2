"""Group HS header clarification — Issue group codes UX."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.normative_store import find_suggested_leaf_codes, is_leaf_hs_code


client = TestClient(app)


class TestIsLeafHsCode:
    def test_group_header_8703230000(self) -> None:
        assert is_leaf_hs_code("8703230000") is False

    def test_real_leaf_8703231100(self) -> None:
        assert is_leaf_hs_code("8703231100") is True

    def test_real_leaf_with_trailing_zeros_8471300000(self) -> None:
        assert is_leaf_hs_code("8471300000") is True

    def test_real_leaf_8517110000(self) -> None:
        assert is_leaf_hs_code("8517110000") is True

    def test_suggested_children_for_8703230000(self) -> None:
        suggested = find_suggested_leaf_codes("8703230000", limit=5)
        assert len(suggested) >= 1
        codes = {s["code"] for s in suggested}
        assert "8703231100" in codes
        assert "8703230000" not in codes


class TestCalculatorClarification:
    def test_group_header_returns_clarification(self) -> None:
        r = client.post(
            "/api/calculator/compute",
            json={
                "hs_code": "8703230000",
                "customs_value": 1_000_000,
                "country": "CN",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "CLARIFICATION_NEEDED"
        assert body["hs_code"] == "8703230000"
        assert len(body["suggested_codes"]) >= 1
        assert any(s["code"] == "8703231100" for s in body["suggested_codes"])
        hit = next(s for s in body["suggested_codes"] if s["code"] == "8703231100")
        assert "15" in hit["duty_rate"]

    def test_leaf_8703231100_computes_normally(self) -> None:
        r = client.post(
            "/api/calculator/compute",
            json={
                "hs_code": "8703231100",
                "customs_value": 1_000_000,
                "country": "CN",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "OK"
        assert body["data_quality"]["match_length"] == 10
        assert body["breakdown"]["total_payable"] > 0

    def test_leaf_8471300000_zero_duty(self) -> None:
        r = client.post(
            "/api/calculator/compute",
            json={
                "hs_code": "8471300000",
                "customs_value": 500_000,
                "country": "CN",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "OK"
        assert body["breakdown"]["duty_rate"] == 0.0

    def test_leaf_8517110000_zero_duty(self) -> None:
        r = client.post(
            "/api/calculator/compute",
            json={
                "hs_code": "8517110000",
                "customs_value": 300_000,
                "country": "CN",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "OK"
        assert body["breakdown"]["duty_rate"] == 0.0
