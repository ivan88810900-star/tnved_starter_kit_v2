"""Парсинг текстовых ставок import_duty в структурированные правила.

Поддерживаемые типы:
- ad_valorem:      "5%"
- specific:        "0,1 евро/кг", "2 USD за 1 л"
- combined_max:    "5%, но не менее 0,1 евро/кг"
- combined_min:    "5%, но не более 0,1 евро/кг"
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_PCT_RE = re.compile(r"(?P<pct>\d+(?:[.,]\d+)?)\s*%")
_AMOUNT_CUR_RE = re.compile(
    r"(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<currency>евро|eur|usd|доллар(?:а|ов)?(?:\s+сша)?)",
    re.IGNORECASE,
)
_UOM_RE = re.compile(
    r"(?:/|за\s*1\s*)(?P<uom>кг|kg|л|l|шт|pcs|м2|м3|т)\b",
    re.IGNORECASE,
)


def _to_float(num: str | None) -> float | None:
    if not num:
        return None
    return float(num.replace(",", "."))


def _norm_currency(cur: str | None) -> str:
    if not cur:
        return ""
    low = cur.lower().strip()
    if low in {"евро", "eur"}:
        return "EUR"
    if low.startswith("usd") or "доллар" in low:
        return "USD"
    return low.upper()


def _norm_uom(uom: str | None) -> str:
    if not uom:
        return ""
    low = uom.lower().strip()
    mapping = {
        "kg": "kg",
        "кг": "kg",
        "l": "l",
        "л": "l",
        "шт": "pcs",
        "pcs": "pcs",
        "м2": "m2",
        "м3": "m3",
        "т": "t",
    }
    return mapping.get(low, low)


@dataclass(slots=True)
class DutyRulePayload:
    type: str
    ad_valorem_pct: float | None = None
    specific_amount: float | None = None
    specific_currency: str = ""
    specific_uom: str = ""


class DutyParser:
    """Преобразует текстовую ставку в структуру hs_duty_rules."""

    @staticmethod
    def parse(raw: str | None) -> DutyRulePayload | None:
        text = (raw or "").strip()
        if not text or text in {"-", "—"}:
            return None

        pct_m = _PCT_RE.search(text)
        amt_m = _AMOUNT_CUR_RE.search(text)
        uom_m = _UOM_RE.search(text)

        pct = _to_float(pct_m.group("pct")) if pct_m else None
        amount = _to_float(amt_m.group("amount")) if amt_m else None
        currency = _norm_currency(amt_m.group("currency")) if amt_m else ""
        uom = _norm_uom(uom_m.group("uom")) if uom_m else ""

        has_pct = pct is not None
        has_specific = amount is not None and bool(currency)

        low = text.lower()
        has_min_keyword = "не менее" in low
        has_max_keyword = "не более" in low

        if has_pct and has_specific:
            # "не менее" => берем большее значение (combined_max)
            if has_min_keyword:
                return DutyRulePayload(
                    type="combined_max",
                    ad_valorem_pct=pct,
                    specific_amount=amount,
                    specific_currency=currency,
                    specific_uom=uom,
                )
            # "не более" => берем меньшее значение (combined_min)
            if has_max_keyword:
                return DutyRulePayload(
                    type="combined_min",
                    ad_valorem_pct=pct,
                    specific_amount=amount,
                    specific_currency=currency,
                    specific_uom=uom,
                )
            # Без ключевых слов оставляем безопасный дефолт для комбинированной ставки.
            return DutyRulePayload(
                type="combined_max",
                ad_valorem_pct=pct,
                specific_amount=amount,
                specific_currency=currency,
                specific_uom=uom,
            )

        if has_pct:
            return DutyRulePayload(type="ad_valorem", ad_valorem_pct=pct)

        if has_specific:
            return DutyRulePayload(
                type="specific",
                specific_amount=amount,
                specific_currency=currency,
                specific_uom=uom,
            )

        return None
