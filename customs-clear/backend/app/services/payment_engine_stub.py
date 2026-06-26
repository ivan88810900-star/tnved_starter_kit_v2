"""Заглушка расчёта платежей, если модуль payment_engine недоступен (отсутствует файл и т.п.)."""

from __future__ import annotations

from typing import Any


def _round2(v: float) -> float:
    return round(float(v), 2)


def compute_payments(payload: dict[str, Any]) -> dict[str, Any]:
    hs_code = str(payload.get("hs_code") or "").strip()
    customs_value = float(payload.get("customs_value") or 0.0)
    freight = float(payload.get("freight") or 0.0)
    country = str(payload.get("country") or "").upper().strip() or None

    if customs_value <= 0:
        raise ValueError("Таможенная стоимость должна быть > 0")

    insurance = payload.get("insurance")
    if insurance is None:
        insurance = 0.0015 * (customs_value + freight)
    insurance = float(insurance)

    duty_rate = float(payload.get("duty_rate")) if payload.get("duty_rate") is not None else 0.0
    vat_rate = float(payload.get("vat_rate")) if payload.get("vat_rate") is not None else 22.0
    excise = float(payload.get("excise")) if payload.get("excise") is not None else 0.0

    duty = customs_value * duty_rate / 100.0
    antidumping = 0.0
    vat_base = customs_value + duty + excise + antidumping
    vat = vat_base * vat_rate / 100.0
    total = duty + excise + antidumping + vat

    return {
        "status": "MOCK",
        "hs_code": hs_code,
        "country": country,
        "customs_value": _round2(customs_value),
        "freight": _round2(freight),
        "insurance": _round2(insurance),
        "auto_detected": {
            "duty_rate": duty_rate,
            "vat_rate": vat_rate,
            "vat_rule": "none",
            "excise_type": "none",
            "excise_value": 0.0,
            "antidumping_type": "none",
            "antidumping_value": 0.0,
            "antidumping_condition": "",
            "antidumping_countries": "",
        },
        "breakdown": {
            "duty_rate": duty_rate,
            "duty": _round2(duty),
            "excise": _round2(excise),
            "excise_reason": "Заглушка: расчёт без базы ставок",
            "antidumping": _round2(antidumping),
            "antidumping_reason": "Не применяется",
            "antidumping_status": "n/a",
            "vat_rate": vat_rate,
            "vat_reason": "Заглушка: 22% или значение из запроса",
            "vat_base": _round2(vat_base),
            "vat": _round2(vat),
            "total_payable": _round2(total),
        },
        "legal_basis": {
            "vat": "MOCK: замените app/services/payment_engine.py полной версией",
            "duty": "MOCK: ставка из запроса или 0%",
            "antidumping": "Не применяется",
            "excise": "Заглушка",
        },
        "data_quality": {
            "confidence": "none",
            "matched_prefix": "",
            "match_length": 0,
            "source_code": None,
            "antidumping_status": "n/a",
        },
        "sources": [],
        "tnved_context": {},
    }


def compare_payment_scenarios(payload: dict[str, Any]) -> dict[str, Any]:
    shared = payload.get("shared") or {}
    scenarios = payload.get("scenarios") or []
    if len(scenarios) < 2:
        raise ValueError("Укажите минимум 2 сценария (разные коды ТН ВЭД)")
    if len(scenarios) > 8:
        raise ValueError("Не более 8 сценариев за один запрос")

    customs_value = float(shared.get("customs_value") or 0)
    if customs_value <= 0:
        raise ValueError("Общая таможенная стоимость (shared.customs_value) должна быть > 0")

    econ: dict[str, Any] = {
        "customs_value": customs_value,
        "freight": float(shared.get("freight") or 0.0),
    }
    if shared.get("insurance") is not None:
        econ["insurance"] = float(shared["insurance"])
    if (shared.get("country") or "").strip():
        econ["country"] = str(shared["country"]).strip().upper()
    if shared.get("quantity") is not None:
        econ["quantity"] = float(shared["quantity"])

    out_scenarios: list[dict[str, Any]] = []
    first_total: float | None = None

    for i, sc in enumerate(scenarios):
        if not isinstance(sc, dict):
            continue
        label = str(sc.get("label") or f"Вариант {i + 1}")
        hs = str(sc.get("hs_code") or "").strip()
        if not hs:
            raise ValueError(f"Сценарий «{label}»: не указан hs_code")
        merged = {**econ, "hs_code": hs}
        for opt in ("duty_rate", "vat_rate", "excise"):
            if sc.get(opt) is not None:
                merged[opt] = sc[opt]
        res = compute_payments(merged)
        total = float(res["breakdown"]["total_payable"])
        delta = None if first_total is None else _round2(total - first_total)
        if first_total is None:
            first_total = total
        tv = res.get("tnved_context") or {}
        out_scenarios.append(
            {
                "label": label,
                "hs_code": hs,
                "delta_total_vs_first_rub": delta,
                "total_payable": _round2(total),
                "duty": res["breakdown"]["duty"],
                "vat": res["breakdown"]["vat"],
                "excise": res["breakdown"]["excise"],
                "antidumping": res["breakdown"]["antidumping"],
                "duty_rate_applied": res["breakdown"]["duty_rate"],
                "vat_rate_applied": res["breakdown"]["vat_rate"],
                "data_quality": res.get("data_quality"),
                "tnved_title": (tv.get("title") or "")[:300] if isinstance(tv, dict) else "",
            }
        )

    return {
        "status": "MOCK",
        "shared_economic": econ,
        "scenarios": out_scenarios,
    }
