"""Форматирование ставок пошлины/акциза для UI (ответ, не обоснование)."""

from __future__ import annotations

import re

from ..db import SessionLocal
from ..models.core import HsRate
from .normative_store import find_rate_for_hs
from .payment_engine import _find_duty_rule_for_hs

EXCISE_LIKELY_CHAPTERS: frozenset[str] = frozenset({"22", "24", "27", "30", "87"})


def _digits(code: str) -> str:
    return "".join(c for c in (code or "") if c.isdigit())


def _format_duty_simple(raw: str) -> str:
    t = (raw or "").strip()
    if not t:
        return ""
    low = t.lower()
    if "пошлина:" in low and "ндс:" in low and not re.search(r"\d", t):
        return ""
    if low in {"пошлина:", "ндс:", "пошлина", "ндс"}:
        return ""
    if "%" in t or "eur" in low or "€" in t:
        return re.sub(r"\s+", " ", t).replace(" %", "%")
    try:
        num = float(t.replace(",", ".").replace("%", "").strip())
        return f"{int(num) if num == int(num) else num:g}%"
    except ValueError:
        return t


def resolve_excise_for_hs(hs_code: str) -> tuple[str, float, str]:
    rate, _ = find_rate_for_hs(hs_code)
    if rate and (rate.excise_type or "none") not in ("", "none"):
        return str(rate.excise_type), float(rate.excise_value or 0.0), (rate.excise_basis or "")

    d = _digits(hs_code)
    with SessionLocal() as db:
        for length in (8, 6, 4):
            if len(d) < length:
                continue
            pref10 = d[:length].ljust(10, "0")
            row = db.query(HsRate).filter(HsRate.hs_code == pref10).first()
            if row and (row.excise_type or "none") not in ("", "none"):
                return str(row.excise_type), float(row.excise_value or 0.0), (row.excise_basis or "")

    if len(d) >= 2 and d[:2] in EXCISE_LIKELY_CHAPTERS:
        return "needs_review", 0.0, ""
    return "none", 0.0, ""


def format_excise_display(excise_type: str, excise_value: float, excise_basis: str = "") -> str:
    t = (excise_type or "none").lower()
    if t == "needs_review":
        return "Уточните ставку"
    if t in ("", "none"):
        return ""
    if t == "percent":
        return f"{excise_value:g}%"
    if t == "fixed":
        basis_low = (excise_basis or "").lower()
        if "руб/л" in basis_low or "rub/l" in basis_low or excise_value < 500:
            return f"{excise_value:g} ₽/л"
        return f"{excise_value:g} ₽"
    if t == "combined":
        return f"{excise_value:g} ₽ (комб.)"
    return f"{excise_value:g}"


def format_duty_rule_label(hs_code: str, import_duty: str = "") -> str:
    rule, _ = _find_duty_rule_for_hs(hs_code)
    if rule is not None:
        ad = getattr(rule, "ad_valorem_pct", None)
        spec = getattr(rule, "specific_amount", None)
        cur = (getattr(rule, "specific_currency", None) or "EUR").strip() or "EUR"
        uom = (getattr(rule, "specific_uom", None) or "л").strip() or "л"
        rtype = (getattr(rule, "type", None) or "ad_valorem").lower()

        if ad is not None and spec is not None and float(spec) > 0:
            return f"{float(ad):g}%, но не менее {float(spec):g} {cur}/{uom}"
        if rtype == "specific" and spec is not None and float(spec) > 0:
            return f"{float(spec):g} {cur}/{uom}"
        if ad is not None and float(ad) > 0:
            return f"{float(ad):g}%"

    duty = _format_duty_simple(import_duty)
    if not duty:
        hs_rate, _ = find_rate_for_hs(hs_code)
        if hs_rate:
            duty = _format_duty_simple(str(hs_rate.duty_rate or ""))
    return duty or "—"
