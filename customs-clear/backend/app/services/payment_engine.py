from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any

from ..db import SessionLocal
from ..models.tnved import Commodity, HsDutyRule, SpecialDuty, VatPreference
from .customs_fees import calculate_customs_fee
from .invoice_analyzer import _parse_duty_rate
from .normative_store import (
    find_geo_duty_override_row,
    find_geo_embargo_match,
    find_rate_for_hs,
    get_country_risk_by_iso,
    get_integrated_data_stats,
    get_recycling_fee,
    get_tariff_preference,
    get_tnved_context_for_hs,
)
from .compliance_resolver import pick_vat_preference_row
from .payment_revision_utils import (
    is_official_anti_dumping_row_marker,
    is_official_countervailing_row_marker,
    is_official_special_safeguard_row_marker,
    is_safe_official_anti_dumping_source_url,
)


@dataclass
class _FallbackDutyRule:
    commodity_code: str
    type: str
    ad_valorem_pct: float | None
    specific_amount: float | None
    specific_currency: str
    specific_uom: str


def _num(v: Any | None) -> float:
    """None-safe numeric cast for arithmetic."""
    return 0.0 if v is None else float(v)


def _sum_amounts(*parts: Any | None) -> float:
    return sum(_num(p) for p in parts)


def _round2(v: Any | None) -> float:
    return round(_num(v), 2)


# Confidence levels based on HS-prefix match length
_CONFIDENCE_MAP = {
    10: "high",
    8: "high",
    6: "medium",
    4: "low",
    0: "none",
}

_FALLBACK_FX_RATES: dict[str, float] = {
    "EUR": 100.0,
    "USD": 92.0,
    "RUB": 1.0,
}

SPECIAL_DUTIES_COUNTRY_WARNING = (
    "Антидемпинговые и иные специальные пошлины проверяются только при указании "
    "страны происхождения. Данные по мерам защиты рынка могут быть неполными — "
    "см. remedies.eaeunion.org"
)

TARIFF_PREFERENCE_REVIEW_REASON = (
    "В прежнем справочнике стран указано снижение пошлины, но право на него "
    "для этого товара и даты не подтверждено. Страна происхождения сама по себе "
    "не подтверждает преференцию. Предварительные суммы рассчитаны без снижения; "
    "проверьте действующий режим, товар, происхождение и условия поставки."
)

DUTY_SOURCE_MISSING_REASON = (
    "Ставка пошлины не найдена в локальных источниках и не задана вручную. "
    "Нулевое значение в предварительной арифметике не подтверждает нулевую ставку."
)
VAT_SOURCE_MISSING_REASON = (
    "Ставка НДС не найдена в локальных источниках и не задана вручную. "
    "Ставка по умолчанию использована только для предварительной арифметики."
)
SPECIAL_DUTY_REVIEW_REASON = (
    "Найдены кандидаты специальных, защитных или компенсационных пошлин, "
    "но их применимость не подтверждена по дате, стране, изготовителю, товару "
    "или единице специфической ставки. Неопределённые меры не включены "
    "в предварительную сумму; база НДС и итог требуют проверки."
)
SPECIAL_DUTY_LEGAL_REVIEW_REASON = (
    "Арифметика торговых пошлин предварительная: метки официального источника "
    "не подтверждают юридическое утверждение применимости к этой поставке. "
    "Суммы торговых пошлин, зависимого НДС и итог не подтверждены к уплате."
)
LEGACY_PAYMENT_AS_OF_UNSUPPORTED = (
    "Расчёт платежей по дате as_of пока недоступен: текущий справочник не "
    "подтверждает исторические версии всех ставок и сборов. Дата не будет "
    "заменена сегодняшней."
)


def _digits_hs(code: str) -> str:
    return re.sub(r"\D", "", (code or ""))[:10]


def _duty_rule_candidates(hs_code: str) -> list[tuple[str, int]]:
    """Кандидаты кодов для поиска hs_duty_rules с приоритетом точности."""
    d = _digits_hs(hs_code)
    if not d:
        return []
    out: list[tuple[str, int]] = []
    if len(d) >= 10:
        out.append((d[:10], 10))
    if len(d) >= 8:
        out.append((d[:8] + "00", 8))
    if len(d) >= 6:
        out.append((d[:6] + "0000", 6))
    if len(d) >= 4:
        out.append((d[:4] + "000000", 4))
    if len(d) < 10:
        out.append((d.ljust(10, "0"), len(d)))
    seen: set[str] = set()
    return [(code, mlen) for code, mlen in out if not (code in seen or seen.add(code))]


def _find_duty_rule_for_hs(hs_code: str) -> tuple[HsDutyRule | _FallbackDutyRule | None, int]:
    cands = _duty_rule_candidates(hs_code)
    if not cands:
        return None, 0
    by_code = {c: m for c, m in cands}

    # 1) Точное/префиксное совпадение в hs_duty_rules (10→8→6→4).
    with SessionLocal() as db:
        rows = db.query(HsDutyRule).filter(HsDutyRule.commodity_code.in_(list(by_code.keys()))).all()
        if rows:
            best = max(rows, key=lambda r: by_code.get(r.commodity_code, 0))
            return best, by_code.get(best.commodity_code, 0)

    # 2) fallback на hs_rates: find_rate_for_hs уже проверяет точное + префикс 10→8→6→4.
    rate, rate_match_len = find_rate_for_hs(hs_code)
    if not rate:
        return None, 0
    parsed = _parse_duty_rate(rate.duty_rate or "0")
    rule_type = "specific" if (parsed.get("specific_amount") is not None) else "ad_valorem"
    fallback = _FallbackDutyRule(
        commodity_code=str(rate.hs_code or rate.hs_prefix or _digits_hs(hs_code)),
        type=rule_type,
        ad_valorem_pct=(float(parsed.get("ad_valorem")) if parsed.get("ad_valorem") is not None else None),
        specific_amount=(float(parsed.get("specific_amount")) if parsed.get("specific_amount") is not None else None),
        specific_currency=str(parsed.get("specific_currency") or ""),
        specific_uom=str(parsed.get("specific_uom") or ""),
    )
    return fallback, rate_match_len


