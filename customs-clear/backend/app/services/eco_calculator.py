"""
Расчёт экологического сбора по тарифам из ``eco_fee_rates``.

Формула (как задано в ТЗ): сумма (руб) = вес (кг) × (норматив % / 100) × ставка (руб/кг).

При неполных данных по упаковке: эвристика по описанию товара (рулон / roll → полимерная пленка;
иначе → картон гофрированный). Если брутто ≤ нетто — сумма сбора 0 и поясняющее предупреждение.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models.core import EcoFeeRate

_AUTO_PACKAGING = frozenset(
    {
        "",
        "авто",
        "auto",
        "неизвестен",
        "неизвестно",
        "unknown",
        "—",
        "-",
    }
)


def _norm_hs_digits(raw: str) -> str:
    return re.sub(r"\D", "", (raw or "").strip())[:10]


def _normalize_packaging_material(raw: str) -> str:
    s = (raw or "").strip().lower().replace("ё", "е")
    if not s:
        return "картон гофрированный"
    if "полимерн" in s and "плен" in s:
        return "полимерная пленка"
    if "гофрирован" in s or "гофр" in s:
        return "картон гофрированный"
    if any(x in s for x in ("картон", "короб")):
        return "картон гофрированный"
    if "бумаг" in s or "макулатур" in s:
        return "бумага"
    if any(x in s for x in ("пластик", "полиэтилен", "пэт", "pet", "пп", "полипропилен", "пленк", "плёнк")):
        return "пластик"
    return s[:64]


def _description_suggests_roll_form(description: str) -> bool:
    t = (description or "").lower().replace("ё", "е")
    if not t.strip():
        return False
    if "рулон" in t:
        return True
    if re.search(r"\brolls?\b", t, flags=re.IGNORECASE):
        return True
    if re.search(r"\breels?\b", t, flags=re.IGNORECASE):
        return True
    return False


def _infer_packaging_material(*, product_description: str | None, packaging_material: str | None) -> str:
    """
    Явно переданный (не авто) материал — нормализуем.
    Иначе: рулон / roll / reel в описании → ``полимерная пленка``; во всех прочих случаях → ``картон гофрированный``.
    """
    raw = (packaging_material or "").strip()
    if raw and raw.lower() not in _AUTO_PACKAGING:
        return _normalize_packaging_material(raw)
    if _description_suggests_roll_form(product_description or ""):
        return "полимерная пленка"
    return "картон гофрированный"


def _pick_rate(
    session: Session,
    *,
    hs10: str,
    material_type: str,
    calendar_year: int,
) -> EcoFeeRate | None:
    """
    Выбор строки тарифа: ``valid_from_year`` ≤ год отчёта, наиболее длинный совпавший ``hs_code_prefix``,
    точное совпадение ``material_type``; при отсутствии — то же для префикса «все товары» (пустой префикс).
    """
    hs10 = _norm_hs_digits(hs10)
    if not hs10:
        return None

    rows = (
        session.query(EcoFeeRate)
        .filter(
            EcoFeeRate.valid_from_year <= int(calendar_year),
            EcoFeeRate.material_type == material_type,
        )
        .all()
    )
    best: EcoFeeRate | None = None
    best_plen = -1
    best_y = -1
    for r in rows:
        p = (r.hs_code_prefix or "").strip()
        if p and not hs10.startswith(p):
            continue
        plen = len(p)
        vy = int(r.valid_from_year)
        if plen > best_plen or (plen == best_plen and vy > best_y):
            best = r
            best_plen = plen
            best_y = vy
    return best


def _pick_packaging_rate(
    session: Session,
    *,
    hs10: str,
    material_canon: str,
    calendar_year: int,
) -> tuple[EcoFeeRate | None, str]:
    """Подбор ставки для упаковки с запасными типами материала (как в РОП: плёнка ≈ полимер)."""
    candidates: list[str] = [material_canon]
    if material_canon == "полимерная пленка":
        candidates.extend(["пластик", "картон гофрированный", "картон", "бумага"])
    elif material_canon == "картон гофрированный":
        candidates.extend(["картон", "бумага"])
    elif material_canon == "пластик":
        candidates.extend(["полимерная пленка", "картон гофрированный", "картон"])
    elif material_canon not in ("бумага", "картон", "товар"):
        candidates.extend(["картон гофрированный", "картон", "бумага"])

    seen: set[str] = set()
    for m in candidates:
        if m in seen:
            continue
        seen.add(m)
        r = _pick_rate(session, hs10=hs10, material_type=m, calendar_year=calendar_year)
        if r is not None:
            return r, m
    return None, material_canon


def _amount_rub(weight_kg: float, rate: EcoFeeRate | None) -> tuple[float, dict[str, Any]]:
    if weight_kg <= 0 or rate is None:
        return 0.0, {}
    n = float(rate.normative_percent or 0.0) / 100.0
    r = float(rate.rate_rub_per_kg or 0.0)
    amt = round(weight_kg * n * r, 2)
    detail = {
        "weight_kg": round(weight_kg, 6),
        "normative_percent": float(rate.normative_percent),
        "rate_rub_per_kg": float(rate.rate_rub_per_kg),
        "hs_code_prefix": rate.hs_code_prefix or "",
        "material_type": rate.material_type,
        "valid_from_year": int(rate.valid_from_year),
    }
    return amt, detail


class EcoFeeCalculator:
    """Расчёт экосбора за товар и упаковку по БД ``eco_fee_rates``."""

    def __init__(self, db_session: Session) -> None:
        self._session = db_session

    def calculate_fee(
        self,
        hs_code: str,
        net_weight_kg: float | None,
        gross_weight_kg: float | None,
        packaging_material: str | None = None,
        *,
        product_description: str | None = None,
        calendar_year: int | None = None,
    ) -> dict[str, Any]:
        year = int(calendar_year or datetime.utcnow().year)
        hs10 = _norm_hs_digits(hs_code)
        net = float(net_weight_kg) if net_weight_kg is not None else None
        gross = float(gross_weight_kg) if gross_weight_kg is not None else None
        warnings: list[str] = []

        if net is None or gross is None:
            return {
                "year": year,
                "hs_code": hs10,
                "net_weight_kg": net,
                "gross_weight_kg": gross,
                "packaging_weight_kg": None,
                "product": None,
                "packaging": None,
                "total_eco_fee_rub": 0.0,
                "warnings": ["Недостаточно данных по нетто/брутто для расчёта упаковки и сбора."],
            }

        if net < 0 or gross < 0:
            warnings.append("Отрицательный вес игнорируется в расчёте.")
            net = max(0.0, net)
            gross = max(0.0, gross)

        mat_pack = _infer_packaging_material(
            product_description=product_description,
            packaging_material=packaging_material,
        )

        if gross <= net:
            warnings.append("Вес упаковки равен нулю или не указан корректно.")
            return {
                "year": year,
                "hs_code": hs10,
                "net_weight_kg": round(net, 6),
                "gross_weight_kg": round(gross, 6),
                "packaging_weight_kg": 0.0,
                "packaging_material": mat_pack,
                "product": {"amount_rub": 0.0, "rate": None},
                "packaging": {"amount_rub": 0.0, "rate": None},
                "total_eco_fee_rub": 0.0,
                "warnings": warnings,
            }

        pack_w = gross - net
        rate_goods = _pick_rate(self._session, hs10=hs10, material_type="товар", calendar_year=year)
        rate_pack, pack_rate_label = _pick_packaging_rate(
            self._session, hs10=hs10, material_canon=mat_pack, calendar_year=year
        )

        amt_goods, det_goods = _amount_rub(net, rate_goods)
        amt_pack, det_pack = _amount_rub(pack_w, rate_pack)
        if det_pack:
            det_pack = {**det_pack, "matched_material_type": pack_rate_label}

        total = round(amt_goods + amt_pack, 2)

        return {
            "year": year,
            "hs_code": hs10,
            "net_weight_kg": round(net, 6),
            "gross_weight_kg": round(gross, 6),
            "packaging_weight_kg": round(pack_w, 6),
            "packaging_material": mat_pack,
            "product": {"amount_rub": amt_goods, "rate": det_goods if det_goods else None},
            "packaging": {"amount_rub": amt_pack, "rate": det_pack if det_pack else None},
            "total_eco_fee_rub": total,
            "warnings": warnings,
        }
