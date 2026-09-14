"""Pending estimates must remain pending across comparison/profile boundaries."""

from contextlib import nullcontext

import pytest

from app.services import payment_engine, payment_profile_builder, scenario_compare_service


def _payment(*, status="OK", provisional=False, duty=100, vat=242, total=342):
    return {
        "status": status,
        "amounts_provisional": provisional,
        "tariff_preference": {
            "applied": False,
            "status": "needs_review" if provisional else "not_applied",
            "reason": "Не подтверждена применимость преференции." if provisional else "",
        },
        "breakdown": {
            "duty": duty, "vat": vat, "excise": 0, "antidumping": 0,
            "customs_fee": 0, "total_payable": total,
            "duty_rate": 10, "vat_rate": 22,
        },
    }


def _isolated_profiles(monkeypatch):
    monkeypatch.setattr(payment_profile_builder, "SessionLocal", lambda: nullcontext(None))
    monkeypatch.setattr(
        payment_profile_builder, "build_compliance_document_items", lambda **_: {"documents": []}
    )


@pytest.mark.parametrize("pending_index", [0, 1])
def test_extended_comparison_does_not_rank_pending_estimates(monkeypatch, pending_index):
    results = [_payment(total=300), _payment(total=400)]
    results[pending_index] = _payment(status="REVIEW_REQUIRED", provisional=True, total=250)
    iterator = iter(results)
    monkeypatch.setattr(scenario_compare_service, "SessionLocal", lambda: nullcontext(None))
    monkeypatch.setattr(scenario_compare_service, "get_rates_map", lambda: {"RUB": 1})
    monkeypatch.setattr(scenario_compare_service, "compute_payments", lambda _: next(iterator))
    result = scenario_compare_service.compare_scenarios_extended({
        "base": {"hs_code": "8517130000", "customs_value": 1000, "currency": "RUB"},
        "scenarios": [{"name": "A"}, {"name": "B"}],
    })
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["comparison_complete"] is False
    assert result["amounts_provisional"] is True
    assert result["best_scenario"] is None
    assert result["savings_vs_worst"] is None
    assert result["scenarios"][pending_index]["total"] == 250
    assert result["scenarios"][pending_index]["preference"]["applied"] is False


def test_extended_complete_comparison_keeps_ranking_and_rop(monkeypatch):
    iterator = iter([_payment(total=300), _payment(total=400)])
    monkeypatch.setattr(scenario_compare_service, "SessionLocal", lambda: nullcontext(None))
    monkeypatch.setattr(scenario_compare_service, "get_rates_map", lambda: {"RUB": 1})
    monkeypatch.setattr(scenario_compare_service, "compute_payments", lambda _: next(iterator))
    monkeypatch.setattr(scenario_compare_service, "calculate_rop", lambda *_: {"total_rop_rub": 17})
    result = scenario_compare_service.compare_scenarios_extended({
        "base": {"hs_code": "8517130000", "customs_value": 1000, "currency": "RUB",
                 "weight_gross_kg": 5, "weight_net_kg": 4},
        "scenarios": [{"name": "A"}, {"name": "B"}],
    })
    assert result["status"] == "OK"
    assert result["comparison_complete"] is True
    assert result["amounts_provisional"] is False
    assert result["best_scenario"] == "A"
    assert result["savings_vs_worst"] == 100
    assert result["scenarios"][0]["total"] == 317


def test_extended_blocked_scenario_cannot_be_a_zero_cost_winner(monkeypatch):
    iterator = iter([_payment(status="EMBARGO", total=0), _payment(total=400)])
    monkeypatch.setattr(scenario_compare_service, "SessionLocal", lambda: nullcontext(None))
    monkeypatch.setattr(scenario_compare_service, "get_rates_map", lambda: {"RUB": 1})
    monkeypatch.setattr(scenario_compare_service, "compute_payments", lambda _: next(iterator))
    result = scenario_compare_service.compare_scenarios_extended({
        "base": {"hs_code": "8517130000", "customs_value": 1000, "currency": "RUB"},
        "scenarios": [{"name": "Blocked"}, {"name": "Available"}],
    })
    assert result["comparison_complete"] is False
    assert result["best_scenario"] is None
    assert result["savings_vs_worst"] is None
    assert result["scenarios"][0]["payments_status"] == "EMBARGO"