def _find_commodity_for_hs(hs_code: str) -> tuple[Commodity | None, int]:
    cands = _duty_rule_candidates(hs_code)
    if not cands:
        return None, 0
    by_code = {c: m for c, m in cands}
    with SessionLocal() as db:
        rows = db.query(Commodity).filter(Commodity.code.in_(list(by_code.keys()))).all()
        if not rows:
            return None, 0
        best = max(rows, key=lambda r: by_code.get(r.code, 0))
        return best, by_code.get(best.code, 0)


def _special_duty_prefix_candidates(hs_code: str) -> list[tuple[str, int]]:
    d = _digits_hs(hs_code)
    if not d:
        return []
    out: list[tuple[str, int]] = []
    if len(d) >= 10:
        out.append((d[:10], 10))
    if len(d) >= 8:
        out.append((d[:8], 8))
    if len(d) >= 6:
        out.append((d[:6], 6))
    if len(d) >= 4:
        out.append((d[:4], 4))
    seen: set[str] = set()
    return [(p, m) for p, m in out if not (p in seen or seen.add(p))]


def _resolve_special_duties(
    hs_code: str,
    country: str | None,
    customs_value: float,
    quantity: float,
    fx_rates: dict[str, float] | None,
    as_of: date | str | None = None,
) -> tuple[float, list[dict[str, Any]]]:
    """Keep unproved applicability separate from known local arithmetic.

    Legacy rows have no structured producer/product matcher, specific-rate unit
    or cumulative-measure identity. Neither free text nor generic quantity/FX
    inputs establish those missing facts. Such rows remain review candidates.
    """
    if as_of is None:
        requested_date = date.today()  # Existing no-date callers retain this default.
    elif type(as_of) is date:
        requested_date = as_of
    elif type(as_of) is str:
        requested_date = date.fromisoformat(as_of)
        if requested_date.isoformat() != as_of:
            raise ValueError("Дата проверки специальных пошлин должна иметь формат YYYY-MM-DD")
    else:
        raise ValueError("Дата проверки специальных пошлин должна быть календарной датой")
    cands = _special_duty_prefix_candidates(hs_code)
    if not cands:
        return 0.0, []
    by_prefix = {p: m for p, m in cands}
    country_norm = (country or "").strip().upper() or None

    with SessionLocal() as db:
        rows = db.query(SpecialDuty).filter(
            SpecialDuty.hs_code_prefix.in_(list(by_prefix.keys())),
        ).all()
    details: list[dict[str, Any]] = []
    for r in rows:
        origin = (r.origin_country or "").strip().upper()
        origin_known = re.fullmatch(r"[A-Z]{2}", origin) is not None
        if country_norm and origin_known and origin != country_norm:
            continue
        issues: list[str] = []
        boundaries = []
        for literal in (r.effective_from, r.effective_to):
            try:
                parsed = date.fromisoformat(literal) if literal else None
                if parsed is None or parsed.isoformat() != literal:
                    raise ValueError("Unbound calendar date")
                boundaries.append(parsed)
            except (TypeError, ValueError):
                boundaries.append(None)
        start, end = boundaries
        if start is not None and end is not None and start > end:
            issues.append("effective_period_invalid")
        elif (start is not None and requested_date < start) or (end is not None and requested_date > end):
            continue
        if None in boundaries:
            issues.append("effective_period_unverified")
        if not country_norm:
            issues.append("origin_country_missing")
        if not origin_known:
            issues.append("origin_country_scope_unverified")
        if (r.manufacturer_exporter or "").strip():
            issues.append("manufacturer_exporter_condition_unverified")
        if (r.product_description or "").strip():
            issues.append("product_characteristics_unverified")
        if bool(r.needs_verification):
            issues.append("source_row_requires_verification")
        measure_type = (r.measure_type or "").strip()
        if measure_type not in {"anti_dumping", "special_safeguard", "special_protective", "countervailing"}:
            issues.append("measure_type_unverified")
        family = "special_safeguard" if measure_type == "special_protective" else measure_type
        if family == "anti_dumping":
            source_marker = is_official_anti_dumping_row_marker(
                source_code=r.source_code, source_revision=r.source_revision)
            source_url = r.source_url
        elif family == "special_safeguard":
            source_marker = is_official_special_safeguard_row_marker(
                safeguard_source_code=r.safeguard_source_code, safeguard_source_revision=r.safeguard_source_revision)
            source_url = r.safeguard_source_url
        elif family == "countervailing":
            source_marker = is_official_countervailing_row_marker(
                countervailing_source_code=r.countervailing_source_code,
                countervailing_source_revision=r.countervailing_source_revision)
            source_url = r.countervailing_source_url
        else:
            source_marker, source_url = False, ""
        source_marker_bound = source_marker and is_safe_official_anti_dumping_source_url(source_url)
        if not source_marker_bound:
            issues.append("source_provenance_unverified")

        def rate_number(value):
            try:
                result = float(value)
                return result if isfinite(result) and result >= 0 else None
            except (TypeError, ValueError, OverflowError):
                return None

        percent, specific = rate_number(r.rate_percent), rate_number(r.rate_specific)
        if percent is None or specific is None:
            issues.append("rate_expression_unverified")
        if specific is not None and specific > 0:
            # SpecialDuty has no source-bound rate unit or denominator. Generic
            # invoice quantity, supplied weight or FX cannot fill that gap.
            issues.append("specific_unit_basis_unverified")
        if not isfinite(customs_value) or customs_value < 0:
            issues.append("customs_value_invalid")
        details.append({
                "candidate_id": r.id,
                "hs_code_prefix": r.hs_code_prefix,
                "origin_country": r.origin_country,
                "measure_type": measure_type,
                "measure_family": family,
                "official_source_marker_present": source_marker_bound,
                "legal_review_verified": False,
                "rate_percent": percent,
                "rate_specific": specific,
                "currency_code": (r.currency_code or "").upper().strip(),
                "fx_rate": None,
                "regulatory_act": r.regulatory_act or "",
                "manufacturer_exporter": r.manufacturer_exporter or "",
                "product_description": r.product_description or "",
                "effective_from": r.effective_from,
                "effective_to": r.effective_to,
                "as_of": requested_date.isoformat(),
                "needs_verification": bool(r.needs_verification),
                "review_reasons": issues,
                "amount": None,
                "match_len": by_prefix.get(r.hs_code_prefix, 0),
                **{field: getattr(r, field) for field in (
                    "source_code", "source_revision", "source_url",
                    "safeguard_source_code", "safeguard_source_revision", "safeguard_source_url",
                    "countervailing_source_code", "countervailing_source_revision", "countervailing_source_url",
                )},
            })
    counts = Counter(item["measure_family"] for item in details)
    total = 0.0
    for item in details:
        if counts[item["measure_family"]] > 1:
            # Prefix matches can be default/producer alternatives or amended
            # measures. No schema field establishes that they are cumulative.
            item["review_reasons"].append("overlapping_measure_candidates")
        pending = bool(item["review_reasons"])
        item["status"] = "needs_clarification" if pending else "provisional"
        item["applied"] = False
        item["calculation_available"] = not pending
        if pending:
            item["warning"] = SPECIAL_DUTY_REVIEW_REASON
        else:
            part = customs_value * item["rate_percent"] / 100.0
            if not isfinite(part) or not isfinite(total + part):
                item.update(status="needs_clarification", calculation_available=False,
                            warning=SPECIAL_DUTY_REVIEW_REASON)
                item["review_reasons"].append("calculation_overflow")
                continue
            total += part
            item["amount"] = _round2(part)
            item["review_reasons"].append("legal_review_unverified")
            item["warning"] = SPECIAL_DUTY_LEGAL_REVIEW_REASON
    details.sort(key=lambda x: int(x.get("match_len", 0)), reverse=True)
    return total, details


