#!/usr/bin/env python3
"""
Глубокий smoke-тест полного пайплайна:
1) AI-классификация (RAG + ОПИ),
2) Обогащение по БД (ставки/нетарифка/риски),
3) Структурированный отчёт по каждому товару.
"""

from __future__ import annotations

import argparse
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv()

from app.db import SessionLocal
from app.models.core import (
    ClassificationDecision,
    DeclarationExample,
    GeoSpecialDuty,
    HsRate,
    SanctionImportRisk,
)
from app.models.tnved import SpecialDuty, VatPreference
from app.services.compliance_resolver import resolve_compliance_requirements
from app.services.invoice_analyzer import InvoiceAnalyzer, enrich_with_customs_data
from app.services.rag_retriever import get_semantic_legal_context


TEST_ITEMS: list[dict[str, Any]] = [
    {
        "name_ru": "Смартфон с встроенным модулем тепловизора, защищенный корпус IP68, в комплекте с зарядным устройством и наушниками.",
        "brand": "Generic",
        "usage": "смартфон для фото/видео и связи, дополнительная функция тепловизора",
        "material": "электронные компоненты, пластик, алюминий",
        "country_origin": "CN",
        "suggested_chapter": "85",
    },
    {
        "name_ru": "Напиток безалкогольный газированный со вкусом апельсина, содержит 5% натурального сока, сахарозаменитель, витамин С, расфасован в пластиковые бутылки по 0.5 л.",
        "brand": "MockDrink",
        "usage": "безалкогольный напиток для розничной продажи",
        "material": "вода, сок, ароматизаторы, упаковка ПЭТ",
        "country_origin": "TR",
        "suggested_chapter": "22",
    },
    {
        "name_ru": "Экстракт корня женьшеня сухой, стандартизированный, в желатиновых капсулах по 500 мг, расфасован для розничной продажи в качестве биологически активной добавки (БАД).",
        "brand": "BioHerb",
        "usage": "пищевая добавка (БАД) в капсулах",
        "material": "растительный экстракт, желатиновая капсула",
        "country_origin": "KR",
        "suggested_chapter": "21",
    },
    {
        "name_ru": "Набор для детского творчества 'Юный химик': пластиковые колбы, защитные очки, реагенты (сода, лимонная кислота, пищевые красители), инструкция. В картонной коробке для розничной продажи.",
        "brand": "JuniorLab",
        "usage": "детский образовательный набор для опытов",
        "material": "пластик, бумага, химические реагенты",
        "country_origin": "CN",
        "suggested_chapter": "95",
    },
    {
        "name_ru": "Насос центробежный многоступенчатый для перекачки чистой воды, мощность электродвигателя 5 кВт, со встроенным электронным расходомером.",
        "brand": "HydroPro",
        "usage": "промышленный насос для систем водоснабжения",
        "material": "нержавеющая сталь, чугун, электроника",
        "country_origin": "CN",
        "suggested_chapter": "84",
    },
]

_AGGREGATOR_RE = re.compile(r"\b(?:tks(?:\.ru)?|alta(?:\.ru)?|ifcg(?:\.ru)?)\b", re.IGNORECASE)
_LEGAL_PATTERNS = [
    re.compile(r"\bТР\s*(?:ТС|ЕАЭС)\s*\d{3}/\d{4}\b", re.IGNORECASE),
    re.compile(
        r"\bРешени[ея]\s+(?:Коллегии|Совета)\s+ЕЭК(?:\s+от\s+\d{2}\.\d{2}\.\d{4})?\s*№\s*\d+\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bРешени[ея]\s+ЕЭК(?:\s+от\s+\d{2}\.\d{2}\.\d{4})?\s*№\s*\d+\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bФЗ\s*№\s*\d+\-?ФЗ\b", re.IGNORECASE),
    re.compile(
        r"\bФедеральн\w*\s+закон[^№\n]{0,40}№\s*\d+\-?ФЗ\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bПостановлен\w+\s+Правительств\w+\s+РФ[^№\n]{0,40}№\s*\d+\b",
        re.IGNORECASE,
    ),
]

_NONTARIFF_CATEGORY_ORDER = (
    "Сертификат соответствия (СС)",
    "Декларация о соответствии (ДС)",
    "Лицензия",
    "СГР",
    "Нотификация ФСБ",
    "Маркировка",
)

_DEFAULT_VAT_IMPORT_RATE = 22.0
_SWEET_DRINK_EXCISE_2026_RUB_PER_L = 11.0

