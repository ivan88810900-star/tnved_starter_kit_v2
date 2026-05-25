"""Product-facing Smart Payments quote: structured breakdown with explicit statuses."""

from __future__ import annotations

import re
from typing import Any

from ..db import SessionLocal
from ..models.tnved import SpecialDuty
from ..schemas.payment_quote import (
    PaymentQuoteAssumption,
    PaymentQuoteLineItem,
    PaymentQuoteResponse,
    PaymentQuoteWarning,
    PaymentLineStatus,
)
from .exchange_rates import get_rates_map
from .payment_engine_compat import compute_payments


def _digits_hs(code: str) -> str:
    return re.sub(r"\D", "", (code or ""))[:10]


def _special_duty_prefixes(hs_code: str) -> list[str]:
    d = _digits_hs(hs_code)
    if not d:
        return []
    out: list[str] = []
    for length in (10, 8, 6, 4):
        if len(d) >= length:
            out.append(d[:length])
    seen: set[str] = set()
    return [p for p in out if not (p in seen or seen.add(p))]


def _special_duties_configured_for_hs(hs_code: str) -> bool:
    prefixes = _special_duty_prefixes(hs_code)
    if not prefixes:
        return False
    with SessionLocal() as db:
        count = (
            db.query(SpecialDuty.id)
            .filter(SpecialDuty.hs_code_prefix.in_(prefixes))
            .limit(1)
            .count()
        )
    return count > 0


def _resolve_excise_status(
    *,
    raw: dict[str, Any],
    user_excise: float | None,
) -> tuple[PaymentLineStatus, float | None, str]:
    breakdown = raw.get("breakdown") or {}
    auto = raw.get("auto_detected") or {}
    dq = raw.get("data_quality") or {}
    excise_type = str(auto.get("excise_type") or "none").strip().lower()
    amount = breakdown.get("excise")
    reason = str(breakdown.get("excise_reason") or "")

    if user_excise is not None:
        return "manual_override", float(amount) if amount is not None else float(user_excise), reason

    if excise_type in {"percent", "fixed"}:
        return "applied", float(amount or 0.0), reason

    if excise_type == "none":
        if int(dq.get("match_length") or 0) > 0:
            return "not_applicable", 0.0, reason or "Акциз не предусмотрен для кода в локальной базе hs_rates."
        return "unknown", None, "Ставка акциза не определена: код не найден в локальной базе hs_rates."

    if int(dq.get("match_length") or 0) == 0:
        return "unknown", None, "Применимость акциза не определена — нет данных по коду в локальной базе."

    return "not_applicable", 0.0, reason or "Акциз не применяется."


def _resolve_antidumping_line(
    *,
    raw: dict[str, Any],
) -> PaymentQuoteLineItem:
    breakdown = raw.get("breakdown") or {}
    auto = raw.get("auto_detected") or {}
    dq = raw.get("data_quality") or {}
    ad_type = str(auto.get("antidumping_type") or "none").strip().lower()
    ad_status = str(dq.get("antidumping_status") or breakdown.get("antidumping_status") or "n/a")
    amount = float(breakdown.get("antidumping") or 0.0)
    reason = str(breakdown.get("antidumping_reason") or "")

    if ad_status == "manual_review":
        return PaymentQuoteLineItem(
            code="antidumping",
            label="Антидемпинговая пошлина",
            amount_rub=None,
            status="manual_review_required",
            reason=reason,
            source="hs_rates / меры торговой защиты ЕАЭС",
            rate_label=str(auto.get("antidumping_value") or "") or None,
        )

    if ad_type in {"percent", "fixed"} and ad_status == "applied":
        return PaymentQuoteLineItem(
            code="antidumping",
            label="Антидемпинговая пошлина",
            amount_rub=amount,
            status="applied",
            reason=reason,
            source="hs_rates / меры торговой защиты ЕАЭС",
            rate_label=f"{auto.get('antidumping_value')}%" if ad_type == "percent" else str(auto.get("antidumping_value")),
        )

    if ad_type == "none" and int(dq.get("match_length") or 0) > 0:
        return PaymentQuoteLineItem(
            code="antidumping",
            label="Антидемпинговая пошлина",
            amount_rub=0.0,
            status="not_applicable",
            reason=reason or "Антидемпинговая мера не указана для кода в локальной базе.",
            source="hs_rates",
        )

    if ad_type in {"percent", "fixed"}:
        return PaymentQuoteLineItem(
            code="antidumping",
            label="Антидемпинговая пошлина",
            amount_rub=0.0,
            status="not_applicable",
            reason=reason or "Антидемпинг не применяется для указанной страны.",
            source="hs_rates",
        )

    return PaymentQuoteLineItem(
        code="antidumping",
        label="Антидемпинговая пошлина",
        amount_rub=None,
        status="unknown",
        reason="Применимость антидемпинговой пошлины не определена — недостаточно данных в локальной базе.",
        source="hs_rates",
    )