def _compute_structured_duty(
    customs_value: float,
    quantity: float,
    net_weight_kg: float | None,
    extra_quantity: float | None,
    duty_rule: HsDutyRule | None,
    manual_duty_rate: float | None,
    auto_duty_rate: float,
    fx_rates: dict[str, float] | None,
) -> tuple[float, float, float | None, float | None, str, float | None, float | None]:
    """Возвращает: duty, duty_rate, ad_valorem_amount, specific_amount_rub, selected_rule, fx_rate, specific_qty_used."""
    if manual_duty_rate is not None:
        duty = customs_value * manual_duty_rate / 100.0
        return duty, manual_duty_rate, duty, None, "manual_rate", None, None

    # Фолбэк на старую логику, если правило не найдено.
    if duty_rule is None:
        duty = customs_value * auto_duty_rate / 100.0
        return duty, auto_duty_rate, duty, None, "ad_valorem", None, None

    rule_type = (duty_rule.type or "ad_valorem").strip().lower()
    ad_pct_raw = duty_rule.ad_valorem_pct
    ad_pct = _num(ad_pct_raw)
    ad_valorem_amount = customs_value * ad_pct / 100.0 if ad_pct_raw is not None else None

    specific_amount_rub: float | None = None
    fx_rate: float | None = None
    specific_qty_used: float | None = None
    if duty_rule.specific_amount is not None:
        amount = _num(duty_rule.specific_amount)
        ccy = (duty_rule.specific_currency or "").upper().strip()
        uom = (duty_rule.specific_uom or "").lower().strip()
        if uom == "kg":
            q_used = _num(net_weight_kg)
        elif uom in {"l", "pcs", "m2", "m3", "t"}:
            q_used = _num(extra_quantity)
        else:
            # Для legacy-правил без единицы оставляем совместимость.
            q_used = _num(quantity)
        if q_used <= 0:
            raise ValueError("Для точного расчета необходимо указать вес/количество")
        specific_qty_used = q_used
        rates = dict(_FALLBACK_FX_RATES)
        rates.update({(k or "").upper(): float(v) for k, v in (fx_rates or {}).items()})
        if ccy not in rates:
            raise ValueError(f"Неизвестная валюта специфической ставки: {ccy or 'EMPTY'}")
        fx_rate = _num(rates.get(ccy) or 1.0)
        specific_amount_rub = amount * q_used * float(fx_rate)

    # simple ad valorem
    if rule_type == "ad_valorem":
        duty = ad_valorem_amount if ad_valorem_amount is not None else customs_value * auto_duty_rate / 100.0
        used_rate = ad_pct if ad_pct_raw is not None else auto_duty_rate
        return duty, used_rate, ad_valorem_amount, specific_amount_rub, "ad_valorem", fx_rate, specific_qty_used

    # simple specific
    if rule_type == "specific":
        duty = specific_amount_rub or 0.0
        return duty, 0.0, ad_valorem_amount, specific_amount_rub, "specific", fx_rate, specific_qty_used

    # combined max/min
    left = ad_valorem_amount
    right = specific_amount_rub
    left_val = _num(left)
    right_val = _num(right)
    if rule_type == "combined_min":
        if left is not None and right is not None:
            duty = min(left_val, right_val)
            selected = "ad_valorem" if duty == left_val else "specific"
        elif left is not None:
            duty = left_val
            selected = "ad_valorem"
        elif right is not None:
            duty = right_val
            selected = "specific"
        else:
            duty = customs_value * auto_duty_rate / 100.0
            selected = "fallback_auto"
        used_rate = auto_duty_rate if selected == "fallback_auto" else ad_pct
        return duty, used_rate, ad_valorem_amount, specific_amount_rub, f"combined_min:{selected}", fx_rate, specific_qty_used

    # default combined_max
    if left is not None and right is not None:
        duty = max(left_val, right_val)
        selected = "ad_valorem" if duty == left_val else "specific"
    elif left is not None:
        duty = left_val
        selected = "ad_valorem"
    elif right is not None:
        duty = right_val
        selected = "specific"
    else:
        duty = customs_value * auto_duty_rate / 100.0
        selected = "fallback_auto"
    used_rate = auto_duty_rate if selected == "fallback_auto" else ad_pct
    return duty, used_rate, ad_valorem_amount, specific_amount_rub, f"combined_max:{selected}", fx_rate, specific_qty_used


