"""Каскадный поиск строк ``non_tariff_measures`` по коду ТН ВЭД."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.tnved import NonTariffMeasure
from .hs_matching import normalize_hs_code


def build_measure_code_candidates(code: str) -> list[str]:
    """
    Все варианты ``commodity_code`` для поиска мер:
    точный 10-значный, усечения хвостовых нулей, префиксы 8/6/4/2 и паддинг до 10.
    """
    norm = normalize_hs_code(code)
    if not norm:
        return []

    code10 = norm.zfill(10)[:10]
    candidates: set[str] = set()
    candidates.add(code10)

    if len(norm) < 10:
        candidates.add(norm)
        candidates.add(norm.ljust(10, "0"))

    trimmed = code10
    while len(trimmed) > 2 and trimmed.endswith("0"):
        trimmed = trimmed[:-1]
        candidates.add(trimmed)
        candidates.add(trimmed.ljust(10, "0"))

    for length in (8, 6, 4, 2):
        if len(code10) >= length:
            prefix = code10[:length]
            candidates.add(prefix)
            candidates.add(prefix.ljust(10, "0"))

    candidates.add(code10[:2])
    return sorted((c for c in candidates if c and len(c) >= 2), key=lambda x: (-len(x), x))


def get_measures_for_code(
    code: str,
    db: Session,
    *,
    direction: str = "import",
) -> list[NonTariffMeasure]:
    """Каскадный поиск мер по всем префиксам кода с дедупликацией."""
    candidates = build_measure_code_candidates(code)
    if not candidates:
        return []

    query = db.query(NonTariffMeasure).filter(NonTariffMeasure.commodity_code.in_(candidates))
    if hasattr(NonTariffMeasure, "quality"):
        query = query.filter(
            (NonTariffMeasure.quality.is_(None)) | (NonTariffMeasure.quality != "noise")
        )
    if hasattr(NonTariffMeasure, "direction"):
        query = query.filter(NonTariffMeasure.direction == (direction or "import").strip().lower())

    rows = query.order_by(NonTariffMeasure.commodity_code.asc(), NonTariffMeasure.id.asc()).all()
    rows.sort(
        key=lambda m: (
            -len((m.commodity_code or "").rstrip("0")),
            m.commodity_code or "",
            m.id,
        )
    )

    seen: set[tuple[str, str]] = set()
    result: list[NonTariffMeasure] = []
    for m in rows:
        mtype = (m.measure_type or "").strip().lower()
        cc4 = (m.commodity_code or "")[:4]
        key = (mtype, cc4)
        if key in seen:
            continue
        seen.add(key)
        result.append(m)
    return result