def test_profile_comparison_reuses_exact_manual_rate_result(monkeypatch):
    _isolated_profiles(monkeypatch)
    calls = []

    def compute(payload):
        calls.append(payload)
        return _payment(duty=payload["duty_rate"] * 10, vat=payload["vat_rate"] * 10,
                        total=(payload["duty_rate"] + payload["vat_rate"]) * 10)

    monkeypatch.setattr(payment_engine, "compute_payments", compute)
    monkeypatch.setattr(payment_profile_builder, "compare_payment_scenarios",
                        payment_engine.compare_payment_scenarios)
    monkeypatch.setattr(payment_profile_builder, "compute_payments",
                        lambda _: pytest.fail("Profile must not recalculate or lose manual rates"))
    result = payment_profile_builder.build_compare_payment_profiles(payload={
        "shared": {"customs_value": 1000, "country": "BR", "net_weight_kg": 4,
                   "extra_quantity": 3, "apply_reduced_vat": True},
        "scenarios": [
            {"hs_code": "8517130000", "duty_rate": 0, "vat_rate": 10},
            {"hs_code": "8517130000", "duty_rate": 5, "vat_rate": 22},
        ],
    })
    assert len(calls) == 2
    assert calls[0]["duty_rate"] == 0
    assert calls[0]["net_weight_kg"] == 4
    assert calls[0]["extra_quantity"] == 3
    assert calls[0]["apply_reduced_vat"] is True
    assert result.scenarios[0].profile.breakdown.base_duty == 0
    assert result.scenarios[0].profile.breakdown.vat == 100
    assert result.scenarios[1].profile.breakdown.base_duty == 50
    assert result.scenarios[1].delta_total_vs_first_rub == 170
    assert result.comparison_complete is True


def test_profile_comparison_keeps_provisional_contract_and_nulls_deltas(monkeypatch):
    _isolated_profiles(monkeypatch)
    iterator = iter([_payment(), _payment(status="REVIEW_REQUIRED", provisional=True)])
    monkeypatch.setattr(payment_engine, "compute_payments", lambda _: next(iterator))
    monkeypatch.setattr(payment_profile_builder, "compare_payment_scenarios",
                        payment_engine.compare_payment_scenarios)
    result = payment_profile_builder.build_compare_payment_profiles(payload={
        "shared": {"customs_value": 1000},
        "scenarios": [{"hs_code": "8517130000"}, {"hs_code": "8517130000", "country": "BR"}],
    }).model_dump()
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["amounts_provisional"] is True
    assert result["comparison_complete"] is False
    assert all(row["delta_total_vs_first_rub"] is None for row in result["scenarios"])
    profile = result["scenarios"][1]["profile"]
    assert profile["amounts_provisional"] is True
    assert profile["tariff_preference"]["status"] == "needs_review"
    assert profile["breakdown"]["total_payable"] == 342


def test_profile_does_not_invent_verification_for_legacy_result(monkeypatch):
    _isolated_profiles(monkeypatch)
    raw = _payment()
    raw.pop("amounts_provisional")
    raw.pop("tariff_preference")
    monkeypatch.setattr(payment_profile_builder, "compute_payments", lambda _: raw)
    profile = payment_profile_builder.build_full_payment_profile(
        payload={}, hs_code="8517130000", country=None
    )
    assert profile.amounts_provisional is None
    assert profile.tariff_preference is None


def test_profile_rejects_missing_original_instead_of_guessing_missing_amounts(monkeypatch):
    monkeypatch.setattr(payment_profile_builder, "compare_payment_scenarios", lambda _: {
        "status": "OK", "shared_economic": {},
        "scenarios": [{"hs_code": "8517130000", "duty": 100, "total_payable": 342}],
    })
    with pytest.raises(ValueError, match="исходный расчёт"):
        payment_profile_builder.build_compare_payment_profiles(payload={})


def test_generic_missing_rate_reason_is_preserved_without_a_preference(monkeypatch):
    _isolated_profiles(monkeypatch)
    reason = "Ставка пошлины не подтверждена источником."
    pending = _payment(status="REVIEW_REQUIRED", provisional=True)
    pending["tariff_preference"] = None
    pending["payment_review_reason"] = reason
    pending["payment_review_reasons"] = ["duty_source_missing"]
    monkeypatch.setattr(payment_profile_builder, "compute_payments", lambda _: pending)
    profile = payment_profile_builder.build_full_payment_profile(
        payload={}, hs_code="8517130000", country=None
    ).model_dump()
    assert profile["payment_review_reason"] == reason
    assert profile["payment_review_reasons"] == ["duty_source_missing"]
    assert profile["tariff_preference"] is None

    monkeypatch.setattr(scenario_compare_service, "SessionLocal", lambda: nullcontext(None))
    monkeypatch.setattr(scenario_compare_service, "get_rates_map", lambda: {"RUB": 1})
    monkeypatch.setattr(scenario_compare_service, "compute_payments", lambda _: pending)
    comparison = scenario_compare_service.compare_scenarios_extended({
        "base": {"hs_code": "8517130000", "customs_value": 1000, "currency": "RUB"},
        "scenarios": [{"name": "A"}, {"name": "B"}],
    })
    assert comparison["best_scenario"] is None
    assert comparison["scenarios"][0]["payment_review_reason"] == reason
    assert comparison["scenarios"][0]["payment_review_reasons"] == ["duty_source_missing"]
