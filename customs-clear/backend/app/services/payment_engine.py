from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
    is_safe_official_countervailing_source_url,
    is_safe_official_special_safeguard_source_url,
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


def _manual_nonnegative_number(payload: dict[str, Any], key: str, label: str) -> float | None:
    """Parse a manual override without admitting invalid money operands."""
    raw = payload.get(key)
    if raw is None:
        return None
    try:
        value = None if isinstance(raw, bool) else float(raw)
    except (TypeError, ValueError, OverflowError):
        value = None
    if value is None or not isfinite(value) or value < 0:
        raise ValueError(f"{label} должна быть конечным неотрицательным числом")
    return value


def _validated_payment_result(value: Any, *, label: str) -> float:
    """Fail closed when otherwise valid operands overflow dependent arithmetic."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} выходит за конечный числовой диапазон") from exc
    if not isfinite(number) or number < 0:
        raise ValueError(f"{label} выходит за конечный числовой диапазон")
    return number


def _sum_amounts(*parts: Any | None) -> float:
    return sum(_num(p) for p in parts)


def _round2(v: Any | None) -> float:
    return round(_num(v), 2)


def _validated_automatic_duty_operand(value: Any, *, label: str) -> float:
    """Reject malformed stored duty operands before payment arithmetic."""
    if isinstance(value, bool):
        raise ValueError(f"Некорректное автоматическое значение {label}")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Некорректное автоматическое значение {label}") from exc
    if not isfinite(number) or number < 0:
        raise ValueError(f"Некорректное автоматическое значение {label}")
    return number


def _validated_automatic_duty_result(value: Any, *, label: str) -> float:
    """Reject overflow/non-finite automatic duty results before dependent math."""
    number = float(value)
    if not isfinite(number) or number < 0:
        raise ValueError(f"Некорректный результат автоматического расчета {label}")
    return number


_LEGACY_DUTY_NUMBER = r"[0-9]+(?:\.[0-9]+)?"
_LEGACY_DUTY_UNIT = (
    r"(?:евро(?:\s*/\s*кг|\s+за(?:\s+кг)?)?|eur(?:\s*/\s*кг)?|€(?:\s*/\s*кг)?)"
)
_LEGACY_DUTY_SIMPLE_RE = re.compile(
    rf"(?:{_LEGACY_DUTY_NUMBER}|{_LEGACY_DUTY_NUMBER}\s*%)",
    re.IGNORECASE,
)
_LEGACY_DUTY_SPECIFIC_RE = re.compile(
    rf"{_LEGACY_DUTY_NUMBER}\s*{_LEGACY_DUTY_UNIT}",
    re.IGNORECASE,
)
_LEGACY_DUTY_COMBINED_RE = re.compile(
    rf"{_LEGACY_DUTY_NUMBER}\s*%\s*(?:,\s*)?"
    rf"(?:(?:но\s+)?(?:не\s+менее|не\s+меньше)|плюс)\s*"
    rf"{_LEGACY_DUTY_NUMBER}\s*{_LEGACY_DUTY_UNIT}",
    re.IGNORECASE,
)


def _contains_forbidden_legacy_sign(raw_text: str) -> bool:
    """Fail closed on signed/ambiguous rate text before permissive parsing."""
    for char in raw_text:
        name = unicodedata.name(char, "")
        if (
            unicodedata.category(char) == "Pd"
            or "MINUS" in name
            or "HYPHEN" in name
            or "DASH" in name
            or "PLUS SIGN" in name
        ):
            return True
    return False


def _parse_validated_legacy_duty_rate(raw_value: Any) -> dict[str, Any]:
    """Parse only a source value that is bound to a supported non-negative rate token."""
    if (
        isinstance(raw_value, bool)
        or raw_value is None
        or not isinstance(raw_value, (str, int, float))
    ):
        raise ValueError("Некорректная автоматическая ставка пошлины в hs_rates")
    if isinstance(raw_value, (int, float)):
        number = _validated_automatic_duty_operand(raw_value, label="ставки пошлины в hs_rates")
        return {
            "ad_valorem": number,
            "specific_eur": 0.0,
            "rule": "STANDARD",
            "raw_text": str(raw_value),
        }
    else:
        raw_text = str(raw_value).strip()
        if not raw_text:
            raise ValueError("Некорректная автоматическая ставка пошлины в hs_rates")

    low = raw_text.lower()
    if (
        _contains_forbidden_legacy_sign(raw_text)
        or re.search(r"\b(?:nan|inf(?:inity)?)\b", low)
    ):
        raise ValueError("Некорректная автоматическая ставка пошлины в hs_rates")
    if not any(
        grammar.fullmatch(raw_text)
        for grammar in (
            _LEGACY_DUTY_SIMPLE_RE,
            _LEGACY_DUTY_SPECIFIC_RE,
            _LEGACY_DUTY_COMBINED_RE,
        )
    ):
        raise ValueError("Некорректная автоматическая ставка пошлины в hs_rates")

    parsed = _parse_duty_rate(raw_text)
    _validated_automatic_duty_operand(parsed.get("ad_valorem"), label="ставки пошлины в hs_rates")
    _validated_automatic_duty_operand(parsed.get("specific_eur"), label="специфической ставки в hs_rates")
    return parsed


# Confidence levels based on HS-prefix match length
_CONFIDENCE_MAP = {
    10: "high",
    8: "high",
    6: "medium",
    4: "low",
    0: "none",
}

SPECIAL_DUTIES_COUNTRY_WARNING = (
    "Антидемпинговые и иные специальные пошлины проверяются только при указании "
    "страны происхождения. Данные по мерам защиты рынка могут быть неполными — "
    "см. remedies.eaeunion.org"
)

HS_RATE_SOURCE_BINDING_REVIEW_REASON = (
    "Строка hs_rates не содержит типизированной неизменяемой привязки к "
    "официальному источнику, редакции и проверенному интервалу действия; "
    "зависимые автоматические суммы являются предварительными и требуют ручной проверки."
)
DUTY_RULE_SOURCE_BINDING_REVIEW_REASON = (
    "Структурированное правило hs_duty_rules не содержит типизированной "
    "неизменяемой привязки к официальной строке источника и редакции; "
    "автоматическая пошлина является предварительной."
)
HS_RATE_SOURCE_MISSING_REVIEW_REASON = (
    "Для кода не найдена строка hs_rates с проверенной применимостью; нулевая "
    "пошлина и отсутствие иных платежей не могут считаться подтверждёнными."
)


def _hs_rate_source_binding_unverified(rate: Any | None) -> bool:
    """Treat legacy rate metadata as observations, never as admission proof.

    The current ``HsRate`` schema stores mutable URL/revision/date strings but
    no reviewed source-row identity or immutable admission token. Plausible
    strings therefore cannot authorize a final customs payment.
    """
    return rate is not None


def _duty_rule_source_binding_unverified(rule: Any | None) -> bool:
    """Return whether a persisted structured duty rule lacks source identity."""
    return isinstance(rule, HsDutyRule)


def _resolve_fx_rate(currency: str, fx_rates: dict[str, float] | None) -> float:
    """Resolve a RUB conversion without inventing an unverified market rate."""
    ccy = (currency or "").upper().strip()
    if ccy == "RUB":
        return 1.0
    supplied = {
        (str(key) if key is not None else "").upper().strip(): value
        for key, value in (fx_rates or {}).items()
    }
    if not ccy or ccy not in supplied:
        raise ValueError(f"Нет подтвержденного курса ЦБ РФ для валюты: {ccy or 'EMPTY'}")
    raw_rate = supplied[ccy]
    if isinstance(raw_rate, bool):
        raise ValueError(f"Некорректный курс ЦБ РФ для валюты: {ccy}")
    try:
        rate = float(raw_rate)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Некорректный курс ЦБ РФ для валюты: {ccy}") from exc
    if not isfinite(rate) or rate <= 0:
        raise ValueError(f"Некорректный курс ЦБ РФ для валюты: {ccy}")
    return rate


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
    parsed = _parse_validated_legacy_duty_rate(rate.duty_rate)
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


def _special_duty_date_window(
    effective_from: Any | None,
    effective_to: Any | None,
) -> tuple[date | None, date | None] | None:
    """Distinguish an invalid window from a valid but inactive measure."""
    parsed: list[date | None] = []
    for raw in (effective_from, effective_to):
        value = str(raw or "").strip()
        if not value:
            parsed.append(None)
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
            return None
        try:
            parsed.append(date.fromisoformat(value))
        except ValueError:
            return None

    starts, ends = parsed
    if starts is not None and ends is not None and starts > ends:
        return None
    return starts, ends


def _special_duty_is_effective(
    effective_from: Any | None,
    effective_to: Any | None,
    on_date: date,
) -> bool:
    window = _special_duty_date_window(effective_from, effective_to)
    if window is None:
        return False
    starts, ends = window
    if starts is not None and starts > on_date:
        return False
    if ends is not None and ends < on_date:
        return False
    return True


def _trade_remedy_timestamp_is_not_future(value: Any | None) -> bool:
    if not isinstance(value, datetime):
        return False
    stamp = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return stamp <= datetime.now(timezone.utc)


def _trade_remedy_revision_is_not_future(value: Any | None) -> bool:
    raw = str(value or "").strip()
    try:
        revision_date = date.fromisoformat(raw.rsplit(":", 1)[-1])
    except ValueError:
        return False
    return revision_date <= date.today()


def _special_duty_admission_failure(row: SpecialDuty) -> str | None:
    """Return a fail-closed reason or admit measure-specific official evidence."""
    for field in ("rate_percent", "rate_specific"):
        raw = getattr(row, field, None)
        try:
            value = float(raw) if raw is not None and not isinstance(raw, bool) else None
        except (TypeError, ValueError, OverflowError):
            value = None
        if value is None or not isfinite(value) or value < 0:
            return "special_duty_rate_invalid"
    if bool(getattr(row, "needs_verification", False)):
        return "special_duty_provenance_unverified"
    if not str(getattr(row, "regulatory_act", "") or "").strip():
        return "special_duty_provenance_unverified"
    if not str(getattr(row, "effective_from", "") or "").strip():
        return "special_duty_provenance_unverified"
    if not str(getattr(row, "effective_to", "") or "").strip():
        return "special_duty_provenance_unverified"

    # SpecialDuty has no persisted typed unit/denominator.  A positive specific
    # rate therefore cannot safely be multiplied by generic quantity.
    if float(getattr(row, "rate_specific", 0.0) or 0.0) != 0.0:
        return "special_duty_specific_unit_unverified"

    measure_type = str(getattr(row, "measure_type", "") or "anti_dumping").strip().lower()
    if measure_type == "anti_dumping":
        revision = getattr(row, "source_revision", None)
        synced_at = getattr(row, "synced_at", None)
        marker_ok = is_official_anti_dumping_row_marker(
            source_code=getattr(row, "source_code", None),
            source_revision=revision,
        )
        url_ok = is_safe_official_anti_dumping_source_url(getattr(row, "source_url", None))
    elif measure_type in {"special_safeguard", "special_protective"}:
        revision = getattr(row, "safeguard_source_revision", None)
        synced_at = getattr(row, "safeguard_synced_at", None)
        marker_ok = is_official_special_safeguard_row_marker(
            safeguard_source_code=getattr(row, "safeguard_source_code", None),
            safeguard_source_revision=revision,
        )
        url_ok = is_safe_official_special_safeguard_source_url(
            getattr(row, "safeguard_source_url", None)
        )
    elif measure_type == "countervailing":
        revision = getattr(row, "countervailing_source_revision", None)
        synced_at = getattr(row, "countervailing_synced_at", None)
        marker_ok = is_official_countervailing_row_marker(
            countervailing_source_code=getattr(row, "countervailing_source_code", None),
            countervailing_source_revision=revision,
        )
        url_ok = is_safe_official_countervailing_source_url(
            getattr(row, "countervailing_source_url", None)
        )
    else:
        return "special_duty_provenance_unverified"

    if not marker_ok or not url_ok or not synced_at:
        return "special_duty_provenance_unverified"
    if (
        not _trade_remedy_revision_is_not_future(revision)
        or not _trade_remedy_timestamp_is_not_future(synced_at)
    ):
        return "special_duty_provenance_future"
    return None


def _special_duty_identity(row: SpecialDuty) -> tuple[Any, ...]:
    """Identity for exact duplicate suppression; no overlap policy is inferred."""
    return (
        str(row.hs_code_prefix or "").strip(),
        str(row.origin_country or "").strip().upper(),
        str(row.measure_type or "anti_dumping").strip().lower(),
        float(row.rate_percent or 0.0),
        float(row.rate_specific or 0.0),
        str(row.currency_code or "RUB").strip().upper(),
        str(row.regulatory_act or "").strip(),
        str(row.manufacturer_exporter or "").strip(),
        str(row.product_description or "").strip(),
        str(row.effective_from or "").strip(),
        str(row.effective_to or "").strip(),
        str(row.source_code or "").strip(),
        str(row.source_revision or "").strip(),
        str(row.source_url or "").strip(),
        str(row.safeguard_source_code or "").strip(),
        str(row.safeguard_source_revision or "").strip(),
        str(row.safeguard_source_url or "").strip(),
        str(row.countervailing_source_code or "").strip(),
        str(row.countervailing_source_revision or "").strip(),
        str(row.countervailing_source_url or "").strip(),
    )


def _resolve_special_duties(
    hs_code: str,
    country: str | None,
    customs_value: float,
    quantity: float,
    fx_rates: dict[str, float] | None,
) -> tuple[float, list[dict[str, Any]], bool]:
    cands = _special_duty_prefix_candidates(hs_code)
    if not cands:
        return 0.0, [], False
    by_prefix = {p: m for p, m in cands}
    today = date.today()
    country_norm = (country or "").strip().upper() or None

    with SessionLocal() as db:
        query = db.query(SpecialDuty).filter(
            SpecialDuty.hs_code_prefix.in_(list(by_prefix.keys())),
        )
        if country_norm:
            query = query.filter(SpecialDuty.origin_country == country_norm)
        candidates = query.all()
        invalid_windows = [
            row for row in candidates
            if _special_duty_date_window(row.effective_from, row.effective_to) is None
        ]
        if invalid_windows:
            return 0.0, [{
                "warning": (
                    "Даты действия специальной пошлины некорректны. "
                    "Нельзя подтвердить неприменимость меры; требуется проверка."
                ),
                "affected_codes": sorted({row.hs_code_prefix for row in invalid_windows}),
                "review_reason": "special_duty_dates_invalid",
            }], True
        rows = [
            row
            for row in candidates
            if _special_duty_is_effective(
                row.effective_from,
                row.effective_to,
                today,
            )
        ]

    if not rows:
        return 0.0, [], False

    if not country_norm:
        return 0.0, [
            {
                "warning": (
                    "Страна происхождения не указана. "
                    "Возможно применение антидемпинговых и иных специальных пошлин."
                ),
                "affected_codes": sorted({r.hs_code_prefix for r in rows}),
                "origin_countries": sorted({r.origin_country for r in rows if r.origin_country}),
                "review_reason": "special_duty_country_missing",
            }
        ], True

    inadmissible_rows = [
        (row, failure)
        for row in rows
        if (failure := _special_duty_admission_failure(row)) is not None
    ]
    if inadmissible_rows:
        failure_reasons = {failure for _, failure in inadmissible_rows}
        review_reason = (
            next(iter(failure_reasons))
            if len(failure_reasons) == 1
            else "special_duty_admission_unresolved"
        )
        return 0.0, [
            {
                "warning": (
                    "Специальная пошлина не включена в итог: одна или несколько активных строк "
                    "не имеют полного официального подтверждения и требуют проверки."
                ),
                "affected_codes": sorted({r.hs_code_prefix for r, _ in inadmissible_rows}),
                "review_reason": review_reason,
            }
        ], True

    unique_rows: dict[tuple[Any, ...], SpecialDuty] = {}
    for row in rows:
        unique_rows.setdefault(_special_duty_identity(row), row)
    rows = list(unique_rows.values())
    if len(rows) > 1:
        return 0.0, [
            {
                "warning": (
                    "Специальная пошлина не включена в итог: найдено несколько одновременно "
                    "применимых мер, а правило их совместного применения не подтверждено."
                ),
                "affected_codes": sorted({r.hs_code_prefix for r in rows}),
                "review_reason": "special_duty_overlap_unresolved",
            }
        ], True

    details: list[dict[str, Any]] = []
    total = 0.0
    for r in rows:
        part_ad = _validated_payment_result(
            customs_value * float(r.rate_percent) / 100.0,
            label="Сумма специальной пошлины",
        )
        ccy = (r.currency_code or "RUB").upper().strip()
        specific_rate = float(r.rate_specific)
        # An ad-valorem amount is already in RUB. Stored currency metadata
        # must not require or invent an exchange rate for a zero fixed part.
        fx = _resolve_fx_rate(ccy, fx_rates) if specific_rate else None
        part_spec = specific_rate * float(quantity or 0.0) * fx if fx is not None else 0.0
        part = part_ad + part_spec
        total += part
        details.append(
            {
                "hs_code_prefix": r.hs_code_prefix,
                "origin_country": r.origin_country,
                "measure_type": r.measure_type or "anti_dumping",
                "rate_percent": float(r.rate_percent or 0.0),
                "rate_specific": float(r.rate_specific or 0.0),
                "currency_code": ccy,
                "fx_rate": fx,
                "regulatory_act": r.regulatory_act or "",
                "effective_from": r.effective_from or "",
                "effective_to": r.effective_to or "",
                "needs_verification": bool(getattr(r, "needs_verification", False)),
                "amount": _round2(part),
                "match_len": by_prefix.get(r.hs_code_prefix, 0),
            }
        )
    details.sort(key=lambda x: int(x.get("match_len", 0)), reverse=True)
    return total, details, False


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
        duty = _validated_payment_result(
            customs_value * manual_duty_rate / 100.0,
            label="ручной пошлины",
        )
        return duty, manual_duty_rate, duty, None, "manual_rate", None, None

    auto_duty_rate = _validated_automatic_duty_operand(
        auto_duty_rate,
        label="ставки пошлины",
    )

    # Фолбэк на старую логику, если правило не найдено.
    if duty_rule is None:
        duty = _validated_automatic_duty_result(
            customs_value * auto_duty_rate / 100.0,
            label="пошлины",
        )
        return duty, auto_duty_rate, duty, None, "ad_valorem", None, None

    rule_type = (duty_rule.type or "ad_valorem").strip().lower()
    ad_pct_raw = duty_rule.ad_valorem_pct
    ad_pct = (
        _validated_automatic_duty_operand(
            ad_pct_raw,
            label="адвалорной ставки",
        )
        if ad_pct_raw is not None
        else 0.0
    )
    ad_valorem_amount = (
        _validated_automatic_duty_result(
            customs_value * ad_pct / 100.0,
            label="адвалорной пошлины",
        )
        if ad_pct_raw is not None
        else None
    )

    specific_amount_rub: float | None = None
    fx_rate: float | None = None
    specific_qty_used: float | None = None
    if duty_rule.specific_amount is not None:
        amount = _validated_automatic_duty_operand(
            duty_rule.specific_amount,
            label="специфической ставки",
        )
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
        fx_rate = _resolve_fx_rate(ccy, fx_rates)
        specific_amount_rub = _validated_automatic_duty_result(
            amount * q_used * float(fx_rate),
            label="специфической пошлины",
        )

    # simple ad valorem
    if rule_type == "ad_valorem":
        duty = ad_valorem_amount if ad_valorem_amount is not None else _validated_automatic_duty_result(
            customs_value * auto_duty_rate / 100.0,
            label="пошлины",
        )
        used_rate = ad_pct if ad_pct > 0 else auto_duty_rate
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
            duty = _validated_automatic_duty_result(
                customs_value * auto_duty_rate / 100.0,
                label="пошлины",
            )
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
        duty = _validated_automatic_duty_result(
            customs_value * auto_duty_rate / 100.0,
            label="пошлины",
        )
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
    antidumping_type = str(antidumping_type or "").strip().lower()
    if antidumping_type in {"none", ""}:
        return 0.0, "Не применяется", "n/a"

    if antidumping_type not in {"percent", "fixed"}:
        return (
            0.0,
            "Требуется ручная проверка: неизвестный тип антидемпинговой ставки "
            f"«{antidumping_type}»; автоматический расчёт и вывод об отсутствии меры запрещены.",
            "manual_review",
        )

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

    if antidumping_type == "percent":
        amount = customs_value * antidumping_value / 100.0
        reason = (
            f"Применяется {antidumping_value}% от таможенной стоимости. "
            f"{antidumping_condition or ''} Страна: {country}."
        ).strip()
        return amount, reason, "applied"

    if antidumping_type == "fixed":
        # ``hs_rates`` stores only the numeric fixed value.  It has no typed
        # currency, source unit or denominator, so the generic invoice
        # ``quantity`` cannot prove the operand required by a trade-remedy
        # measure (kg, tonne, item, etc.).  Keep the candidate visible but do
        # not admit an amount into VAT or the final payable total.
        reason = (
            "Требуется ручная проверка: для фиксированной антидемпинговой ставки "
            f"{antidumping_value} не указаны валюта, единица и знаменатель источника; "
            f"универсальное количество {quantity} не применяется автоматически. "
            f"{antidumping_condition or ''} Страна: {country}."
        ).strip()
        return 0.0, reason, "manual_review"

    raise AssertionError("unreachable antidumping type")


def compute_payments(payload: dict[str, Any]) -> dict[str, Any]:
    manual_duty_rate = _manual_nonnegative_number(
        payload, "duty_rate", "Ручная ставка пошлины"
    )
    manual_vat_rate = _manual_nonnegative_number(
        payload, "vat_rate", "Ручная ставка НДС"
    )
    manual_excise = _manual_nonnegative_number(
        payload, "excise", "Ручная сумма акциза"
    )
    hs_code = str(payload.get("hs_code") or "").strip()
    hs_digits = _digits_hs(hs_code)
    customs_value = float(payload.get("customs_value") or 0.0)
    freight = float(payload.get("freight") or 0.0)
    country = str(payload.get("country") or "").upper().strip() or None
    manual_duty_rate_supplied = manual_duty_rate is not None

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
            geo_rate = None
            if not manual_duty_rate_supplied:
                parsed_geo = _parse_validated_legacy_duty_rate(duty_override_row.duty_rate)
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

    if rate is None or manual_duty_rate_supplied:
        auto_duty_rate = 0.0
    else:
        auto_duty_rate = float(_parse_validated_legacy_duty_rate(rate.duty_rate).get("ad_valorem") or 0.0)
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
    antidumping_type = str((rate.antidumping_type if rate else "none") or "none").strip().lower()
    antidumping_value = float(rate.antidumping_value) if rate else 0.0
    antidumping_condition = (rate.antidumping_condition if rate else "") or ""
    antidumping_countries = (rate.antidumping_countries if rate else "") or ""
    matched_prefix = hs_code[:match_len] if match_len else ""
    apply_reduced_vat = bool(payload.get("apply_reduced_vat") or False)

    qty = float(payload.get("quantity") or 1.0)
    net_weight_kg = float(payload.get("net_weight_kg") or 0.0) if payload.get("net_weight_kg") is not None else None
    extra_quantity = float(payload.get("extra_quantity") or 0.0) if payload.get("extra_quantity") is not None else None

    # Duty (структурированные правила hs_duty_rules + fallback на историческую ставку)
    if manual_duty_rate is not None:
        # Manual override is authoritative for this calculation. Do not parse or
        # admit an otherwise unused automatic rule/source value.
        duty_rule, duty_rule_match_len = None, 0
    else:
        duty_rule, duty_rule_match_len = _find_duty_rule_for_hs(hs_code)
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

    # Tariff preference: apply country-of-origin duty coefficient
    tariff_pref = get_tariff_preference(country) if country else None
    tariff_pref_meta: dict[str, Any] = {"applied": False}
    user_duty_rate = manual_duty_rate
    if tariff_pref and user_duty_rate is None and geo_meta.get("duty_override_rate") is None:
        coeff = tariff_pref.duty_coefficient
        if coeff != 1.0:
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

    # Final automatic-duty barrier immediately before dependent VAT/final-payable
    # arithmetic. This also covers automatic preference/geo transformations.
    if not manual_duty_rate_supplied:
        duty = _validated_automatic_duty_result(duty, label="пошлины")
        if ad_valorem_amount is not None:
            ad_valorem_amount = _validated_automatic_duty_result(
                ad_valorem_amount,
                label="адвалорной пошлины",
            )
        if specific_amount_rub is not None:
            specific_amount_rub = _validated_automatic_duty_result(
                specific_amount_rub,
                label="специфической пошлины",
            )

    # Excise
    user_excise = manual_excise
    if user_excise is not None:
        excise = user_excise
        excise_reason = "Указано вручную"
    elif excise_type == "percent":
        excise = customs_value * excise_value / 100.0
        basis_str = excise_basis or f"НК РФ ст. 193: {excise_value}% от таможенной стоимости"
        excise_reason = f"Авто: {excise_value}% — {basis_str}"
    elif excise_type == "fixed":
        raise ValueError(
            "Фиксированная ставка акциза не содержит подтверждённую единицу "
            "и знаменатель; итоговый платёж требует ручной проверки"
        )
    elif excise_type == "needs_review":
        excise = 0.0
        excise_reason = "Уточните ставку акциза"
    else:
        excise = 0.0
        excise_reason = "Не применяется"

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
    rate_source_binding_unverified = _hs_rate_source_binding_unverified(rate)
    rate_source_missing = rate is None
    duty_rule_source_binding_unverified = (
        manual_duty_rate is None and _duty_rule_source_binding_unverified(duty_rule)
    )
    payment_review_reasons: list[str] = []
    if rate_source_missing:
        payment_review_reasons.append("hs_rate_source_missing")
        antidumping_status = "manual_review"
        antidumping_reason = HS_RATE_SOURCE_MISSING_REVIEW_REASON
    if rate_source_binding_unverified:
        payment_review_reasons.append("hs_rate_source_binding_unverified")
        # Even a stored ``none`` conclusion for trade remedies is an automatic
        # legal conclusion from the unbound row. Keep the arithmetic candidate
        # visible but do not let it authorize dependent VAT/final totals.
        antidumping_status = "manual_review"
        antidumping_reason = HS_RATE_SOURCE_BINDING_REVIEW_REASON
    if duty_rule_source_binding_unverified:
        payment_review_reasons.append("duty_rule_source_binding_unverified")
    special_duties_amount, special_duties_details, special_duties_review_required = _resolve_special_duties(
        hs_code=hs_code,
        country=country,
        customs_value=customs_value,
        quantity=qty,
        fx_rates=payload.get("_fx_rates") if isinstance(payload.get("_fx_rates"), dict) else None,
    )
    special_duties_warning: str | None = None
    if special_duties_details and special_duties_details[0].get("warning"):
        special_duties_warning = str(special_duties_details[0]["warning"])
    if special_duties_review_required:
        payment_review_reasons.append(
            str(special_duties_details[0].get("review_reason") or "special_duty_manual_review")
            if special_duties_details
            else "special_duty_manual_review"
        )

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
    if manual_vat_rate is not None:
        vat_rate = manual_vat_rate
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

    duty_amount = _num(duty)
    excise_amount = _num(excise)
    antidumping_amount = _num(antidumping)
    special_duties_total = _num(special_duties_amount)
    customs_fee_amount = _num(customs_fee)

    recycling_fee_total = _num(recycling_fee_amount)

    vat_base = _validated_payment_result(
        _sum_amounts(customs_value, duty_amount, excise_amount, antidumping_amount, special_duties_total),
        label="базы НДС",
    )
    vat = _validated_payment_result(
        _num(vat_base) * _num(vat_rate) / 100.0,
        label="НДС",
    )

    total = _validated_payment_result(
        _sum_amounts(
            customs_fee_amount,
            duty_amount,
            excise_amount,
            antidumping_amount,
            special_duties_total,
            vat,
            recycling_fee_total,
        ),
        label="итоговой суммы",
    )
    # VAT includes antidumping in its tax base.  When the antidumping amount is
    # unknown, the numeric VAT and total below are only partial arithmetic and
    # must not be exposed as final amounts.  Keep them under explicitly named
    # provisional fields for diagnostics while withholding every final signal.
    antidumping_pending = antidumping_status == "manual_review"
    source_binding_pending = bool(payment_review_reasons)
    final_payment_pending = antidumping_pending or source_binding_pending

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

    tnved_context = get_tnved_context_for_hs(hs_code)

    return {
        "status": "REVIEW_REQUIRED" if final_payment_pending else "OK",
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
            "vat_base": None if final_payment_pending else _round2(vat_base),
            "vat": None if final_payment_pending else _round2(vat),
            "vat_status": "manual_review" if final_payment_pending else "applied",
            "vat_base_provisional": _round2(vat_base) if final_payment_pending else None,
            "vat_provisional": _round2(vat) if final_payment_pending else None,
            "recycling_fee": _round2(recycling_fee_total),
            "total_payable": None if final_payment_pending else _round2(total),
            "total_payable_status": "withheld" if final_payment_pending else "final",
            "total_payable_provisional": _round2(total) if final_payment_pending else None,
        },
        "legal_basis": {
            "vat": vat_reason,
            "duty": (
                (
                    f"Структурированное правило: {duty_rule.type} "
                    f"(код {duty_rule.commodity_code}). Выбрано: {selected_rule}."
                )
                if duty_rule
                else (
                    f"Ввозная пошлина {duty_rate}% по коду ТН ВЭД/ЕТТ ЕАЭС."
                    if matched else
                    "Ставка пошлины не найдена в локальной базе; нулевой кандидат не подтверждён, "
                    "окончательный платёж удержан до ручной проверки."
                )
            ),
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
        "payment_review_reasons": payment_review_reasons,
        **({"hs_rate_source_candidate": {
            "status": "needs_review",
            "source_kind": "legacy_hs_rates",
            "valid_from": getattr(rate, "valid_from", None),
            "valid_to": getattr(rate, "valid_to", None),
            "source_revision": getattr(rate, "source_revision", ""),
            "source_url": getattr(rate, "source_url", ""),
            "source_evidence_verified": False,
            "legal_review_verified": False,
        }} if rate_source_binding_unverified else {}),
        **({"hs_rate_source_candidate": {
            "status": "missing",
            "source_kind": "legacy_hs_rates",
            "source_evidence_verified": False,
            "legal_review_verified": False,
        }} if rate_source_missing else {}),
        **({"duty_rule_source_candidate": {
            "status": "needs_review",
            "source_kind": "legacy_hs_duty_rules",
            "code": duty_rule.commodity_code,
            "rule_type": duty_rule.type,
            "source_evidence_verified": False,
            "legal_review_verified": False,
            "reason": "duty_rule_source_binding_unverified",
        }} if duty_rule_source_binding_unverified else {}),
        "geo": geo_meta,
        "tariff_preference": tariff_pref_meta,
        "recycling_fee": recycling_fee_meta,
    }


def compare_payment_scenarios(payload: dict[str, Any]) -> dict[str, Any]:
    """Сравнение 2–8 сценариев при общих экономических параметрах (что если другой ТН ВЭД)."""
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
    if isinstance(shared.get("_fx_rates"), dict):
        econ["_fx_rates"] = shared.get("_fx_rates")
    if shared.get("insurance") is not None:
        econ["insurance"] = float(shared["insurance"])
    if (shared.get("country") or "").strip():
        econ["country"] = str(shared["country"]).strip().upper()
    if shared.get("quantity") is not None:
        econ["quantity"] = float(shared["quantity"])

    out_scenarios: list[dict[str, Any]] = []
    first_total: float | None = None
    any_review_required = False

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
        raw_total = (res.get("breakdown") or {}).get("total_payable")
        total = float(raw_total) if raw_total is not None else None
        delta = (
            None
            if first_total is None or total is None
            else _round2(total - first_total)
        )
        if i == 0:
            first_total = total
        any_review_required = any_review_required or total is None or res.get("status") != "OK"
        tv = res.get("tnved_context") or {}
        out_scenarios.append(
            {
                "label": label,
                "hs_code": hs,
                "country": (merged.get("country") or None),
                "delta_total_vs_first_rub": delta,
                "total_payable": _round2(total) if total is not None else None,
                "duty": res["breakdown"]["duty"],
                "vat": res["breakdown"]["vat"],
                "excise": res["breakdown"]["excise"],
                "antidumping": res["breakdown"]["antidumping"],
                "duty_rate_applied": res["breakdown"]["duty_rate"],
                "vat_rate_applied": res["breakdown"]["vat_rate"],
                "data_quality": res.get("data_quality"),
                "payment_review_reasons": list(res.get("payment_review_reasons") or []),
                "tnved_title": (tv.get("title") or "")[:300] if isinstance(tv, dict) else "",
            }
        )

    return {
        "status": "REVIEW_REQUIRED" if any_review_required else "OK",
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