def _resolve_vat(
    rate_vat: float,
    vat_rule: str,
    vat_rule_basis: str,
    matched: bool,
) -> tuple[float, str]:
    """Return (vat_rate, vat_reason) based on DB rule."""
    if not matched:
        return 22.0, "Ставка по умолчанию 22% (ТН ВЭД код не найден в локальной базе; применяется общая ставка НК РФ ст. 164 п. 3)"

    if vat_rule == "reduced10":
        basis = vat_rule_basis or "НК РФ ст. 164 п. 2: льготная ставка 10%"
        return 10.0, f"Ставка 10% — льготный перечень: {basis}"

    if vat_rule == "zero":
        basis = vat_rule_basis or "НК РФ ст. 164 п. 1: нулевая ставка"
        return 0.0, f"Ставка 0% — {basis}"

    if vat_rule == "exempt":
        basis = vat_rule_basis or "НК РФ ст. 150: освобождение от НДС при ввозе"
        return 0.0, f"НДС не взимается — {basis}"

    # none / unknown — 22% general
    basis = vat_rule_basis or "НК РФ ст. 164 п. 3 (общая ставка 22%)"
    return float(rate_vat), f"Общая ставка {rate_vat:.0f}% — {basis}"


def _vat_prefix_candidates(hs_code: str) -> list[tuple[str, int]]:
    d = _digits_hs(hs_code)
    if not d:
        return []
    out: list[tuple[str, int]] = []
    for length in (10, 8, 6, 4, 2):
        if len(d) >= length:
            out.append((d[:length], length))
    return out


def _find_vat_preference(hs_code: str) -> tuple[VatPreference | None, int]:
    with SessionLocal() as db:
        return pick_vat_preference_row(hs_code, db)


def get_effective_vat_rate(hs_code: str) -> float:
    """Фактическая ставка НДС при ввозе: vat_preferences → hs_rates → 22%."""
    rate, _ = find_rate_for_hs(hs_code)
    vat_pref, _ = _find_vat_preference(hs_code)
    if vat_pref is not None:
        return float(vat_pref.vat_rate)
    if rate is not None:
        return float(rate.vat_import_rate)
    return 22.0


def _resolve_antidumping(
    antidumping_type: str,
    antidumping_value: float,
    antidumping_condition: str,
    antidumping_countries: str,
    country: str | None,
    customs_value: float,
    quantity: float,
) -> tuple[float, str, str]:
    """Return (antidumping_amount, antidumping_reason, confidence)."""
    if (not isfinite(antidumping_value) or antidumping_value < 0
            or (antidumping_type in {"none", ""} and antidumping_value != 0)):
        return 0.0, "Тип и значение антидемпинговой ставки противоречат друг другу; требуется проверка", "manual_review"
    if antidumping_type == "none" or antidumping_type == "":
        return 0.0, "Не применяется", "n/a"

    # Check country applicability
    applicable_countries = [c.strip().upper() for c in antidumping_countries.split(",") if c.strip()]

    country_match = True
    if applicable_countries and country:
        country_match = country.upper() in applicable_countries

    if applicable_countries and not country:
        # Country unknown — flag as manual review needed
        reason = (
            f"Требуется ручная проверка: антидемпинговая мера применяется для стран {antidumping_countries}, "
            f"но страна происхождения не указана. {antidumping_condition or ''}"
        ).strip()
        return 0.0, reason, "manual_review"

    if not country_match:
        return 0.0, f"Не применяется: страна {country} не входит в список ({antidumping_countries})", "n/a"

    if antidumping_condition.strip():
        return 0.0, f"Требуется проверка условий антидемпинга: {antidumping_condition}", "manual_review"

    if antidumping_type == "percent":
        amount = customs_value * antidumping_value / 100.0
        reason = (
            f"Применяется {antidumping_value}% от таможенной стоимости. "
            f"{antidumping_condition or ''} Страна: {country}."
        ).strip()
        return amount, reason, "applied"

    if antidumping_type == "fixed":
        amount = antidumping_value * quantity
        reason = (
            f"Применяется фикс. ставка {antidumping_value} руб./ед. × {quantity} ед. "
            f"{antidumping_condition or ''} Страна: {country}."
        ).strip()
        return amount, reason, "applied"

    return 0.0, "Тип антидемпинговой ставки не определён; требуется проверка", "manual_review"


