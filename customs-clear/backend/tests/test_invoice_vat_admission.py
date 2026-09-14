"""Fail-closed boundary for model-derived VAT in the legacy invoice consumer."""

from __future__ import annotations

from contextlib import AbstractContextManager
from types import SimpleNamespace

import pytest

from app.models.core import HsRate
from app.models.tnved import NonTariffMeasure
from app.services import invoice_analyzer as analyzer
from app.services import payment_profile_builder
from app.services.currency_sync import CurrencyService


CODE = "8501100000"


class _Query:
    def __init__(self, result):
        self.result = result

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.result

    def all(self):
        return [] if self.result is None else [self.result]


class _Session(AbstractContextManager):
    def __init__(self, rate):
        self.rate = rate

    def __exit__(self, *_args):
        return None

    def query(self, entity):
        if entity is HsRate:
            return _Query(self.rate)
        if entity is NonTariffMeasure:
            return _Query(None)
        raise AssertionError(f"unexpected query: {entity!r}")


@pytest.fixture
def isolated_legacy_invoice(monkeypatch):
    rate = SimpleNamespace(
        hs_code=CODE,
        hs_prefix=CODE,
        duty_rate="10%",
        vat_import_rate=22.0,
        vat_rule_basis="synthetic reviewed fixture",
        excise_type="none",
        excise_value=0.0,
        excise_basis="",
        valid_from="2026-01-01",
    )
    monkeypatch.setattr(analyzer, "SessionLocal", lambda: _Session(rate))
    monkeypatch.setattr(analyzer, "_resolve_existing_hs10_with_session", lambda *_: (CODE, "exact"))
    monkeypatch.setattr(analyzer, "_best_hs_rate", lambda *_: rate)
    monkeypatch.setattr(analyzer.InvoiceAnalyzer, "check_geopolitical_risks", lambda *_: {})
    monkeypatch.setattr(analyzer, "resolve_vat_rate_for_hs", lambda *_: (22.0, "synthetic reviewed fixture"))
    monkeypatch.setattr(analyzer, "apply_compliance_resolution_to_enrichment", lambda *_: None)
    monkeypatch.setattr(CurrencyService, "get_eur_rate", lambda: 100.0)
    monkeypatch.setattr(
        payment_profile_builder,
        "build_full_payment_profile",
        lambda **_: SimpleNamespace(model_dump=lambda: {"status": "fixture"}),
    )
    return {"customs_value": 1000.0, "country_origin": "CN"}


def test_no_override_keeps_existing_legacy_output_shape(isolated_legacy_invoice):
    result = analyzer.enrich_with_customs_data(CODE, isolated_legacy_invoice)

    assert result["vat_import_rate"] == 22.0
    assert result["vat_amount"] == 242.0
    assert result["total_tax_pay"] == 342.0
    assert "vat_override_review" not in result


@pytest.mark.parametrize("candidate", [10, 10.0, "10", 22, 22.0])
def test_unadmitted_vat_candidate_never_changes_legacy_totals(isolated_legacy_invoice, candidate):
    result = analyzer.enrich_with_customs_data(
        CODE,
        isolated_legacy_invoice,
        vat_import_override=candidate,
    )

    assert result["vat_import_rate"] == 22.0
    assert result["vat_amount"] == 242.0
    assert result["total_tax_pay"] == 342.0
    assert result["vat_override_review"] == {
        "source_kind": "caller_supplied_diagnostic",
        "candidate_rate": float(candidate),
        "status": "REVIEW_REQUIRED",
        "applied": False,
        "reason": (
            "Диагностическая ставка НДС не применена: отсутствует отдельное "
            "source-bound подтверждение применимости."
        ),
    }
    assert result["non_tariff"] == []


@pytest.mark.parametrize("candidate", [True, "reduced", 0, 20, 23])
def test_invalid_vat_candidate_is_rejected_without_affecting_totals(isolated_legacy_invoice, candidate):
    result = analyzer.enrich_with_customs_data(
        CODE,
        isolated_legacy_invoice,
        vat_import_override=candidate,
    )

    assert result["vat_import_rate"] == 22.0
    assert result["vat_amount"] == 242.0
    assert result["total_tax_pay"] == 342.0
    assert result["vat_override_review"]["candidate_rate"] is None
    assert result["vat_override_review"]["status"] == "INVALID"
    assert result["vat_override_review"]["applied"] is False