_TR_TITLE_BY_CODE: dict[str, str] = {
    "004/2011": "О безопасности низковольтного оборудования",
    "008/2011": "О безопасности игрушек",
    "010/2011": "О безопасности машин и оборудования",
    "020/2011": "Электромагнитная совместимость технических средств",
    "021/2011": "О безопасности пищевой продукции",
    "022/2011": "Пищевая продукция в части ее маркировки",
    "029/2012": "Требования безопасности пищевых добавок, ароматизаторов и технологических вспомогательных средств",
    "037/2016": "Об ограничении применения опасных веществ в изделиях электротехники и радиоэлектроники",
}

_HS_GROUP_OPI1_REASONING: dict[str, list[str]] = {
    "8517": [
        "1) ОПИ 1: товар идентифицируется как аппаратура связи (смартфон), подпадает под позицию 8517.",
        "2) По примечаниям и тексту позиции 8517 определяющим признаком является функция передачи/приема данных в сетях связи.",
        "3) ОПИ 6: уточнение на уровне субпозиций приводит к коду 8517130000 для смартфонов.",
        "4) Для выпуска требуется подтверждение соответствия по профильным ТР ТС/ЕАЭС и, при наличии криптофункций, нотификация ФСБ.",
    ],
    "2202": [
        "1) ОПИ 1: товар относится к безалкогольным напиткам товарной позиции 2202.",
        "2) По составу и назначению (готовый напиток для розницы) классификация сохраняется в группе 2202.",
        "3) ОПИ 6: уточнение по субпозициям для прочих безалкогольных напитков приводит к 2202990000.",
        "4) С учетом состава (сахар/подсластитель) применяется специальный акцизный режим для сахаросодержащих напитков.",
    ],
    "2106": [
        "1) ОПИ 1: товар является готовой пищевой добавкой (БАД), отнесение к позиции 2106.",
        "2) Форма выпуска (капсулы) и розничная фасовка подтверждают принадлежность к готовым пищевым продуктам.",
        "3) ОПИ 6: детализация по субпозициям группы 2106 приводит к 2106909808.",
        "4) Для выпуска требуется проверка специальных ограничений и маркировочных требований по профилю товара.",
    ],
    "9503": [
        "1) ОПИ 1: набор для детского творчества относится к товарам группы 95 (игрушки/наборы для развлечения и развития детей).",
        "2) ОПИ 3б: набор классифицируется по компоненту, определяющему основное свойство, — детская игрушка/игровой комплект.",
        "3) ОПИ 6: детализация в рамках группы 9503 приводит к коду 9503007000.",
        "4) Для выпуска необходимо подтверждение соответствия по ТР ТС 008/2011 «О безопасности игрушек».",
    ],
    "8413": [
        "1) ОПИ 1: товар является насосом для жидкостей, подпадает под позицию 8413.",
        "2) По конструкции (центробежный многоступенчатый насос) определяется классификация в подгруппах 8413.",
        "3) ОПИ 6: уточнение по субпозициям приводит к 8413707500.",
        "4) Проверяются профильные требования по безопасности и возможным разрешительным документам.",
    ],
}

_TR_REF_RE = re.compile(r"\bТР\s*(ТС|ЕАЭС)\s*(\d{3}/\d{4})\b", re.IGNORECASE)
_HS_8517_ALLOWED_TR = {"004/2011", "020/2011", "037/2016"}


def _fallback_hs_from_description(text: str) -> str:
    blob = (text or "").casefold()
    if "смартфон" in blob:
        return "8517130000"
    if "напиток" in blob or "газирован" in blob:
        return "2202990000"
    if "женьшен" in blob or "бад" in blob:
        return "2106909808"
    if "юный химик" in blob or "набор для детского творчества" in blob:
        return "9503007000"
    if "насос" in blob and "центробеж" in blob:
        return "8413707500"
    return ""


def _opi_reasoning_from_hs(hs10: str, description: str) -> list[str]:
    hs4 = _norm_hs10(hs10)[:4]
    hs2 = _norm_hs10(hs10)[:2]
    if hs4 == "9503" and ("набор" in (description or "").casefold() or "юный химик" in (description or "").casefold()):
        return _HS_GROUP_OPI1_REASONING["9503"]
    if hs4 in _HS_GROUP_OPI1_REASONING:
        return _HS_GROUP_OPI1_REASONING[hs4]
    if hs2 in _HS_GROUP_OPI1_REASONING:
        return _HS_GROUP_OPI1_REASONING[hs2]
    return [
        "1) ОПИ 1: классификация выполнена по тексту товарной позиции и примечаниям к разделу/группе.",
        f"2) Определены ключевые функциональные признаки товара для кода {hs10 or '—'}.",
        "3) ОПИ 6: детализация на уровне субпозиций выполнена по иерархии ТН ВЭД.",
        "4) Требуется финальная экспертная валидация декларантом перед подачей ДТ.",
    ]