def compute_payments(payload: dict[str, Any]) -> dict[str, Any]:
    if "as_of" in payload:
        raise ValueError(LEGACY_PAYMENT_AS_OF_UNSUPPORTED)
    hs_code = str(payload.get("hs_code") or "").strip()
    hs_digits = _digits_hs(hs_code)
    customs_value = float(payload.get("customs_value") or 0.0)
    freight = float(payload.get("freight") or 0.0)
    country = str(payload.get("country") or "").upper().strip() or None

    if customs_value <= 0:
        raise ValueError("Таможенная стоимость должна быть > 0")

    # Геополитика: эмбарго и подмена ставки (geo_special_duties)
    geo_meta: dict[str, Any] = {
        "embargo": False,
        "duty_override_rate": None,
        "document_basis": "",
        "document_link": "",
    }
    if country and len(hs_digits) >= 4:
        country_risk = get_country_risk_by_iso(country)
        is_unfriendly = bool(country_risk.is_unfriendly) if country_risk else False
        embargo_row = find_geo_embargo_match(hs_digits, country, country_is_unfriendly=is_unfriendly)
        if embargo_row is not None:
            basis = (embargo_row.document_basis or "").strip()
            link = (embargo_row.document_link or "").strip()
            return {
                "status": "EMBARGO",
                "hs_code": hs_code,
                "country": country,
                "geo": {
                    "embargo": True,
                    "document_basis": basis[:512],
                    "document_link": link[:2000],
                    "measure_type": (embargo_row.measure_type or "embargo").strip(),
                },
                # Стабильная структура для потребителей compare/истории.
                "breakdown": {
                    "customs_fee": 0.0,
                    "duty_rate": 0.0,
                    "duty": 0.0,
                    "excise": 0.0,
                    "antidumping": 0.0,
                    "special_duties_amount": 0.0,
                    "vat_rate": 0.0,
                    "vat": 0.0,
                    "recycling_fee": 0.0,
                    "total_payable": 0.0,
                },
                "message": "Ввоз запрещён: найдено эмбарго в geo_special_duties.",
            }
        duty_override_row = find_geo_duty_override_row(hs_digits, country, country_is_unfriendly=is_unfriendly)
        if duty_override_row is not None:
            parsed_geo = _parse_duty_rate(str(duty_override_row.duty_rate or "0"))
            geo_rate = float(parsed_geo.get("ad_valorem") or 0.0)
            geo_meta = {
                "embargo": False,
                "duty_override_rate": geo_rate,
                "document_basis": (duty_override_row.document_basis or "").strip()[:512],
                "document_link": (duty_override_row.document_link or "").strip()[:2000],
            }

    insurance = payload.get("insurance")
    if insurance is None:
        insurance = 0.0015 * (customs_value + freight)
    insurance = float(insurance)

    rate, match_len = find_rate_for_hs(hs_code)
    matched = rate is not None
    confidence = _CONFIDENCE_MAP.get(match_len, "none")

    if rate is None:
        auto_duty_rate = 0.0
    else:
        auto_duty_rate = float(_parse_duty_rate(rate.duty_rate or "0").get("ad_valorem") or 0.0)
    vat_rule = (rate.vat_rule if rate else "none") or "none"
    vat_rule_basis = (rate.vat_rule_basis if rate else "") or ""
    raw_vat_rate = float(rate.vat_import_rate) if rate else 22.0
    excise_type = (rate.excise_type if rate else "none") or "none"
    excise_value = float(rate.excise_value) if rate else 0.0
    excise_basis = (rate.excise_basis if rate else "") or ""
    from .rate_display import resolve_excise_for_hs

    resolved_type, resolved_value, resolved_basis = resolve_excise_for_hs(hs_code)
    if excise_type in ("", "none") and resolved_type not in ("", "none"):
        excise_type = resolved_type
        excise_value = resolved_value
        excise_basis = resolved_basis or excise_basis
    antidumping_type = (rate.antidumping_type if rate else "none") or "none"
    antidumping_value = float(rate.antidumping_value) if rate else 0.0
    antidumping_condition = (rate.antidumping_condition if rate else "") or ""
    antidumping_countries = (rate.antidumping_countries if rate else "") or ""
    matched_prefix = hs_code[:match_len] if match_len else ""
    apply_reduced_vat = bool(payload.get("apply_reduced_vat") or False)

    qty = float(payload.get("quantity") or 1.0)
    net_weight_kg = float(payload.get("net_weight_kg") or 0.0) if payload.get("net_weight_kg") is not None else None
    extra_quantity = float(payload.get("extra_quantity") or 0.0) if payload.get("extra_quantity") is not None else None

    # Duty (структурированные правила hs_duty_rules + fallback на историческую ставку)
    duty_rule, duty_rule_match_len = _find_duty_rule_for_hs(hs_code)
    manual_duty_rate = float(payload.get("duty_rate")) if payload.get("duty_rate") is not None else None
    # Гео-подмена ставки применяется к базовой (исторической) адвалорной логике;
    # структурированное правило hs_duty_rules остаётся приоритетным.
    if manual_duty_rate is None and duty_rule is None and geo_meta.get("duty_override_rate") is not None:
        manual_duty_rate = float(geo_meta["duty_override_rate"])
    duty, duty_rate, ad_valorem_amount, specific_amount_rub, selected_rule, fx_rate, specific_qty_used = _compute_structured_duty(
        customs_value=customs_value,
        quantity=qty,
        net_weight_kg=net_weight_kg,
        extra_quantity=extra_quantity,
        duty_rule=duty_rule,
        manual_duty_rate=manual_duty_rate,
        auto_duty_rate=auto_duty_rate,
        fx_rates=payload.get("_fx_rates") if isinstance(payload.get("_fx_rates"), dict) else None,
    )
    duty_source_missing = manual_duty_rate is None and duty_rule is None and rate is None

    # A legacy country row is a review candidate, not proof of eligibility for
    # this commodity, date and shipment. Caller assertions cannot authorize it.
    tariff_pref = get_tariff_preference(country) if country else None
    tariff_pref_meta: dict[str, Any] = {"applied": False}
    preference_review_required = False
    user_duty_rate = payload.get("duty_rate")
    if tariff_pref and user_duty_rate is None and geo_meta.get("duty_override_rate") is None:
        coeff = tariff_pref.duty_coefficient
        if coeff < 1.0:
            preference_review_required = True
            tariff_pref_meta = {
                "applied": False,
                "status": "needs_review",
                "preference_type": tariff_pref.preference_type,
                "candidate_duty_coefficient": coeff,
                "duty_coefficient": 1.0,
                "eligibility_verified": False,
                "source_kind": "legacy_country_tariff_preferences",
                "legal_ref": tariff_pref.legal_ref or "",
                "reason": TARIFF_PREFERENCE_REVIEW_REASON,
                "missing_eligibility": [
                    "current_regime",
                    "exact_code_and_date",
                    "origin_and_goods_status",
                    "origin_evidence",
                    "shipment_conditions_and_exceptions",
                ],
            }
        elif coeff > 1.0:
            duty = duty * coeff
            if ad_valorem_amount is not None:
                ad_valorem_amount = ad_valorem_amount * coeff
            if specific_amount_rub is not None:
                specific_amount_rub = specific_amount_rub * coeff
            tariff_pref_meta = {
                "applied": True,
                "preference_type": tariff_pref.preference_type,
                "duty_coefficient": coeff,
                "legal_ref": tariff_pref.legal_ref or "",
            }

    # Excise
    user_excise = payload.get("excise")
    excise_review_required = user_excise is None and (
        excise_type not in {"", "none", "percent", "fixed"}
        or not isfinite(excise_value) or excise_value < 0
        or (excise_type in {"", "none"} and excise_value != 0)
    )
    if user_excise is not None:
        excise = float(user_excise)
        excise_reason = "Указано вручную"
    elif excise_review_required:
        excise = 0.0
        excise_reason = "Тип, значение или применимость ставки акциза требуют проверки"
    elif excise_type == "percent":
        excise = customs_value * excise_value / 100.0
        basis_str = excise_basis or f"НК РФ ст. 193: {excise_value}% от таможенной стоимости"
        excise_reason = f"Авто: {excise_value}% — {basis_str}"
    elif excise_type == "fixed":
        qty = float(payload.get("quantity") or 1.0)
        excise = excise_value * qty
        basis_str = excise_basis or f"НК РФ ст. 193: фикс. ставка {excise_value} руб./ед."
        excise_reason = f"Авто: {excise_value} руб./ед. × {qty} ед. — {basis_str}"
    elif excise_type == "needs_review":
        excise = 0.0
        excise_reason = "Уточните ставку акциза"
    else:
        excise = 0.0
        excise_reason = "Не применяется" if excise_type in ("", "none") else "Тип ставки акциза не определён; требуется проверка"

    # Antidumping
    antidumping, antidumping_reason, antidumping_status = _resolve_antidumping(
        antidumping_type,
        antidumping_value,
        antidumping_condition,
        antidumping_countries,
        country,
        customs_value,
        qty,
    )
    special_duties_amount, special_duties_details = _resolve_special_duties(
        hs_code=hs_code,
        country=country,
        customs_value=customs_value,
        quantity=qty,
        fx_rates=payload.get("_fx_rates") if isinstance(payload.get("_fx_rates"), dict) else None,
    )
    special_duty_review_required = any(
        item.get("status") == "needs_clarification" for item in special_duties_details
    )
    special_duty_legal_review_required = any(
        item.get("status") == "provisional" for item in special_duties_details
    )
    special_duties_warning: str | None = None
    warnings = list(dict.fromkeys(str(item["warning"]) for item in special_duties_details if item.get("warning")))
    if warnings:
        special_duties_warning = " ".join(warnings)

    # Recycling fee (утильсбор) for vehicles (8701-8705, 8711)
    recycling_fee_amount = 0.0
    recycling_fee_meta: dict[str, Any] = {"applied": False}
    vehicle_is_new = bool(payload.get("vehicle_is_new", True))
    engine_volume = int(payload["engine_volume"]) if payload.get("engine_volume") is not None else None
    recycling_matches = get_recycling_fee(hs_code, is_new=vehicle_is_new, engine_volume=engine_volume)
    if recycling_matches:
        best = recycling_matches[0]
        recycling_fee_amount = best["fee_amount"]
        recycling_fee_meta = {
            "applied": True,
            "vehicle_type": best["vehicle_type"],
            "is_new": best["is_new"],
            "base_rate": best["base_rate"],
            "coefficient": best["coefficient"],
            "fee_amount": best["fee_amount"],
            "description": best["description"],
            "legal_ref": best["legal_ref"],
            "all_matches": len(recycling_matches),
        }

    # Customs fee (2026 tariff) — в базу НДС при ввозе не включается (НК РФ)
    customs_fee = calculate_customs_fee(customs_value)

    # НДС при ввозе: база = таможенная стоимость + ввозная пошлина + акциз + антидемпинг/
    # компенсационные/специальные пошлины (без таможенного сбора).
    vat_pref, vat_pref_match_len = _find_vat_preference(hs_code)
    auto_vat_rate = float(vat_pref.vat_rate) if vat_pref else 22.0
    vat_decree_info = (vat_pref.decree_info or "") if vat_pref else ""
    vat_pref_comment = (vat_pref.comment or "") if vat_pref else ""
    if payload.get("vat_rate") is not None:
        vat_rate = float(payload.get("vat_rate"))
        vat_reason = f"Указано вручную: {vat_rate}%"
        vat_decree_info = ""
        vat_pref_comment = ""
    elif vat_pref is not None:
        vat_rate = auto_vat_rate
        vat_reason = (
            f"Льготная ставка {int(vat_rate)}% по справочнику vat_preferences: "
            f"{vat_decree_info or 'нормативный акт не указан'}."
        )
    elif rate is not None:
        vat_rate = raw_vat_rate
        basis = (vat_rule_basis or "").strip()
        vat_reason = (
            f"Ставка НДС по справочнику hs_rates: {vat_rate}%"
            + (f" ({vat_rule})" if vat_rule and vat_rule != "none" else "")
            + (f". {basis}" if basis else "")
        )
    else:
        vat_rate = 10.0 if apply_reduced_vat else 22.0
        if apply_reduced_vat:
            vat_reason = "Льготная ставка 10% (ручной признак apply_reduced_vat=true; проверьте нормативное основание)"
        else:
            vat_reason = "Базовая ставка 22% (нет hs_rates и записи в vat_preferences)"

    vat_source_missing = payload.get("vat_rate") is None and vat_pref is None and rate is None
    if vat_source_missing:
        vat_reason = VAT_SOURCE_MISSING_REASON

    review_reasons: list[str] = []
    review_messages: list[str] = []
    for required, code, reason in (
        (duty_source_missing, "duty_source_missing", DUTY_SOURCE_MISSING_REASON),
        (vat_source_missing, "vat_source_missing", VAT_SOURCE_MISSING_REASON),
        (preference_review_required, "tariff_preference_eligibility_unverified", TARIFF_PREFERENCE_REVIEW_REASON),
        (special_duty_review_required, "special_duty_applicability_unverified", SPECIAL_DUTY_REVIEW_REASON),
        (special_duty_legal_review_required, "special_duty_legal_review_unverified", SPECIAL_DUTY_LEGAL_REVIEW_REASON),
        (excise_review_required, "excise_applicability_unverified", excise_reason),
        (antidumping_status == "manual_review", "antidumping_applicability_unverified", antidumping_reason),
    ):
        if required:
            review_reasons.append(code)
            review_messages.append(reason)
    amounts_provisional = bool(review_reasons)
    payment_review_reason = " ".join(review_messages) or None

    duty_amount = _num(duty)
    excise_amount = _num(excise)
    antidumping_amount = _num(antidumping)
    special_duties_total = _num(special_duties_amount)
    customs_fee_amount = _num(customs_fee)

    recycling_fee_total = _num(recycling_fee_amount)

    vat_base = _sum_amounts(customs_value, duty_amount, excise_amount, antidumping_amount, special_duties_total)
    vat = _num(vat_base) * _num(vat_rate) / 100.0

    total = _sum_amounts(customs_fee_amount, duty_amount, excise_amount, antidumping_amount, special_duties_total, vat, recycling_fee_total)

    # Sources: интегрированные данные в приложении (без внешних ссылок)
    stats = get_integrated_data_stats()
    applied_sources = []
    data_info = f"{stats['hs_rates_count']:,} позиций в приложении".replace(",", " ")
    applied_sources.append({
        "name": "ЕТТ ЕАЭС (ставки пошлин)",
        "integrated": True,
        "data_info": data_info,
        "revision": rate.source_revision if rate else "seed",
    })
    applied_sources.append({
            "name": "НДС при ввозе (НК РФ ст. 164)",
        "integrated": True,
        "data_info": "Ставки 10%/22% в приложении",
            "revision": "reference",
    })
    if antidumping_type not in ("none", "") and antidumping_status in ("applied", "manual_review"):
        applied_sources.append({
            "name": "Меры торговой защиты ЕАЭС",
            "integrated": True,
            "data_info": "Антидемпинг из базы приложения",
            "revision": rate.source_revision if rate else "seed",
        })

    # Data quality
    data_quality = {
        "confidence": confidence,
        "matched_prefix": matched_prefix,
        "match_length": match_len,
        "source_code": "EEC_ETT" if rate else None,
        "antidumping_status": antidumping_status,
    }
    if amounts_provisional:
        data_quality.update({
            "status": "REVIEW_REQUIRED",
            "amounts_provisional": True,
            "payment_review_reason": payment_review_reason,
            "payment_review_reasons": review_reasons,
        })
    if preference_review_required:
        data_quality.update({
            "tariff_preference_status": "needs_review",
            "tariff_preference_warning": TARIFF_PREFERENCE_REVIEW_REASON,
        })

    tnved_context = get_tnved_context_for_hs(hs_code)

    if user_duty_rate is not None:
        duty_reason = f"Ставка пошлины указана вручную: {duty_rate}%."
    elif manual_duty_rate is not None:
        duty_reason = f"Подмена ставки по geo_special_duties: {duty_rate}%. {geo_meta['document_basis']}".strip()
    elif duty_rule is not None:
        duty_reason = (
            f"Структурированное правило: {duty_rule.type} "
            f"(код {duty_rule.commodity_code}). Выбрано: {selected_rule}."
        )
    elif matched:
        duty_reason = f"Ввозная пошлина {duty_rate}% по коду ТН ВЭД/ЕТТ ЕАЭС."
    else:
        duty_reason = DUTY_SOURCE_MISSING_REASON
    if preference_review_required:
        duty_reason += f" {TARIFF_PREFERENCE_REVIEW_REASON}"

    return {
        "status": "REVIEW_REQUIRED" if amounts_provisional else "OK",
        "amounts_provisional": amounts_provisional,
        "payment_review_reason": payment_review_reason,
        "payment_review_reasons": review_reasons,
        "hs_code": hs_code,
        "country": country,
        "customs_value": _round2(customs_value),
        "freight": _round2(freight),
        "insurance": _round2(insurance),
        "auto_detected": {
            "duty_rate": auto_duty_rate,
            "duty_rule_type": (duty_rule.type if duty_rule else ""),
            "duty_rule_code": (duty_rule.commodity_code if duty_rule else ""),
            "duty_rule_match_len": duty_rule_match_len,
            "vat_rate": auto_vat_rate,
            "apply_reduced_vat": apply_reduced_vat,
            "vat_rule": ("vat_preference" if vat_pref else vat_rule),
            "vat_pref_match_len": vat_pref_match_len,
            "excise_type": excise_type,
            "excise_value": excise_value,
            "antidumping_type": antidumping_type,
            "antidumping_value": antidumping_value,
            "antidumping_condition": antidumping_condition,
            "antidumping_countries": antidumping_countries,
        },
        "breakdown": {
            "customs_fee": _round2(customs_fee_amount),
            "duty_rate": duty_rate,
            "duty": _round2(duty_amount),
            "ad_valorem_amount": _round2(ad_valorem_amount) if ad_valorem_amount is not None else None,
            "specific_amount_rub": _round2(specific_amount_rub) if specific_amount_rub is not None else None,
            "selected_rule": selected_rule,
            "fx_rate": _round2(fx_rate) if fx_rate is not None else None,
            "fx_currency": (duty_rule.specific_currency if duty_rule else ""),
            "specific_qty_used": _round2(specific_qty_used) if specific_qty_used is not None else None,
            "specific_uom": ((duty_rule.specific_uom or "") if duty_rule else ""),
            "excise": _round2(excise_amount),
            "excise_reason": excise_reason,
            "antidumping": _round2(antidumping_amount),
            "antidumping_reason": antidumping_reason,
            "antidumping_status": antidumping_status,
            "special_duties_amount": _round2(special_duties_total),
            "special_duties_warning": special_duties_warning,
            "vat_rate": vat_rate,
            "vat_reason": vat_reason,
            "vat_decree_info": vat_decree_info,
            "vat_pref_comment": vat_pref_comment,
            "vat_base": _round2(vat_base),
            "vat": _round2(vat),
            "recycling_fee": _round2(recycling_fee_total),
            "total_payable": _round2(total),
        },
        "legal_basis": {
            "vat": vat_reason,
            "duty": duty_reason,
            "customs_fee": "Таможенный сбор рассчитан по шкале РФ 2026 по таможенной стоимости.",
            "antidumping": antidumping_reason,
            "excise": excise_reason,
        },
        "data_quality": data_quality,
        "sources": applied_sources,
        "tnved_context": tnved_context,
        "special_duties": special_duties_details,
        "special_duties_amount": _round2(special_duties_amount),
        "special_duties_warning": special_duties_warning,
        "geo": geo_meta,
        "tariff_preference": tariff_pref_meta,
        "recycling_fee": recycling_fee_meta,
    }


