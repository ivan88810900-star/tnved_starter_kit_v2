"""
Сверка строки инвойса с локальными реестрами:

- нотификации ФСБ (fss_notifications), РЭС (reo_registry) — главы 84, 85;
- свидетельства о государственной регистрации СГР (sgr_certificates) — при признаках СГР в нетарифных мерах
  или типовых главах санитарного контроля (30, 33–35, 39 и др.).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models.core import FssNotification, ReoRegistryEntry, SgrCertificate
from ..models.tnved import NonTariffMeasure

_SKIP_BRAND = frozenset(
    {"", "отсутствует", "неизвестен", "—", "отсутствует.", "нет", "n/a", "na"}
)

# Главы ТН ВЭД, для которых часто требуется санитарно-эпидемиологический контроль / СГР (эвристика при отсутствии строк в БД нетарифки).
SGR_HEURISTIC_CHAPTERS: frozenset[str] = frozenset({"30", "33", "34", "35", "39", "40"})

SGR_RECOMMENDATION_FUZZY = (
    "Найдено действующее СГР на продукцию данного изготовителя со схожим описанием. "
    "Проверьте возможность применения (внесения артикула) или оформления письма-доверенности от заявителя."
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _article_from_item(item_data: dict[str, Any]) -> str:
    for k in ("article", "sku", "SKU", "Артикул"):
        v = str(item_data.get(k) or "").strip()
        if v:
            return v
    return ""


def _brand_for_match(attrs: dict[str, str], item_data: dict[str, Any]) -> str:
    b = (attrs.get("trademark") or item_data.get("brand") or "").strip()
    if _norm(b) in _SKIP_BRAND:
        return str(item_data.get("brand") or "").strip()
    return b


def _manufacturer_for_match(attrs: dict[str, str], item_data: dict[str, Any]) -> str:
    m = (attrs.get("manufacturer") or item_data.get("manufacturer") or "").strip()
    return m


def _category_keywords(item_data: dict[str, Any], attrs: dict[str, str]) -> list[str]:
    blob = " ".join(
        str(x)
        for x in (
            item_data.get("name_ru"),
            item_data.get("name_cn"),
            attrs.get("name"),
            attrs.get("purpose_and_tech"),
            item_data.get("usage"),
            item_data.get("material"),
        )
        if (x or "").strip()
    )
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]{4,}", blob)
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            out.append(w)
    return out[:14]


def _fss_score(row: FssNotification, article: str, kws: list[str]) -> int:
    n = (row.name or "").lower()
    s = 0
    art = (article or "").strip().lower()
    if art and art in n:
        s += 20
    if art and art in (row.number or "").lower():
        s += 25
    for kw in kws:
        if kw.lower() in n:
            s += 2
    return s


def _reo_score(row: ReoRegistryEntry, article: str, kws: list[str]) -> int:
    m = (row.model_name or "").lower()
    ch = (row.characteristics or "").lower()
    s = 0
    art = (article or "").strip().lower()
    if art and art in m:
        s += 25
    if art and art in ch:
        s += 10
    blob = m + " " + ch
    for kw in kws:
        if kw.lower() in blob:
            s += 2
    return s


def _pick_best_fss(rows: list[FssNotification], article: str, kws: list[str]) -> FssNotification | None:
    if not rows:
        return None
    scored = sorted(rows, key=lambda r: _fss_score(r, article, kws), reverse=True)
    return scored[0]


def _pick_best_reo(rows: list[ReoRegistryEntry], article: str, kws: list[str]) -> ReoRegistryEntry | None:
    if not rows:
        return None
    scored = sorted(rows, key=lambda r: _reo_score(r, article, kws), reverse=True)
    return scored[0]


def _format_expiry_status(expiry: datetime | None, status: str) -> str:
    st = (status or "").strip() or "—"
    if expiry is None:
        return f"Статус: {st} (срок не указан)"
    try:
        d = expiry.strftime("%Y-%m-%d")
    except Exception:
        d = str(expiry)
    return f"Действует до {d} ({st})"


def _format_sgr_issue_status(issue: datetime | None, status: str) -> str:
    st = (status or "").strip() or "—"
    if issue is None:
        return f"Статус: {st} (дата выдачи не указана)"
    try:
        d = issue.strftime("%Y-%m-%d")
    except Exception:
        d = str(issue)
    return f"Выдано {d}, статус: {st}"


def _ai_disambiguate_fss(
    candidates: list[FssNotification],
    *,
    product_context: str,
) -> FssNotification | None:
    if len(candidates) <= 1:
        return candidates[0] if candidates else None
    try:
        from .invoice_analyzer import _gemini_generate
    except Exception as e:
        logger.debug("registry AI pick: skip import: {}", e)
        return candidates[0]
    lines = []
    for i, r in enumerate(candidates[:8]):
        lines.append(f"{i}. №{r.number} | бренд={r.brand} | {r.name[:200]}")
    prompt = (
        "Выбери ОДИН индекс строки (0–7) наиболее подходящей нотификации ФСБ под товар из инвойса. "
        "Ответь строго JSON: {\"best_index\": <int>} без текста вокруг.\n\n"
        f"Товар (контекст): {product_context[:1200]}\n\nКандидаты:\n"
        + "\n".join(lines)
    )
    try:
        raw = _gemini_generate(prompt, max_output_tokens=128, temperature=0.0)
        m = re.search(r"\{[^}]+\}", raw)
        if not m:
            return candidates[0]
        obj = json.loads(m.group(0))
        idx = int(obj.get("best_index", 0))
        if 0 <= idx < len(candidates):
            return candidates[idx]
    except Exception as e:
        logger.warning("registry AI disambiguate FSS: {}", e)
    return candidates[0]


def _nt_requires_sgr(session: Session, commodity_code: str) -> bool:
    """Признак СГР / санитарно-эпидемиологического контроля в строках нетарифных мер по 10-значному коду."""
    rows = (
        session.query(NonTariffMeasure)
        .filter(NonTariffMeasure.commodity_code == commodity_code)
        .limit(40)
        .all()
    )
    for m in rows:
        if (m.measure_type or "").strip().lower() == "sgr":
            return True
        blob = f"{m.measure_type} {m.document_required} {m.description} {m.regulatory_act}".lower()
        if "сгр" in blob:
            return True
        if "санитарно-эпидемиолог" in blob or "санитарно эпидемиолог" in blob:
            return True
        if "299" in (m.regulatory_act or "") and ("санитар" in blob or "эпидемиолог" in blob):
            return True
    return False


def _should_search_sgr(session: Session, hs_code: str) -> bool:
    hs10 = re.sub(r"\D", "", hs_code or "")[:10]
    hs2 = hs10[:2] if len(hs10) >= 2 else ""
    if hs2 in SGR_HEURISTIC_CHAPTERS:
        return True
    if len(hs10) == 10:
        return _nt_requires_sgr(session, hs10)
    return False


def _sgr_na_block() -> dict[str, str]:
    return {
        "status": "Не применимо",
        "document_number": "—",
        "date_status": "—",
        "recommendation": "Сверка с реестром СГР для данного кода не активирована (нет признаков СГР в нетарифных мерах и код вне типовых глав санитарного контроля).",
    }


def _sgr_not_found_block() -> dict[str, str]:
    return {
        "status": "Не найдено",
        "document_number": "—",
        "date_status": "—",
        "recommendation": "В локальной базе СГР совпадений не найдено; проверьте номер в официальном реестре и полноту выгрузки (sync_sgr_registry).",
    }


def _sgr_score_exact(row: SgrCertificate, article: str, name_line: str) -> int:
    p = (row.product_name or "").lower()
    s = 0
    art = (article or "").strip().lower()
    if art and art in p:
        s += 40
    nl = (name_line or "").strip().lower()
    if nl and len(nl) > 6 and nl in p:
        s += 35
    if nl and len(nl) > 6 and p in nl:
        s += 25
    return s


def _sgr_score_fuzzy(row: SgrCertificate, kws: list[str], manuf_n: str, brand_n: str) -> int:
    p = (row.product_name or "").lower()
    s = 0
    rb = _norm(row.brand or "")
    rm = _norm(row.manufacturer or "")
    if brand_n and brand_n == rb:
        s += 25
    if manuf_n and manuf_n == rm:
        s += 30
    if manuf_n and manuf_n in rm:
        s += 15
    for kw in kws:
        if len(kw) > 3 and kw.lower() in p:
            s += 4
    return s


def lookup_sgr_registry(
    session: Session,
    item_data: dict[str, Any],
    attrs: dict[str, str],
    *,
    hs_code: str,
) -> dict[str, str]:
    if not _should_search_sgr(session, hs_code):
        return _sgr_na_block()

    brand_raw = _brand_for_match(attrs, item_data)
    brand_n = _norm(brand_raw)
    manuf_raw = _manufacturer_for_match(attrs, item_data)
    manuf_n = _norm(manuf_raw)
    article = _article_from_item(item_data)
    kws = _category_keywords(item_data, attrs)
    name_line = " ".join(
        x
        for x in (
            (item_data.get("name_ru") or "").strip(),
            (item_data.get("name_cn") or "").strip(),
            (attrs.get("name") or "").strip(),
        )
        if (x or "").strip()
    )[:400]

    rows_exact: list[SgrCertificate] = []
    if brand_n and brand_n not in _SKIP_BRAND:
        q = session.query(SgrCertificate).filter(func.lower(SgrCertificate.brand) == brand_n)
        conds: list[Any] = []
        if article:
            conds.append(SgrCertificate.product_name.ilike(f"%{article}%"))
        if name_line and len(name_line) > 5:
            conds.append(SgrCertificate.product_name.ilike(f"%{name_line[:120]}%"))
        if conds:
            rows_exact = q.filter(or_(*conds)).limit(15).all()

    best: SgrCertificate | None = None
    kind = "Не найдено"

    if rows_exact:
        best = sorted(rows_exact, key=lambda r: _sgr_score_exact(r, article, name_line), reverse=True)[0]
        if best and _sgr_score_exact(best, article, name_line) >= 25:
            kind = "Найдено точное совпадение"
        elif best:
            kind = "Найдено по бренду/составу"

    if not best and (brand_n and brand_n not in _SKIP_BRAND or manuf_n):
        fuzzy_conds: list[Any] = []
        if kws:
            fuzzy_conds = [SgrCertificate.product_name.ilike(f"%{kw}%") for kw in kws[:8]]
        qf = session.query(SgrCertificate)
        ident: list[Any] = []
        if brand_n and brand_n not in _SKIP_BRAND:
            ident.append(func.lower(SgrCertificate.brand) == brand_n)
        if manuf_n:
            ident.append(func.lower(SgrCertificate.manufacturer) == manuf_n)
            ident.append(SgrCertificate.manufacturer.ilike(f"%{manuf_raw}%"))
        if not ident:
            return _sgr_not_found_block()
        qf = qf.filter(or_(*ident))
        if fuzzy_conds:
            qf = qf.filter(or_(*fuzzy_conds))
        fz = qf.limit(15).all()
        if fz:
            best = sorted(fz, key=lambda r: _sgr_score_fuzzy(r, kws, manuf_n, brand_n), reverse=True)[0]
            kind = "Найдено по бренду/составу"

    if not best:
        return _sgr_not_found_block()

    if kind == "Найдено точное совпадение":
        rec = (
            "Совпадение по бренду и описанию/артикулу; сверьте полный состав и наименование в реестре СГР перед применением."
        )
    else:
        rec = SGR_RECOMMENDATION_FUZZY

    return {
        "status": kind,
        "document_number": (best.sgr_number or "").strip() or "—",
        "date_status": _format_sgr_issue_status(best.issue_date, best.status),
        "recommendation": rec[:4000],
    }


def lookup_state_registries(
    session: Session,
    item_data: dict[str, Any],
    attrs: dict[str, str],
    *,
    hs_code: str,
) -> dict[str, Any]:
    """
    Блок «Проверка по реестрам»: ФСБ/РЭС для глав 84–85; вложенный объект ``sgr`` — при активации сверки СГР.
    """
    sgr_block = lookup_sgr_registry(session, item_data, attrs, hs_code=hs_code)

    empty_fss_reo = {
        "status": "Не найдено",
        "document_number": "—",
        "date_status": "—",
        "recommendation": "—",
    }
    hs2 = re.sub(r"\D", "", hs_code or "")[:2]
    if hs2 not in ("84", "85"):
        return {**empty_fss_reo, "sgr": sgr_block}

    brand_raw = _brand_for_match(attrs, item_data)
    brand_n = _norm(brand_raw)
    article = _article_from_item(item_data)
    kws = _category_keywords(item_data, attrs)
    ctx = " ".join(
        x
        for x in (brand_raw, article, attrs.get("name"), item_data.get("name_ru"), item_data.get("usage"))
        if (x or "").strip()
    )[:2000]

    fss_rows: list[FssNotification] = []
    reo_rows: list[ReoRegistryEntry] = []

    if brand_n and brand_n not in _SKIP_BRAND:
        if article:
            fss_rows.extend(
                session.query(FssNotification)
                .filter(func.lower(FssNotification.brand) == brand_n)
                .filter(
                    or_(
                        FssNotification.name.ilike(f"%{article}%"),
                        FssNotification.number.ilike(f"%{article}%"),
                    )
                )
                .limit(15)
                .all()
            )
            reo_rows.extend(
                session.query(ReoRegistryEntry)
                .filter(func.lower(ReoRegistryEntry.brand) == brand_n)
                .filter(
                    or_(
                        ReoRegistryEntry.model_name.ilike(f"%{article}%"),
                        ReoRegistryEntry.characteristics.ilike(f"%{article}%"),
                    )
                )
                .limit(15)
                .all()
            )
        if not fss_rows and kws:
            conds = [FssNotification.name.ilike(f"%{kw}%") for kw in kws[:8]]
            fss_rows.extend(
                session.query(FssNotification)
                .filter(func.lower(FssNotification.brand) == brand_n)
                .filter(or_(*conds))
                .limit(15)
                .all()
            )
        if not reo_rows and kws:
            rconds = [
                or_(
                    ReoRegistryEntry.model_name.ilike(f"%{kw}%"),
                    ReoRegistryEntry.characteristics.ilike(f"%{kw}%"),
                )
                for kw in kws[:6]
            ]
            reo_rows.extend(
                session.query(ReoRegistryEntry)
                .filter(func.lower(ReoRegistryEntry.brand) == brand_n)
                .filter(or_(*rconds))
                .limit(15)
                .all()
            )
        if not fss_rows and brand_raw:
            like = f"%{brand_n}%"
            fss_rows.extend(
                session.query(FssNotification)
                .filter(func.lower(FssNotification.brand).like(like))
                .limit(15)
                .all()
            )
        if not reo_rows and brand_raw:
            like = f"%{brand_n}%"
            reo_rows.extend(
                session.query(ReoRegistryEntry)
                .filter(func.lower(ReoRegistryEntry.brand).like(like))
                .limit(15)
                .all()
            )

    fss_u = list({r.id: r for r in fss_rows}.values())
    reo_u = list({r.id: r for r in reo_rows}.values())

    best_fss: FssNotification | None = None
    best_reo: ReoRegistryEntry | None = None
    status_kind = "Не найдено"

    if fss_u:
        ranked = sorted(fss_u, key=lambda r: _fss_score(r, article, kws), reverse=True)
        if len(fss_u) > 3 and (article or kws):
            best_fss = _ai_disambiguate_fss(ranked[:8], product_context=ctx)
        else:
            best_fss = _pick_best_fss(fss_u, article, kws)
    if reo_u:
        best_reo = _pick_best_reo(reo_u, article, kws)

    if best_fss or best_reo:
        if article and (
            (best_fss and (article.lower() in (best_fss.name or "").lower() or article.lower() in (best_fss.number or "").lower()))
            or (best_reo and article.lower() in (best_reo.model_name or "").lower())
        ):
            status_kind = "Найден артикул"
        else:
            status_kind = "Найдено по бренду"

    if not best_fss and not best_reo:
        return {**empty_fss_reo, "sgr": sgr_block}

    doc_bits: list[str] = []
    date_bits: list[str] = []
    if best_fss:
        doc_bits.append(f"ФСБ: {best_fss.number}")
        date_bits.append("ФСБ: " + _format_expiry_status(best_fss.expiry_date, best_fss.status))
    if best_reo:
        doc_bits.append(f"РЭС: {best_reo.number}")
        date_bits.append("РЭС: " + _format_expiry_status(best_reo.expiry_date, best_reo.status))

    rec_parts: list[str] = []
    if status_kind == "Найдено по бренду" and article and best_fss:
        rec_parts.append(
            f"Торговая марка совпадает с нотификацией № {best_fss.number}; уточните соответствие модели и при необходимости подставьте артикул {article} в сопроводительных документах."
        )
    elif status_kind == "Найден артикул":
        rec_parts.append("Обнаружено совпадение по артикулу/модели; сверьте полное наименование с реестром перед применением.")
    else:
        rec_parts.append("Найдены записи по бренду; требуется ручная проверка соответствия типа товара.")

    return {
        "status": status_kind,
        "document_number": " | ".join(doc_bits) if doc_bits else "—",
        "date_status": " | ".join(date_bits) if date_bits else "—",
        "recommendation": " ".join(rec_parts).strip()[:4000],
        "sgr": sgr_block,
    }


def format_registry_check_excel(rc: Any) -> dict[str, str]:
    """Колонки Excel: ФСБ/РЭС + секция СГР."""
    base_keys = (
        "Проверка реестров: статус",
        "Проверка реестров: номер",
        "Проверка реестров: срок/статус",
        "Проверка реестров: рекомендация",
    )
    sgr_keys = (
        "Проверка реестров (СГР): статус",
        "Проверка реестров (СГР): номер",
        "Проверка реестров (СГР): дата/статус",
        "Проверка реестров (СГР): рекомендация",
    )
    if not isinstance(rc, dict):
        return {**dict.fromkeys(base_keys, "—"), **dict.fromkeys(sgr_keys, "—")}
    sg = rc.get("sgr") if isinstance(rc.get("sgr"), dict) else {}
    return {
        "Проверка реестров: статус": str(rc.get("status") or "—"),
        "Проверка реестров: номер": str(rc.get("document_number") or "—"),
        "Проверка реестров: срок/статус": str(rc.get("date_status") or "—"),
        "Проверка реестров: рекомендация": str(rc.get("recommendation") or "—"),
        "Проверка реестров (СГР): статус": str(sg.get("status") or "—"),
        "Проверка реестров (СГР): номер": str(sg.get("document_number") or "—"),
        "Проверка реестров (СГР): дата/статус": str(sg.get("date_status") or "—"),
        "Проверка реестров (СГР): рекомендация": str(sg.get("recommendation") or "—"),
    }