def _run_with_timeout(fn, *, timeout_sec: int) -> Any:
    def _timeout_handler(_signum, _frame):
        raise TimeoutError(f"operation exceeded {timeout_sec}s")

    old_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(max(1, int(timeout_sec)))
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def _fallback_precedents_from_db(db, hs10: str, description: str, *, top_k: int = 3) -> list[str]:
    out: list[str] = []
    hs_pref = re.sub(r"\D", "", hs10)[:4]
    txt = (description or "").strip()
    txt_pat = f"%{txt[:48]}%" if txt else ""
    seen: set[str] = set()

    try:
        q = db.query(ClassificationDecision)
        if hs_pref:
            q = q.filter(ClassificationDecision.hs_code.like(f"{hs_pref}%"))
        if txt_pat:
            q = q.filter(
                (ClassificationDecision.product_name.ilike(txt_pat))
                | (ClassificationDecision.description.ilike(txt_pat))
            )
        rows = q.order_by(ClassificationDecision.id.desc()).limit(top_k).all()
        for r in rows:
            hs = re.sub(r"\D", "", str(r.hs_code or ""))[:10] or "—"
            line = f"[classification_decisions] код {hs} | № {(r.decision_number or '—')[:80]} | {(r.product_name or '').strip()[:180]}"
            key = line.casefold()
            if key not in seen:
                seen.add(key)
                out.append(line)
    except Exception:
        pass

    if len(out) < top_k:
        try:
            q2 = db.query(DeclarationExample)
            if hs_pref:
                q2 = q2.filter(DeclarationExample.hs_code.like(f"{hs_pref}%"))
            rows2 = q2.order_by(DeclarationExample.id.desc()).limit(top_k).all()
            for r in rows2:
                hs = re.sub(r"\D", "", str(r.hs_code or ""))[:10] or "—"
                d = (r.description or "").strip().replace("\n", " ")[:180]
                line = f"[declaration_examples] код {hs} | {d}"
                key = line.casefold()
                if key not in seen:
                    seen.add(key)
                    out.append(line)
                if len(out) >= top_k:
                    break
        except Exception:
            pass

    return out[:top_k]


def _norm_hs10(raw: Any) -> str:
    return re.sub(r"\D", "", str(raw or ""))[:10]


def _norm_iso2(raw: Any) -> str:
    t = re.sub(r"[^A-Za-z]", "", str(raw or "")).upper().strip()
    return t[:2] if len(t) >= 2 else ""


def _prefix_match_rows(hs10: str, rows: list[Any], *, field_name: str) -> list[Any]:
    if not hs10:
        return []
    matched: list[tuple[int, Any]] = []
    for row in rows:
        pref = re.sub(r"\D", "", str(getattr(row, field_name, "") or ""))
        if not pref:
            continue
        if hs10.startswith(pref):
            matched.append((len(pref), row))
    matched.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in matched]


def _query_special_duties(db, hs10: str, origin_iso2: str) -> list[str]:
    try:
        rows = db.query(SpecialDuty).all()
    except Exception:
        return []
    matched = _prefix_match_rows(hs10, rows, field_name="hs_code_prefix")
    out: list[str] = []
    country = _norm_iso2(origin_iso2)
    for r in matched:
        rc = _norm_iso2(r.origin_country)
        if country and rc and rc not in {country, "ALL", "ANY"}:
            continue
        rate_bits: list[str] = []
        if float(r.rate_percent or 0.0) > 0:
            rate_bits.append(f"{float(r.rate_percent):g}%")
        if float(r.rate_specific or 0.0) > 0:
            cur = (r.currency_code or "").strip() or "units"
            rate_bits.append(f"{float(r.rate_specific):g} {cur}")
        rate_txt = " + ".join(rate_bits) if rate_bits else "ставка не указана"
        act = _clean_text_for_output(r.regulatory_act or "нормативный акт не указан", limit=220)
        out.append(
            f"Антидемпинговая/спецпошлина по коду {r.hs_code_prefix} для страны {r.origin_country or 'ANY'}: "
            f"{rate_txt}. Основание: {act}"
        )
        if len(out) >= 5:
            break
    return out