def _resolve_special_duty_line(
    *,
    raw: dict[str, Any],
    country: str | None,
    hs_code: str,
) -> PaymentQuoteLineItem:
    breakdown = raw.get("breakdown") or {}
    amount = float(breakdown.get("special_duties_amount") or 0.0)
    details = list(raw.get("special_duties") or [])
    configured = _special_duties_configured_for_hs(hs_code)

    if amount > 0 and details:
        acts = ", ".join({str(d.get("regulatory_act") or "").strip() for d in details if d.get("regulatory_act")})
        return PaymentQuoteLineItem(
            code="special_duty",
            label="Специальные / защитные / компенсационные пошлины",
            amount_rub=amount,
            status="applied",
            reason=acts or "Спецпошлины по стране происхождения из таблицы special_duties.",
            source="special_duties",
        )

    if configured and not country:
        return PaymentQuoteLineItem(
            code="special_duty",
            label="Специальные / защитные / компенсационные пошлины",
            amount_rub=None,
            status="manual_review_required",
            reason="Для кода есть записи special_duties; укажите страну происхождения для проверки применимости.",
            source="special_duties",
        )

    if configured and country and amount == 0:
        return PaymentQuoteLineItem(
            code="special_duty",
            label="Специальные / защитные / компенсационные пошлины",
            amount_rub=0.0,
            status="not_applicable",
            reason=f"Для страны {country} спецпошлины по коду не найдены в локальной базе.",
            source="special_duties",
        )

    if not configured:
        return PaymentQuoteLineItem(
            code="special_duty",
            label="Специальные / защитные / компенсационные пошлины",
            amount_rub=None,
            status="not_configured",
            reason="Локальная база special_duties не содержит данных по этому коду; требуется отдельная проверка.",
            source="special_duties",
        )

    return PaymentQuoteLineItem(
        code="special_duty",
        label="Специальные / защитные / компенсационные пошлины",
        amount_rub=0.0,
        status="not_applicable",
        reason="Спецпошлины не применяются.",
        source="special_duties",
    )


def _build_warnings(line_items: list[PaymentQuoteLineItem], raw: dict[str, Any]) -> list[PaymentQuoteWarning]:
    warnings: list[PaymentQuoteWarning] = []
    dq = raw.get("data_quality") or {}

    confidence = str(dq.get("confidence") or "")
    if confidence in {"low", "none"}:
        warnings.append(
            PaymentQuoteWarning(
                code="hs_match_low_confidence",
                message="Ставки по коду определены по короткому префиксу или не найдены — проверьте код и актуальность данных.",
                severity="warning",
            )
        )

    for item in line_items:
        if item.status == "manual_review_required":
            warnings.append(
                PaymentQuoteWarning(
                    code=f"{item.code}_manual_review",
                    message=item.reason or f"Строка «{item.label}» требует ручной проверки.",
                    severity="warning",
                )
            )
        elif item.status in {"unknown", "not_configured"}:
            warnings.append(
                PaymentQuoteWarning(
                    code=f"{item.code}_{item.status}",
                    message=item.reason or f"Строка «{item.label}»: данные неполные.",
                    severity="warning",
                )
            )

    if raw.get("status") == "EMBARGO":
        geo = raw.get("geo") or {}
        warnings.append(
            PaymentQuoteWarning(
                code="embargo",
                message=str(raw.get("message") or geo.get("document_basis") or "Ввоз запрещён по геополитическим ограничениям."),
                severity="error",
            )
        )
    return warnings


