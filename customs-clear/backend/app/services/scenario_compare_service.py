"""
Расширенное сравнение сценариев: страны, коды, процедуры + РОП (#146).
"""

from __future__ import annotations

from typing import Any

from ..db import SessionLocal
from .exchange_rates import get_rates_map
from .payment_engine_compat import compute_payments
from .rop_calculator import calculate_rop


def compare_scenarios_extended(payload: dict[str, Any]) -> dict[str, Any]:
    base = payload.get("base") or {}
    scenarios = payload.get("scenarios") or []
    if len(scenarios) < 2:
        raise ValueError("Укажите минимум 2 сценария")

    hs_base = str(base.get("hs_code") or "").strip()
    customs_value = float(base.get("customs_value") or 0)
    currency = str(base.get("currency") or base.get("invoice_currency") or "USD").upper()
    gross = base.get("weight_gross_kg")
    net = base.get("weight_net_kg")

    rates = get_rates_map()
    fx = float(rates.get(currency) or 1.0)
    cv_rub = customs_value * fx

    out: list[dict[str, Any]] = []
    with SessionLocal() as db:
        for i, sc in enumerate(scenarios):
            if not isinstance(sc, dict):
                continue
            name = str(sc.get("name") or sc.get("label") or f"Сценарий {i + 1}")
            hs = str(sc.get("hs_code") or hs_base).strip()
            country = str(sc.get("country_of_origin") or sc.get("country") or base.get("country") or "").strip().upper()
            procedure = str(sc.get("procedure_code") or "").strip().upper()

            pay_in: dict[str, Any] = {
                "hs_code": hs,
                "customs_value": cv_rub,
                "invoice_currency": "RUB",
                "country": country or None,
            }
            if net is not None:
                pay_in["net_weight_kg"] = float(net)
            if gross is not None:
                pay_in["gross_weight_kg"] = float(gross)

            res = compute_payments(pay_in)
            bd = res.get("breakdown") or {}
            rop = {"total_rop_rub": 0.0}
            if hs and gross is not None and net is not None:
                rop = calculate_rop(db, hs, float(gross), float(net))

            total = float(bd.get("total_payable") or 0) + float(rop.get("total_rop_rub") or 0)
            out.append(
                {
                    "name": name,
                    "hs_code": hs,
                    "country_of_origin": country or None,
                    "procedure_code": procedure or None,
                    "duty": bd.get("duty", 0),
                    "vat": bd.get("vat", 0),
                    "fee": bd.get("customs_fee", 0),
                    "excise": bd.get("excise", 0),
                    "recycling_fee": (res.get("recycling_fee") or {}).get("fee_amount", 0),
                    "rop": rop.get("total_rop_rub", 0),
                    "total": round(total, 2),
                    "preference": res.get("tariff_preference"),
                    "payments_status": res.get("status"),
                }
            )

    if not out:
        raise ValueError("Нет валидных сценариев")

    best = min(out, key=lambda x: float(x["total"]))
    worst = max(out, key=lambda x: float(x["total"]))
    savings = round(float(worst["total"]) - float(best["total"]), 2)

    return {
        "status": "OK",
        "base": {
            "hs_code": hs_base,
            "customs_value": customs_value,
            "currency": currency,
            "customs_value_rub": round(cv_rub, 2),
            "weight_gross_kg": gross,
            "weight_net_kg": net,
        },
        "scenarios": out,
        "best_scenario": best["name"],
        "savings_vs_worst": savings,
    }