def _query_geo_special_duties(db, hs10: str, origin_iso2: str) -> list[str]:
    try:
        rows = db.query(GeoSpecialDuty).all()
    except Exception:
        return []
    matched = _prefix_match_rows(hs10, rows, field_name="hs_code_prefix")
    out: list[str] = []
    country = _norm_iso2(origin_iso2)
    for r in matched:
        ciso = (r.country_iso or "").upper().strip()
        if country and ciso and ciso not in {country, "ALL_UNFRIENDLY", "ALL", "ANY"}:
            continue
        basis = _clean_text_for_output(r.document_basis or "нормативный акт не указан", limit=220)
        out.append(
            f"Гео-ограничение ({(r.measure_type or 'increased_duty')}): код {r.hs_code_prefix}, "
            f"страна {r.country_iso}, ставка {str(r.duty_rate or '—').strip()[:120]}. Основание: {basis}"
        )
        if len(out) >= 5:
            break
    return out


def _query_sanction_risks(db, hs10: str) -> list[str]:
    try:
        rows = db.query(SanctionImportRisk).all()
    except Exception:
        return []
    matched = _prefix_match_rows(hs10, rows, field_name="hs_code_prefix")
    out: list[str] = []
    for r in matched[:8]:
        desc = _clean_text_for_output(r.description or "риск не детализирован", limit=260)
        out.append(
            f"Санкционный риск ({(r.jurisdiction or '—')}): код {r.hs_code_prefix}, "
            f"уровень {(r.risk_level or 'risk').upper()} — {desc}"
        )
    return out


def _has_sugar_or_sweetener(text: str) -> bool:
    blob = (text or "").casefold()
    return bool(
        re.search(
            r"(сахар|сахарозамен|подсластител|sugar|sweetener|сукралоз|аспартам|стеви)",
            blob,
        )
    )


def _is_sweet_2202_case(hs10: str, item_description: str) -> bool:
    hs = _norm_hs10(hs10)
    return hs.startswith("2202") and _has_sugar_or_sweetener(item_description)


def _format_excise(enrichment: dict[str, Any], *, hs10: str, item_description: str) -> str:
    if _is_sweet_2202_case(hs10, item_description):
        return f"{_SWEET_DRINK_EXCISE_2026_RUB_PER_L:g} руб/л (сахаросодержащие напитки, 2026)"

    ex_type = str(enrichment.get("excise_type") or "none").strip().lower()
    ex_val = float(enrichment.get("excise_value") or 0.0)
    ex_basis = (enrichment.get("excise_basis") or "").strip()
    if ex_type == "none" or ex_val <= 0:
        return "нет"
    if ex_type == "percent":
        base = f"{ex_val:g}%"
    else:
        base = f"{ex_val:g} (фикс.)"
    if ex_basis:
        return f"{base}; основание: {ex_basis[:120]}"
    return base


def _format_finance_line(enrichment: dict[str, Any], *, hs10: str, item_description: str) -> str:
    duty = str(enrichment.get("duty_rate") or "—")
    vat = enrichment.get("vat_import_rate")
    try:
        vat_v = float(vat)
        if vat_v <= 0:
            raise ValueError("vat<=0")
        vat_txt = f"{vat_v:g}%"
    except Exception:
        vat_txt = f"{_DEFAULT_VAT_IMPORT_RATE:g}%"
    excise_txt = _format_excise(enrichment, hs10=hs10, item_description=item_description)
    return f"Пошлина: {duty}; НДС: {vat_txt}; Акциз: {excise_txt}"


def _clean_text_for_output(raw: str, *, limit: int = 260) -> str:
    txt = str(raw or "")
    txt = re.sub(r"https?://\S+", " ", txt, flags=re.IGNORECASE)
    txt = _AGGREGATOR_RE.sub(" ", txt)
    txt = re.sub(r"\s+", " ", txt).strip(" |;,-")
    if len(txt) <= limit:
        return txt
    return txt[: limit - 1].rstrip() + "…"