def _build_assumptions(payload: dict[str, Any], raw: dict[str, Any]) -> list[PaymentQuoteAssumption]:
    assumptions: list[PaymentQuoteAssumption] = []
    invoice_currency = str(payload.get("invoice_currency") or "RUB").upper()
    customs_value = float(raw.get("customs_value") or payload.get("customs_value") or 0.0)
    freight = float(raw.get("freight") or payload.get("freight") or 0.0)
    insurance = raw.get("insurance")
    country = raw.get("country") or payload.get("country")

    assumptions.append(
        PaymentQuoteAssumption(
            key="customs_value_rub",
            label="Таможенная стоимость",
            value=f"{customs_value:,.2f} RUB".replace(",", " "),
        )
    )
    if invoice_currency != "RUB":
        assumptions.append(
            PaymentQuoteAssumption(
                key="invoice_currency",
                label="Валюта инвойса",
                value=invoice_currency,
            )
        )
    if freight:
        assumptions.append(
            PaymentQuoteAssumption(key="freight", label="Фрахт", value=f"{freight:,.2f} RUB".replace(",", " "))
        )
    if insurance is not None:
        assumptions.append(
            PaymentQuoteAssumption(
                key="insurance",
                label="Страховка",
                value=f"{float(insurance):,.2f} RUB".replace(",", " "),
            )
        )
    assumptions.append(
        PaymentQuoteAssumption(
            key="country",
            label="Страна происхождения",
            value=str(country).upper() if country else "не указана",
        )
    )
    qty = payload.get("quantity")
    if qty is not None:
        assumptions.append(
            PaymentQuoteAssumption(key="quantity", label="Количество", value=str(qty))
        )
    weight = payload.get("net_weight_kg")
    if weight is not None:
        assumptions.append(
            PaymentQuoteAssumption(key="net_weight_kg", label="Вес нетто", value=f"{weight} кг")
        )
    return assumptions