def compare_payment_scenarios(payload: dict[str, Any]) -> dict[str, Any]:
    """Сравнение 2–8 сценариев при общих экономических параметрах (что если другой ТН ВЭД)."""
    shared = payload.get("shared") or {}
    scenarios = payload.get("scenarios") or []
    if "as_of" in payload or "as_of" in shared or any(isinstance(row, dict) and "as_of" in row for row in scenarios):
        raise ValueError(LEGACY_PAYMENT_AS_OF_UNSUPPORTED)
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
    if isinstance(shared.get("_fx_rates"), dict):
        econ["_fx_rates"] = shared.get("_fx_rates")
    if shared.get("insurance") is not None:
        econ["insurance"] = float(shared["insurance"])
    if (shared.get("country") or "").strip():
        econ["country"] = str(shared["country"]).strip().upper()
    if shared.get("quantity") is not None:
        econ["quantity"] = float(shared["quantity"])
    for key in ("net_weight_kg", "extra_quantity"):
        if shared.get(key) is not None:
            econ[key] = float(shared[key])
    if shared.get("apply_reduced_vat") is not None:
        econ["apply_reduced_vat"] = bool(shared["apply_reduced_vat"])
    if shared.get("invoice_currency") is not None:
        econ["invoice_currency"] = str(shared["invoice_currency"])

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
        scenario_country = str(sc.get("country") or "").strip().upper()
        if scenario_country:
            merged["country"] = scenario_country
        for opt in ("duty_rate", "vat_rate", "excise"):
            if sc.get(opt) is not None:
                merged[opt] = sc[opt]
        res = compute_payments(merged)
        total = _num((res.get("breakdown") or {}).get("total_payable"))
        delta = None if first_total is None else _round2(total - first_total)
        if first_total is None:
            first_total = total
        tv = res.get("tnved_context") or {}
        out_scenarios.append(
            {
                "label": label,
                "hs_code": hs,
                "country": (merged.get("country") or None),
                "status": res.get("status") or "OK",
                "amounts_provisional": bool(res.get("amounts_provisional")),
                "payment_review_reason": res.get("payment_review_reason"),
                "payment_review_reasons": res.get("payment_review_reasons"),
                "tariff_preference": res.get("tariff_preference"),
                "payment_result": res,
                "calculation_payload": merged,
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

    # Even the first row cannot be a comparison baseline while any scenario is
    # unresolved or blocked. Keep estimates, but do not imply proven savings.
    comparison_requires_review = any(
        row["amounts_provisional"] or row["status"] != "OK"
        for row in out_scenarios
    )
    if comparison_requires_review:
        for row in out_scenarios:
            row["delta_total_vs_first_rub"] = None

    return {
        "status": "REVIEW_REQUIRED" if comparison_requires_review else "OK",
        "amounts_provisional": any(row["amounts_provisional"] for row in out_scenarios),
        "shared_economic": econ,
        "scenarios": out_scenarios,
    }


def get_duty_rule_info(hs_code: str) -> dict[str, Any] | None:
    """Справка по структурированному правилу пошлины для UI."""
    rule, match_len = _find_duty_rule_for_hs(hs_code)
    if not rule:
        return None
    return {
        "commodity_code": rule.commodity_code,
        "type": rule.type,
        "ad_valorem_pct": float(rule.ad_valorem_pct) if rule.ad_valorem_pct is not None else None,
        "specific_amount": float(rule.specific_amount) if rule.specific_amount is not None else None,
        "specific_currency": rule.specific_currency or "",
        "specific_uom": rule.specific_uom or "",
        "match_len": match_len,
    }


def get_commodity_meta_info(hs_code: str) -> dict[str, Any] | None:
    """Справка по дополнительной единице и статистическому весу для UI."""
    commodity, match_len = _find_commodity_for_hs(hs_code)
    if not commodity:
        return None
    return {
        "commodity_code": commodity.code,
        "supp_unit": (commodity.supp_unit or "").strip(),
        "weight_coeff": float(commodity.weight_coeff or 0.0),
        "match_len": match_len,
    }