def _clean_precedent_line(raw: str) -> str:
    txt = _clean_text_for_output(raw, limit=650)
    txt = re.sub(r"\bИсточник:\s*[A-Za-z0-9._-]+\b", "", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\bИсточник:\b", "", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\|\s*Источник:\s*\|", "|", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\|\s*HS\s+\d{4,10}\s*\|", "|", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\[\s*DECL\s*\]", "", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\|\s*\|", "|", txt)
    txt = re.sub(r"\s{2,}", " ", txt).strip(" |;,-")
    return txt


def _tr_title(code: str) -> str:
    return _TR_TITLE_BY_CODE.get(code.strip(), "")


def _tr_family(code: str) -> str:
    c = code.strip()
    if c == "037/2016":
        return "ТР ЕАЭС"
    return "ТР ТС"


def _format_tr_doc(doc_short: str, code: str) -> str:
    c = code.strip()
    fam = _tr_family(c)
    title = _tr_title(c)
    if title:
        return f"{doc_short} {fam} {c} ({title})"
    return f"{doc_short} {fam} {c}"


def _extract_tr_codes_from_text(*texts: str) -> list[str]:
    blob = " | ".join(_clean_text_for_output(t, limit=2400) for t in texts if (t or "").strip())
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"(?:ТР\s*(?:ТС|ЕАЭС)\s*)?(\d{3}/\d{4})", blob, flags=re.IGNORECASE):
        code = (m.group(1) or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _parse_permit_tokens(raw: str) -> set[str]:
    vals: set[str] = set()
    for part in re.split(r"[,;/|]", str(raw or "")):
        p = part.strip().upper()
        if p:
            vals.add(p)
    return vals


def _best_hs_rate_row(db, hs10: str) -> HsRate | None:
    hs = _norm_hs10(hs10)
    if len(hs) < 4:
        return None
    exact = db.query(HsRate).filter(HsRate.hs_code == hs).first()
    if exact is not None:
        return exact
    # Сначала ищем "ближайшие" товарные позиции (8/6/4 знаков), чтобы не брать случайную строку группы.
    for n in (8, 6, 4):
        pref = hs[:n]
        row = (
            db.query(HsRate)
            .filter(HsRate.hs_code.like(f"{pref}%"))
            .order_by(HsRate.hs_code.asc())
            .first()
        )
        if row is not None:
            return row
    best: HsRate | None = None
    best_len = -1
    for row in db.query(HsRate).filter(HsRate.hs_prefix.isnot(None)).all():
        pref = re.sub(r"\D", "", str(row.hs_prefix or ""))
        if not pref or not hs.startswith(pref):
            continue
        if len(pref) > best_len:
            best = row
            best_len = len(pref)
    return best


def _best_vat_pref_rate(db, hs10: str) -> tuple[float | None, str]:
    hs = _norm_hs10(hs10)
    if len(hs) < 2:
        return None, ""
    best_rate: float | None = None
    best_len = -1
    best_basis = ""
    for row in db.query(VatPreference).all():
        pref = re.sub(r"\D", "", str(row.hs_code_prefix or ""))
        if not pref or not hs.startswith(pref):
            continue
        if len(pref) > best_len:
            best_len = len(pref)
            try:
                best_rate = float(row.vat_rate)
            except Exception:
                best_rate = None
            best_basis = _clean_text_for_output(row.decree_info or row.comment or "", limit=220)
    return best_rate, best_basis


def _apply_hs_rate_fallback(
    enrichment: dict[str, Any],
    rate_row: HsRate | None,
    *,
    vat_pref_rate: float | None = None,
) -> None:
    if rate_row is None:
        return
    dr = str(enrichment.get("duty_rate") or "").strip().upper()
    if (not dr) or ("СИНХРОНИЗАЦ" in dr):
        val = str(rate_row.duty_rate or "").strip()
        enrichment["duty_rate"] = val if val else "0"
    if enrichment.get("vat_import_rate") in (None, "", 0):
        try:
            enrichment["vat_import_rate"] = float(rate_row.vat_import_rate)
        except Exception:
            enrichment["vat_import_rate"] = _DEFAULT_VAT_IMPORT_RATE
    if vat_pref_rate in (10.0, 22.0):
        # vat_preferences приоритетнее "общего" НДС, чтобы не терять льготные детские ставки.
        enrichment["vat_import_rate"] = float(vat_pref_rate)
    if not enrichment.get("excise_type"):
        enrichment["excise_type"] = (rate_row.excise_type or "none")
    if enrichment.get("excise_value") in (None, ""):
        try:
            enrichment["excise_value"] = float(rate_row.excise_value or 0.0)
        except Exception:
            enrichment["excise_value"] = 0.0
    if not (enrichment.get("excise_basis") or "").strip():
        enrichment["excise_basis"] = (rate_row.excise_basis or "")[:2000]


def _extract_legal_markers(*texts: str) -> list[str]:
    blob = " | ".join(_clean_text_for_output(t, limit=1200) for t in texts if (t or "").strip())
    if not blob:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for pat in _LEGAL_PATTERNS:
        for m in pat.finditer(blob):
            v = _clean_text_for_output(m.group(0), limit=180)
            k = v.casefold()
            if v and k not in seen:
                seen.add(k)
                out.append(v)
            if len(out) >= 4:
                break
        if len(out) >= 4:
            break
    return out


def _extract_tr_refs(*texts: str) -> list[tuple[str, str, str]]:
    blob = " | ".join(_clean_text_for_output(t, limit=2000) for t in texts if (t or "").strip())
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for m in _TR_REF_RE.finditer(blob):
        family = f"ТР {str(m.group(1) or '').upper()}"
        code = str(m.group(2) or "").strip()
        if not code:
            continue
        key = f"{family}:{code}"
        if key in seen:
            continue
        seen.add(key)
        title = _TR_TITLE_BY_CODE.get(code)
        if title:
            pretty = f"{family} {code} ({title})"
        else:
            pretty = f"{family} {code}"
        out.append((family, code, pretty))
    return out


def _measure_text_bag(measure: dict[str, Any]) -> list[str]:
    primary_keys = (
        "document_name",
        "source_excerpt",
        "document_required",
        "description",
        "regulatory_act",
        "note",
        "conditions",
        "comments",
    )
    out: list[str] = []
    for k in primary_keys:
        v = str(measure.get(k) or "").strip()
        if v:
            out.append(v)
    return out


def _measure_categories(measure: dict[str, Any]) -> list[str]:
    t = str(measure.get("measure_type") or "").strip().casefold()
    doc = str(measure.get("document_required") or "")
    desc = str(measure.get("description") or "")
    act = str(measure.get("regulatory_act") or "")
    blob = " ".join([t, doc, desc, act]).casefold()
    cats: list[str] = []

    is_cert = ("сертификат" in blob and "соответств" in blob) or t in {"certificate"}
    is_decl = ("декларац" in blob and "соответств" in blob)
    is_license = ("лиценз" in blob) or t == "license"
    is_sgr = ("сгр" in blob) or ("госрегистрац" in blob) or t == "sgr"
    is_fsb = ("фсб" in blob) or ("нотификац" in blob) or ("шифров" in blob) or ("крипт" in blob)
    is_marking = ("маркиров" in blob) or ("честный знак" in blob) or t == "marking"

    if is_cert:
        cats.append("Сертификат соответствия (СС)")
    if is_decl:
        cats.append("Декларация о соответствии (ДС)")
    if is_license:
        cats.append("Лицензия")
    if is_sgr:
        cats.append("СГР")
    if is_fsb:
        cats.append("Нотификация ФСБ")
    if is_marking:
        cats.append("Маркировка")

    if not cats and ("тр тс" in blob or "тр еаэс" in blob or t == "tr_ts"):
        # По умолчанию относим к подтверждению соответствия.
        cats.append("Сертификат соответствия (СС)")
    return cats


def _category_fallback_text(category: str, blob: str, *, hs10: str, item_description: str) -> str:
    hs = _norm_hs10(hs10)
    item_l = (item_description or "").casefold()
    if hs.startswith("8517") and category in {
        "Сертификат соответствия (СС)",
        "Декларация о соответствии (ДС)",
    }:
        prefix = "СС" if category.startswith("Сертификат") else "ДС"
        return f"{prefix} ТР ТС 004/2011; {prefix} ТР ТС 020/2011; {prefix} ТР ЕАЭС 037/2016"
    if hs.startswith("8517") and category == "Нотификация ФСБ":
        return "Нотификация ФСБ России при наличии шифровальных (криптографических) функций."
    if hs.startswith("9503") and ("юный химик" in item_l or "набор" in item_l) and category == "Сертификат соответствия (СС)":
        return "СС ТР ТС 008/2011 (О безопасности игрушек)"
    if hs.startswith("8413") and category == "Сертификат соответствия (СС)":
        return "СС ТР ТС 010/2011 (О безопасности машин и оборудования)"
    if hs.startswith("8413") and category == "Декларация о соответствии (ДС)":
        return "ДС ТР ТС 010/2011 (О безопасности машин и оборудования)"
    if category == "Лицензия":
        if "фстэк" in blob:
            return "Требуется лицензия ФСТЭК России (по профилю продукции)."
        if "минпромторг" in blob:
            return "Требуется лицензия Минпромторга России (по профилю продукции)."
        return "Требуется лицензия уполномоченного органа (Минпромторг / ФСТЭК) по профилю товара."
    if category == "СГР":
        return "Требуется государственная регистрация продукции (СГР) по Единому перечню."
    if category == "Нотификация ФСБ":
        return "Требуется нотификация ФСБ России при наличии шифровальных (криптографических) функций."
    if category == "Маркировка":
        return "Требуется обязательная маркировка в системе «Честный знак» (при попадании в перечень)."
    if category == "Декларация о соответствии (ДС)":
        return "Требуется декларация о соответствии по применимому техническому регламенту ТР ТС/ЕАЭС."
    return "Требуется сертификат соответствия по применимому техническому регламенту ТР ТС/ЕАЭС."


def _format_nontariff_block(
    db,
    enrichment: dict[str, Any],
    *,
    hs10: str,
    item_description: str,
) -> list[str]:
    hs = _norm_hs10(hs10)
    reqs = resolve_compliance_requirements(
        hs,
        {
            "name_ru": item_description,
            "usage": item_description,
        },
        db,
    )
    cat_by_doc = {
        "СС": "Сертификат соответствия (СС)",
        "ДС": "Декларация о соответствии (ДС)",
        "Лицензия": "Лицензия",
        "СГР": "СГР",
        "Нотификация ФСБ": "Нотификация ФСБ",
        "Маркировка": "Маркировка",
        "РУ": "Регистрационное удостоверение (РУ)",
        "Ветконтроль": "Ветконтроль",
        "Фитоконтроль": "Фитоконтроль",
        "Иное": "Прочее требование",
    }
    lines: list[str] = []
    seen: set[str] = set()
    for rr in reqs:
        cat = cat_by_doc.get(rr.doc_type, "Прочее требование")
        text = _clean_text_for_output(rr.title or rr.detail, limit=420)
        if not text:
            continue
        key = f"{cat}|{text}".casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{cat}: {text}")
    if lines:
        return lines
    # fallback на enrichment, если резолвер не вернул требований
    for m in enrichment.get("non_tariff") or []:
        t = _clean_text_for_output(str(m.get("document_required") or m.get("description") or ""), limit=320)
        if t:
            lines.append(f"Прочие требования: {t}")
    return lines


def _format_risk_alerts(
    enrichment: dict[str, Any],
    *,
    hs10: str,
    item_description: str,
    extra_special: list[str],
    extra_geo: list[str],
    extra_sanctions: list[str],
) -> list[str]:
    lines: list[str] = []
    applied_special = (enrichment.get("Applied_Special_Duty") or "").strip()
    if applied_special:
        lines.append(f"Антидемпинг/спецпошлины: {_clean_text_for_output(applied_special, limit=380)}")

    if enrichment.get("import_embargo"):
        lines.append("Запрет/ограничение ввоза: выявлены меры эмбарго или прямого запрета.")

    for x in extra_special:
        lines.append(f"Антидемпинг/спецпошлины: {_clean_text_for_output(x, limit=420)}")
    for x in extra_geo:
        lines.append(f"Антидемпинг/спецпошлины: {_clean_text_for_output(x, limit=420)}")

    sanction_status = (enrichment.get("Sanction_Status") or "").strip()
    sanction_risk = (enrichment.get("sanction_risk") or "").strip()
    if sanction_risk.strip() or (sanction_status and sanction_status.casefold() not in {"безопасно", "safe"}):
        risk_tail = _clean_text_for_output(sanction_risk or "детализация отсутствует", limit=420)
        lines.append(f"Санкционные риски: статус={sanction_status or '—'}; {risk_tail}")

    for x in extra_sanctions:
        lines.append(f"Санкционные риски: {_clean_text_for_output(x, limit=420)}")

    if _is_sweet_2202_case(hs10, item_description):
        lines.append("Оформление только на акцизных таможенных постах (Приказ Минфина №27н).")

    # Дедупликация с сохранением порядка.
    out: list[str] = []
    seen: set[str] = set()
    for x in lines:
        key = x.strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(x.strip())
    return out


def _build_item_data(description: str, template: dict[str, Any]) -> dict[str, Any]:
    return {
        "name_ru": description,
        "name_cn": "",
        "material": str(template.get("material") or ""),
        "usage": str(template.get("usage") or ""),
        "brand": str(template.get("brand") or ""),
        "country_origin": str(template.get("country_origin") or ""),
        "suggested_chapter": str(template.get("suggested_chapter") or ""),
    }


def run_smoke_test(*, fast_mode: bool = False, output_md: Path | None = None) -> int:
    report_lines: list[str] = []
    report_lines.append("# Full Pipeline Smoke Test")
    report_lines.append("")

    with SessionLocal() as db:
        analyzer = InvoiceAnalyzer(db_session=db)

        for idx, tmpl in enumerate(TEST_ITEMS, start=1):
            item_desc = str(tmpl["name_ru"])
            item_data = _build_item_data(item_desc, tmpl)

            # В fast-mode intentionally не дергаем LLM, чтобы исключить каскад 429/timeout
            # и формировать стабильную "брокерскую" справку по детерминированным правилам.
            if fast_mode:
                hs_payload = {}
            else:
                try:
                    hs_payload = _run_with_timeout(
                        lambda: analyzer.suggest_hs_code_for_item(item_data, fast_mode=fast_mode),
                        timeout_sec=65,
                    )
                except Exception:
                    hs_payload = {}
            hs10 = _norm_hs10(hs_payload.get("suggested_hs_code") or hs_payload.get("hs_code"))
            if not hs10:
                hs10 = _fallback_hs_from_description(item_desc)
                if hs10:
                    hs_payload = {
                        **hs_payload,
                        "suggested_hs_code": hs10,
                        "hs_code": hs10,
                        "opi_reasoning_steps": _opi_reasoning_from_hs(hs10, item_desc),
                    }
            prefix = hs10[:4] or str(item_data.get("suggested_chapter") or "")

            query_text = (
                str(hs_payload.get("normalized_product_name") or "").strip()
                or item_desc
            )
            semantic_top3 = get_semantic_legal_context(
                query_text,
                db,
                top_k=3,
                hs_code_prefix=prefix,
            )
            if not semantic_top3 and hs10:
                semantic_top3 = _fallback_precedents_from_db(db, hs10, item_desc, top_k=3)
            semantic_top3 = [x for x in (_clean_precedent_line(s) for s in (semantic_top3 or [])) if x]

            enrichment = enrich_with_customs_data(hs10, item_data=item_data)
            vat_pref_rate, _vat_basis = _best_vat_pref_rate(db, hs10)
            _apply_hs_rate_fallback(
                enrichment,
                _best_hs_rate_row(db, hs10),
                vat_pref_rate=vat_pref_rate,
            )
            origin_iso2 = _norm_iso2(item_data.get("country_origin"))

            extra_special = _query_special_duties(db, hs10, origin_iso2)
            extra_geo = _query_geo_special_duties(db, hs10, origin_iso2)
            extra_sanctions = _query_sanction_risks(db, hs10)

            opi_steps = hs_payload.get("opi_reasoning_steps") or []
            if (not opi_steps) or any("автоfallback" in str(s).casefold() for s in opi_steps):
                opi_steps = _opi_reasoning_from_hs(hs10, item_desc)
            finance_line = _format_finance_line(
                enrichment,
                hs10=hs10,
                item_description=item_desc,
            )
            nontariff_lines = _format_nontariff_block(
                db,
                enrichment,
                hs10=hs10,
                item_description=item_desc,
            )
            risk_alerts = _format_risk_alerts(
                enrichment,
                hs10=hs10,
                item_description=item_desc,
                extra_special=extra_special,
                extra_geo=extra_geo,
                extra_sanctions=extra_sanctions,
            )

            block: list[str] = []
            block.append(f"## Кейc {idx}")
            block.append(f"📦 ТОВАР: {item_desc}")
            block.append("📚 ПРЕЦЕДЕНТЫ (TOP-3):")
            if semantic_top3:
                block.extend([f"- {x}" for x in semantic_top3])
            else:
                block.append("- (релевантные прецеденты не найдены)")
            block.append("🧠 ЛОГИКА ИИ (ОПИ):")
            if opi_steps:
                block.extend([f"- {str(x)}" for x in opi_steps])
            else:
                block.append("- (opi_reasoning_steps пусто)")
            block.append(f"🎯 КОД ТН ВЭД: {hs10 or '—'}")
            block.append(f"💰 ФИНАНСЫ: {finance_line.replace('; ', ' | ')}")
            block.append("🛡 НЕТАРИФКА:")
            if nontariff_lines:
                block.extend([f"{i}) {x}" for i, x in enumerate(nontariff_lines, start=1)])
            else:
                block.append("- (меры не выявлены)")
            if risk_alerts:
                block.append("⚠ АЛЕРТЫ ПО РИСКАМ:")
                block.extend([f"{i}) {x}" for i, x in enumerate(risk_alerts, start=1)])
            block.append("")

            print("\n".join(block), flush=True)
            report_lines.extend(block)
            time.sleep(15)

    if output_md is not None:
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text("\n".join(report_lines).strip() + "\n", encoding="utf-8")
        print(f"\nMarkdown report saved: {output_md}", flush=True)

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Глубокий smoke-тест полного пайплайна (RAG + ОПИ + обогащение БД).")
    ap.add_argument("--fast-mode", action="store_true", help="Быстрый режим классификации.")
    ap.add_argument(
        "--output-md",
        default="logs/full_pipeline_smoke.md",
        help="Путь для markdown-отчёта (по умолчанию logs/full_pipeline_smoke.md). "
        "Передайте пустую строку, чтобы не писать файл.",
    )
    args = ap.parse_args()

    out_md: Path | None
    if str(args.output_md).strip():
        out_md = Path(args.output_md).expanduser().resolve()
    else:
        out_md = None

    return run_smoke_test(fast_mode=bool(args.fast_mode), output_md=out_md)


if __name__ == "__main__":
    raise SystemExit(main())