def build_payment_quote(payload: dict[str, Any]) -> PaymentQuoteResponse:
    """Собирает product-facing quote поверх compute_payments без изменения расчётной семантики."""
    hs_code = str(payload.get("hs_code") or "").strip()
    description = (payload.get("description") or "").strip() or None
    invoice_currency = str(payload.get("invoice_currency") or "RUB").upper().strip()
    user_excise = float(payload["excise"]) if payload.get("excise") is not None else None

    rates = get_rates_map()
    if invoice_currency not in rates:
        raise ValueError(f"Неизвестная валюта инвойса: {invoice_currency}")

    calc_payload = dict(payload)
    invoice_fx = float(rates.get(invoice_currency) or 1.0)
    calc_payload["customs_value"] = float(payload.get("customs_value") or 0.0) * invoice_fx
    calc_payload["_fx_rates"] = rates
    calc_payload["invoice_currency"] = invoice_currency

    raw = compute_payments(calc_payload)
    breakdown = raw.get("breakdown") or {}
    country = raw.get("country") or (str(payload.get("country") or "").upper().strip() or None)
    dq = raw.get("data_quality") or {}

    if raw.get("status") == "EMBARGO":
        geo = raw.get("geo") or {}
        line_items = [
            PaymentQuoteLineItem(
                code="duty",
                label="Ввозная пошлина",
                amount_rub=0.0,
                status="embargo",
                reason="Расчёт заблокирован: эмбарго.",
                source="geo_special_duties",
            ),
            PaymentQuoteLineItem(
                code="vat",
                label="НДС",
                amount_rub=0.0,
                status="embargo",
                reason="Расчёт заблокирован: эмбарго.",
                source="geo_special_duties",
            ),
            PaymentQuoteLineItem(
                code="customs_fee",
                label="Таможенный сбор",
                amount_rub=0.0,
                status="embargo",
                reason="Расчёт заблокирован: эмбарго.",
                source="geo_special_duties",
            ),
        ]
        warnings = _build_warnings(line_items, raw)
        return PaymentQuoteResponse(
            status="EMBARGO",
            hs_code=hs_code,
            country=country,
            description=description,
            customs_value_rub=float(raw.get("customs_value") or 0.0),
            invoice_currency=invoice_currency,
            line_items=line_items,
            total_payable_rub=None,
            total_partial_rub=0.0,
            warnings=warnings,
            assumptions=_build_assumptions(payload, raw),
            data_quality=dq,
            sources=list(raw.get("sources") or []),
            legal_basis=raw.get("legal_basis"),
            geo=geo,
        )

    duty_status: PaymentLineStatus = "applied"
    duty_reason = str((raw.get("legal_basis") or {}).get("duty") or "")
    if int(dq.get("match_length") or 0) == 0:
        duty_status = "unknown"
        duty_reason = duty_reason or "Ставка пошлины не найдена в локальной базе; применена ставка 0% для расчёта."

    excise_status, excise_amount, excise_reason = _resolve_excise_status(raw=raw, user_excise=user_excise)

    line_items: list[PaymentQuoteLineItem] = [
        PaymentQuoteLineItem(
            code="duty",
            label="Ввозная пошлина",
            amount_rub=float(breakdown.get("duty") or 0.0),
            status=duty_status,
            reason=duty_reason,
            source="hs_duty_rules / hs_rates (ЕТТ ЕАЭС)",
            rate_label=f"{breakdown.get('duty_rate')}%" if breakdown.get("duty_rate") is not None else None,
        ),
        PaymentQuoteLineItem(
            code="vat",
            label="НДС",
            amount_rub=float(breakdown.get("vat") or 0.0),
            status="applied",
            reason=str(breakdown.get("vat_reason") or ""),
            source="hs_rates / vat_preferences (НК РФ)",
            rate_label=f"{breakdown.get('vat_rate')}%",
        ),
        PaymentQuoteLineItem(
            code="customs_fee",
            label="Таможенный сбор",
            amount_rub=float(breakdown.get("customs_fee") or 0.0),
            status="applied",
            reason=str((raw.get("legal_basis") or {}).get("customs_fee") or "Шкала таможенных сборов РФ 2026."),
            source="customs_fees",
        ),
        PaymentQuoteLineItem(
            code="excise",
            label="Акциз",
            amount_rub=excise_amount,
            status=excise_status,
            reason=excise_reason,
            source="hs_rates (НК РФ ст. 193)",
        ),
        _resolve_antidumping_line(raw=raw),
        _resolve_special_duty_line(raw=raw, country=country, hs_code=hs_code),
    ]

    warnings = _build_warnings(line_items, raw)
    assumptions = _build_assumptions(payload, raw)

    uncertain_statuses = {"manual_review_required", "unknown", "not_configured", "embargo"}
    blocking_codes = {"excise", "antidumping", "special_duty"}
    has_uncertain = any(
        item.status in uncertain_statuses and item.code in blocking_codes for item in line_items
    )
    partial_total = round(
        sum(item.amount_rub for item in line_items if item.amount_rub is not None),
        2,
    )
    engine_total = float(breakdown.get("total_payable") or 0.0)
    total_payable: float | None = None if has_uncertain else engine_total

    return PaymentQuoteResponse(
        status=str(raw.get("status") or "OK"),
        hs_code=hs_code,
        country=country,
        description=description,
        customs_value_rub=float(raw.get("customs_value") or 0.0),
        invoice_currency=invoice_currency,
        line_items=line_items,
        total_payable_rub=total_payable,
        total_partial_rub=partial_total,
        warnings=warnings,
        assumptions=assumptions,
        data_quality=dq,
        sources=list(raw.get("sources") or []),
        legal_basis=raw.get("legal_basis"),
        geo=raw.get("geo"),
    )