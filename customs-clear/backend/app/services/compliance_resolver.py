"""Единый резолвер нормативных требований (ТР/ДС/СС/СГР/ФСБ/маркировка/лицензии)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import HsRate
from ..models.core import (
    CountryRisk,
    EuSanctionsList,
    GeoSpecialDuty,
    NonTariffRule,
    NormativeNote,
    OfacSdnList,
    RegulatoryAiExtract,
    SanctionImportRisk,
    TrTsAct,
)
from ..models.tnved import NonTariffMeasure, VatPreference
from .registry_matcher import match_document_in_registries

DEFAULT_VAT_RATE = 22.0


@dataclass(frozen=True)
class ComplianceRequirement:
    doc_type: str
    legal_ref: str
    title: str
    detail: str
    source: str
    priority: int = 100


def _norm_hs(raw: Any) -> str:
    return re.sub(r"\D", "", str(raw or ""))[:10]


def _norm_text(*parts: str) -> str:
    return " ".join(str(p or "") for p in parts).strip().lower()


def _hs_prefix_chain(hs_code: str, *, min_len: int = 2) -> list[str]:
    hs = _norm_hs(hs_code)
    if len(hs) < min_len:
        return []
    out: list[str] = []
    for ln in range(len(hs), min_len - 1, -1):
        out.append(hs[:ln])
    return out


# ---------------------------------------------------------------------------
# ЖЁСТКИЕ ОГРАНИЧИТЕЛИ (HS-gate) и word-boundary триггеры.
#
# Цель: не допускать абсурдных связок вроде «ветсертификат на смартфон (8517)»
# или «фитоконтроль на микросхему (8542)». Гейт применяется УНИВЕРСАЛЬНО
# в _apply_strict_profile_filters и отсекает типы документов, не совместимые
# с главой/позицией ТН ВЭД, даже если строка non_tariff_measures / AI-extract
# «ошибочно» сработала на подстроку.
# ---------------------------------------------------------------------------

# Допустимые префиксы ТН ВЭД для каждого типа разрешительного документа.
# Формируются по смыслу нетарифного регулирования ЕАЭС / РФ.
_DOC_TYPE_HS_GATE: dict[str, tuple[str, ...]] = {
    "Ветконтроль": (
        "01", "02", "03", "04", "05",  # живые животные, мясо, рыба, молочка, яйца, пух, кишки
        "15",                            # жиры и масла животного происхождения
        "16",                            # готовые мясо/рыбо- продукты
        "2309",                          # корма для животных
        "41", "42", "43",              # шкуры, кожа необработанная, меха
        "9508",                          # передвижные цирки/зверинцы
    ),
    "Фитоконтроль": (
        "06", "07", "08", "09", "10", "11", "12", "13", "14",  # растения, зерновые, овощи, фрукты, семена
        "24",                              # табачное сырьё
        "44", "45", "46",                  # древесина, пробка, плетёные изделия
        "1401", "1402", "1403", "1404",    # растительные материалы для плетения
    ),
    "Нотификация ФСБ": (
        "84", "85", "90",  # ВТ, электроника связи, измерительные приборы с шифрованием
    ),
    "РУ": (
        "30",                             # лекарства
        "3822", "3006",                   # диагностические реагенты, мед. стерилизаторы
        "9018", "9019", "9020", "9021", "9022",  # медицинские инструменты
        "9402",                            # медицинская мебель
    ),
    "СГР": (
        "02", "03", "04", "05",                    # продукты животного происхождения
        "07", "08", "09", "10", "11", "12", "13", "14",  # растит. продовольствие
        "15", "16", "17", "18", "19", "20", "21", "22",  # переработанное продовольствие
        "2106",                                         # БАД, спецпитание
        "33", "34",                                     # косметика, бытовая химия
        "3808",                                         # дезсредства
        "4818",                                         # подгузники, гигиена
        "61", "62", "63", "64",                       # детская одежда/обувь
        "95",                                            # игрушки
    ),
    "Маркировка": (
        "24",         # табак
        "30",         # лекарства
        "33",         # парфюмерия
        "40",         # шины
        "42",         # сумки/изделия из кожи
        "4202",       # изделия из кожи
        "4818",       # бумажная гигиена
        "61", "62",   # одежда (частично)
        "64",         # обувь
        "6401", "6402", "6403", "6404", "6405",
        "8418", "8450", "8508", "8516", "8528",  # бытовая техника (отдельные группы)
        "8712",       # велосипеды
        "90",         # фото/оптика (отдельные группы)
    ),
    # Радиочастотное разрешение (РКН/ГКРЧ): только РЭС/ВЧУ в главах 84/85/90.
    "Лицензия_РЧЦ": ("84", "85", "90"),
}


def _is_doc_type_applicable_for_hs(doc_type: str, hs: str) -> bool:
    """HS-gate: возвращает True, если данный тип документа в принципе применим к коду.

    Если для типа документа нет строгой привязки — разрешаем. Если привязка задана —
    пропускаем только коды, начинающиеся с одного из допустимых префиксов.
    """
    allowed = _DOC_TYPE_HS_GATE.get(doc_type)
    if not allowed:
        return True
    return any(hs.startswith(pref) for pref in allowed)


# Word-boundary регулярки для триггеров из текстов НПА/мер.
# Никакого substring-поиска: иначе «вет» ловит «цвет/свет/ответ», «фсб» — часть наименования НПА
# без отношения к нотификации, «маркиров» — знак ЕАС (а не «Честный знак»).
_VET_PATTERN = re.compile(
    r"(?<![а-яё])(вет(?:еринар\w*|надзор|контрол\w*|справк\w*|сертификат\w*)|ветслужб\w*|ветэкспертиз\w*)",
    re.IGNORECASE,
)
_PHYTO_PATTERN = re.compile(
    r"(?<![а-яё])(фитосанитар\w*|фитоконтрол\w*|фитокарантин\w*|фитосертификат\w*)",
    re.IGNORECASE,
)
_FSB_NOTIFY_PATTERN = re.compile(
    r"(?<![а-яё])(нотификац\w*|шифровальн\w*|крипто(?:граф\w*)?|фсб\s+росси\w*|цлсз)",
    re.IGNORECASE,
)
_SGR_PATTERN = re.compile(
    r"(?<![а-яё])(сгр\b|свидетельств\w+\s+о\s+госрегистрац\w*|единое\s+свидетельств\w*|госрегистрац\w*)",
    re.IGNORECASE,
)
_LICENSE_PATTERN = re.compile(
    r"(?<![а-яё])(лицензи\w+|разрешени\w+\s+минпромторг\w*|разрешени\w+\s+фстэк\w*)",
    re.IGNORECASE,
)
_MARKING_PATTERN = re.compile(
    r"(?<![а-яё])(честн\w+\s+знак\w*|обязательн\w+\s+маркировк\w+|средств\w+\s+идентификац\w+)",
    re.IGNORECASE,
)


def _extract_tr_codes(*texts: str) -> list[str]:
    blob = _norm_text(*texts)
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"(?:тр\s*(?:тс|еаэс)\s*)?(\d{3}/\d{4})", blob, flags=re.IGNORECASE):
        code = (m.group(1) or "").strip()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _tr_family(code: str) -> str:
    return "ТР ЕАЭС" if code.strip() == "037/2016" else "ТР ТС"


_TR_TITLES: dict[str, str] = {
    "004/2011": "О безопасности низковольтного оборудования",
    "008/2011": "О безопасности игрушек",
    "010/2011": "О безопасности машин и оборудования",
    "020/2011": "Электромагнитная совместимость технических средств",
    "021/2011": "О безопасности пищевой продукции",
    "022/2011": "Пищевая продукция в части ее маркировки",
    "029/2012": "Требования безопасности пищевых добавок, ароматизаторов и технологических вспомогательных средств",
    "037/2016": "Об ограничении применения опасных веществ в изделиях электротехники и радиоэлектроники",
}


def _format_doc(doc_type: str, tr_code: str) -> tuple[str, str]:
    fam = _tr_family(tr_code)
    title = _TR_TITLES.get(tr_code, "")
    legal_ref = f"{fam} {tr_code}".strip()
    if title:
        return legal_ref, f"{doc_type} {legal_ref} ({title})"
    return legal_ref, f"{doc_type} {legal_ref}"


def _features(item_data: dict[str, Any] | None, hs_code: str) -> dict[str, bool]:
    hs = _norm_hs(hs_code)
    t = _norm_text(
        str((item_data or {}).get("name_ru") or ""),
        str((item_data or {}).get("name_cn") or ""),
        str((item_data or {}).get("material") or ""),
        str((item_data or {}).get("usage") or ""),
        str((item_data or {}).get("brand") or ""),
    )
    has_radio = any(k in t for k in ("wifi", "wi-fi", "bluetooth", "nfc", "gsm", "lte", "5g", "радио", "беспровод", "роутер", "смартфон"))
    has_encryption = any(k in t for k in ("шифр", "крипт", "encryption", "crypto", "vpn"))
    is_food = hs.startswith("22") or any(k in t for k in ("напит", "сок", "пищев", "food", "beverage"))
    is_kids = hs.startswith("95") or any(k in t for k in ("детск", "игрушк", "юный химик"))
    is_baad = any(k in t for k in ("бад", "биологически актив", "dietary supplement", "капсул"))
    has_electronics = hs.startswith(("84", "85", "90")) or any(k in t for k in ("электро", "электродвиг", "датчик", "расходомер"))
    return {
        "has_radio": has_radio,
        "has_encryption": has_encryption or has_radio,
        "is_food": is_food,
        "is_kids": is_kids,
        "is_baad": is_baad,
        "has_electronics": has_electronics,
    }


ConditionFn = Callable[[dict[str, bool], str], bool]


@dataclass(frozen=True)
class MatrixRule:
    hs_prefix: str
    doc_type: str
    tr_code: str
    title_override: str = ""
    source: str = "matrix"
    priority: int = 100
    condition: ConditionFn | None = None


def _cond_true(_f: dict[str, bool], _hs: str) -> bool:
    return True


def _cond_food(f: dict[str, bool], _hs: str) -> bool:
    return bool(f.get("is_food"))


def _cond_kids(f: dict[str, bool], _hs: str) -> bool:
    return bool(f.get("is_kids"))


def _cond_radio(f: dict[str, bool], _hs: str) -> bool:
    return bool(f.get("has_radio"))


def _cond_encrypt(f: dict[str, bool], _hs: str) -> bool:
    return bool(f.get("has_encryption"))


def _cond_baad(f: dict[str, bool], _hs: str) -> bool:
    return bool(f.get("is_baad"))


def _cond_electronics(f: dict[str, bool], _hs: str) -> bool:
    return bool(f.get("has_electronics"))


COMPLIANCE_MATRIX: tuple[MatrixRule, ...] = (
    MatrixRule("8517", "ДС", "020/2011", condition=_cond_true, priority=1000),
    MatrixRule("8517", "ДС", "037/2016", condition=_cond_true, priority=1000),
    MatrixRule("2202", "ДС", "021/2011", condition=_cond_food, priority=1000),
    MatrixRule("2202", "ДС", "022/2011", condition=_cond_food, priority=1000),
    MatrixRule("9503", "СС", "008/2011", condition=_cond_kids, priority=1000),
    MatrixRule("8413", "СС", "010/2011", condition=_cond_true, priority=1000),
    MatrixRule("8413", "ДС", "004/2011", condition=_cond_electronics, priority=900),
    MatrixRule("8413", "ДС", "020/2011", condition=_cond_electronics, priority=900),
    MatrixRule("2106", "ДС", "021/2011", condition=_cond_true, priority=950),
    MatrixRule("2106", "ДС", "022/2011", condition=_cond_true, priority=950),
)


def _permit_doc_types(raw: str) -> set[str]:
    out: set[str] = set()
    for tok in re.split(r"[,;/|]", str(raw or "")):
        t = tok.strip().upper()
        if not t:
            continue
        if "ДС" in t or "ДЕКЛАР" in t:
            out.add("ДС")
        if "СС" in t or "СЕРТИФ" in t:
            out.add("СС")
        if "СГР" in t or "ГОСРЕГ" in t:
            out.add("СГР")
        if "ФСБ" in t or "НОТИФ" in t:
            out.add("Нотификация ФСБ")
        if "ЛИЦ" in t:
            out.add("Лицензия")
        if "МАРКИР" in t or "ЧЕСТНЫЙ ЗНАК" in t:
            out.add("Маркировка")
        if t == "РУ" or ("РЕГИСТРАЦ" in t and "УДОСТ" in t):
            out.add("РУ")
        if "ВЕТ" in t:
            out.add("Ветконтроль")
        if "ФИТО" in t:
            out.add("Фитоконтроль")
    return out


def _generic_doc_requirement(doc_type: str, *, source: str, priority: int, legal_ref: str = "") -> ComplianceRequirement:
    if doc_type == "ДС":
        return ComplianceRequirement("ДС", legal_ref or "ТР ТС/ЕАЭС", "ДС по применимому ТР ТС/ЕАЭС", "ДС по применимому техническому регламенту ТР ТС/ЕАЭС.", source, priority)
    if doc_type == "СС":
        return ComplianceRequirement("СС", legal_ref or "ТР ТС/ЕАЭС", "СС по применимому ТР ТС/ЕАЭС", "СС по применимому техническому регламенту ТР ТС/ЕАЭС.", source, priority)
    if doc_type == "СГР":
        return ComplianceRequirement("СГР", legal_ref or "ЕАЭС", "СГР по требованиям ЕАЭС", "СГР по требованиям ЕАЭС (проверить номер в реестре).", source, priority)
    if doc_type == "Нотификация ФСБ":
        return ComplianceRequirement("Нотификация ФСБ", legal_ref or "ФСБ РФ", "Нотификация ФСБ", "Нотификация ФСБ России при наличии шифровальных (криптографических) функций.", source, priority)
    if doc_type == "Лицензия":
        return ComplianceRequirement("Лицензия", legal_ref or "Лицензирование", "Лицензия уполномоченного органа", "Требуется лицензия уполномоченного органа (Минпромторг / ФСТЭК) по профилю товара.", source, priority)
    if doc_type == "Маркировка":
        return ComplianceRequirement("Маркировка", legal_ref or "ПП РФ (маркировка)", "Маркировка «Честный знак»", "Маркировка «Честный знак» по постановлению Правительства РФ для соответствующей группы товаров.", source, priority)
    if doc_type == "РУ":
        return ComplianceRequirement("РУ", legal_ref or "Росздравнадзор", "Регистрационное удостоверение (РУ)", "Требуется регистрационное удостоверение (РУ) на медицинское изделие/лекарственный профиль товара.", source, priority)
    if doc_type == "Ветконтроль":
        return ComplianceRequirement("Ветконтроль", legal_ref or "ЕАЭС/РФ", "Ветеринарный контроль", "Требуется ветеринарный контроль по профилю товара.", source, priority)
    if doc_type == "Фитоконтроль":
        return ComplianceRequirement("Фитоконтроль", legal_ref or "ЕАЭС/РФ", "Фитосанитарный контроль", "Требуется фитосанитарный контроль по профилю товара.", source, priority)
    return ComplianceRequirement(doc_type or "Иное", legal_ref or "НПА", f"{doc_type or 'Иное'} требование", "Требуется проверка профильных разрешительных требований.", source, priority)


def resolve_vat_rate_for_hs(hs_code: str, db: Session) -> tuple[float, str]:
    hs = _norm_hs(hs_code)
    if hs.startswith("9503"):
        return 10.0, "Льготная ставка для детских товаров (проверить актуальную редакцию ПП РФ/НК РФ)."
    prefixes = _hs_prefix_chain(hs, min_len=2)
    if not prefixes:
        return DEFAULT_VAT_RATE, "НК РФ ст. 164 п. 3 (общая ставка)"
    best_rate: float | None = None
    best_basis = ""
    best_len = -1
    for r in db.query(VatPreference).filter(VatPreference.hs_code_prefix.in_(prefixes)).all():
        pref = _norm_hs(r.hs_code_prefix)
        if not pref or not hs.startswith(pref):
            continue
        if len(pref) > best_len:
            best_len = len(pref)
            try:
                best_rate = float(r.vat_rate)
            except Exception:
                best_rate = None
            best_basis = str(r.decree_info or r.comment or "").strip()[:255]
    if best_rate is not None:
        return best_rate, best_basis
    # fallback по hs_rates (префиксный)
    best_row: HsRate | None = None
    best_len = -1
    for rr in db.query(HsRate).filter(or_(HsRate.hs_code.in_(prefixes), HsRate.hs_prefix.in_(prefixes))).all():
        pref = _norm_hs(rr.hs_code) or _norm_hs(rr.hs_prefix)
        if not pref or not hs.startswith(pref):
            continue
        if len(pref) > best_len:
            best_row = rr
            best_len = len(pref)
    if best_row is not None:
        try:
            return float(best_row.vat_import_rate), str(best_row.vat_rule_basis or "")[:255]
        except Exception:
            pass
    return DEFAULT_VAT_RATE, "НК РФ ст. 164 п. 3 (общая ставка)"


def pick_vat_preference_row(hs_code: str, db: Session) -> tuple[VatPreference | None, int]:
    """Выбирает запись vat_preferences по самому длинному префиксу; tie-break — по id DESC."""
    hs = _norm_hs(hs_code)
    prefixes = _hs_prefix_chain(hs, min_len=2)
    if not prefixes:
        return None, 0

    rows = (
        db.query(VatPreference)
        .filter(VatPreference.hs_code_prefix.in_(prefixes))
        .order_by(VatPreference.id.desc())
        .all()
    )

    best_row: VatPreference | None = None
    best_len = -1
    for row in rows:
        pref = _norm_hs(row.hs_code_prefix)
        if not pref or not hs.startswith(pref):
            continue
        lp = len(pref)
        if lp > best_len:
            best_row = row
            best_len = lp
            continue
        # При равной длине берём запись с более новым id (уже гарантировано order_by id DESC).
        if lp == best_len and best_row is None:
            best_row = row

    if best_row is None:
        return None, 0
    return best_row, best_len


def _requirements_from_matrix(hs: str, f: dict[str, bool]) -> list[ComplianceRequirement]:
    out: list[ComplianceRequirement] = []
    for r in COMPLIANCE_MATRIX:
        if not hs.startswith(r.hs_prefix):
            continue
        cond = r.condition or _cond_true
        if not cond(f, hs):
            continue
        legal_ref, label = _format_doc(r.doc_type, r.tr_code)
        if r.title_override.strip():
            label = r.title_override.strip()
        out.append(
            ComplianceRequirement(
                doc_type=r.doc_type,
                legal_ref=legal_ref,
                title=label,
                detail=label,
                source=r.source,
                priority=r.priority,
            )
        )
    return out


def _requirements_from_non_tariff_rules(hs: str, db: Session) -> list[ComplianceRequirement]:
    out: list[ComplianceRequirement] = []
    prefixes = _hs_prefix_chain(hs, min_len=2)
    if not prefixes:
        return out
    for rr in db.query(NonTariffRule).filter(NonTariffRule.hs_prefix.in_(prefixes)).all():
        pref = _norm_hs(rr.hs_prefix)
        if not pref or not hs.startswith(pref):
            continue
        tr_codes = _extract_tr_codes(str(rr.tr_ts or ""), str(rr.tr_ts_edition or ""))
        permit_tokens = _permit_doc_types(str(rr.required_permits or ""))
        prio = 700 + len(pref) * 8 + int(rr.priority or 0)
        for code in tr_codes:
            if "ДС" in permit_tokens:
                legal_ref, label = _format_doc("ДС", code)
                out.append(ComplianceRequirement("ДС", legal_ref, label, label, "non_tariff_rules", prio))
            if "СС" in permit_tokens:
                legal_ref, label = _format_doc("СС", code)
                out.append(ComplianceRequirement("СС", legal_ref, label, label, "non_tariff_rules", prio))

        # Разрешения, не завязанные на конкретный ТР-код.
        for dt in sorted(permit_tokens):
            if dt in {"ДС", "СС"} and tr_codes:
                continue
            out.append(_generic_doc_requirement(dt, source="non_tariff_rules", priority=prio))
    return out


def _requirements_from_non_tariff_measures(hs: str, db: Session) -> list[ComplianceRequirement]:
    out: list[ComplianceRequirement] = []
    prefixes = _hs_prefix_chain(hs, min_len=2)
    if not prefixes:
        return out
    rows = (
        db.query(NonTariffMeasure)
        .filter(
            NonTariffMeasure.commodity_code.in_(prefixes)
        )
        .limit(2000)
        .all()
    )
    for r in rows:
        code = _norm_hs(r.commodity_code)
        if code and not hs.startswith(code):
            continue
        text_blob = _norm_text(r.document_required or "", r.description or "", r.regulatory_act or "")
        tr_codes = _extract_tr_codes(text_blob)
        mtype = str(r.measure_type or "").strip().lower()
        prio = 500 + len(code) * 5
        row_detected = False

        if _MARKING_PATTERN.search(text_blob) or mtype == "marking":
            out.append(_generic_doc_requirement("Маркировка", source="non_tariff_measures", priority=prio + 100))
            row_detected = True
        if _FSB_NOTIFY_PATTERN.search(text_blob) or mtype == "fsb":
            out.append(_generic_doc_requirement("Нотификация ФСБ", source="non_tariff_measures", priority=prio + 140))
            row_detected = True
        if _LICENSE_PATTERN.search(text_blob) or mtype == "license":
            out.append(_generic_doc_requirement("Лицензия", source="non_tariff_measures", priority=prio + 50))
            row_detected = True
        if _SGR_PATTERN.search(text_blob) or mtype == "sgr":
            out.append(_generic_doc_requirement("СГР", source="non_tariff_measures", priority=prio + 60))
            row_detected = True
        if _VET_PATTERN.search(text_blob) or mtype in {"vet_control", "veterinary"}:
            out.append(_generic_doc_requirement("Ветконтроль", source="non_tariff_measures", priority=prio + 30))
            row_detected = True
        if _PHYTO_PATTERN.search(text_blob) or mtype in {"phyto_control", "phytosanitary"}:
            out.append(_generic_doc_requirement("Фитоконтроль", source="non_tariff_measures", priority=prio + 30))
            row_detected = True
        if "декларац" in text_blob and "соответств" in text_blob:
            if tr_codes:
                for code in tr_codes:
                    legal_ref, label = _format_doc("ДС", code)
                    out.append(ComplianceRequirement("ДС", legal_ref, label, label, "non_tariff_measures", prio + 120))
            else:
                out.append(_generic_doc_requirement("ДС", source="non_tariff_measures", priority=prio + 80))
            row_detected = True
        if "сертификат" in text_blob and "соответств" in text_blob:
            if tr_codes:
                for code in tr_codes:
                    legal_ref, label = _format_doc("СС", code)
                    out.append(ComplianceRequirement("СС", legal_ref, label, label, "non_tariff_measures", prio + 120))
            else:
                out.append(_generic_doc_requirement("СС", source="non_tariff_measures", priority=prio + 80))
            row_detected = True

        if not row_detected:
            generic_title = str(r.document_required or r.measure_type or "Иное требование").strip()[:255]
            generic_detail = str(r.description or r.regulatory_act or generic_title).strip()[:500]
            generic_ref = str(r.regulatory_act or "НПА").strip()[:255]
            out.append(
                ComplianceRequirement(
                    "Иное",
                    generic_ref or "НПА",
                    generic_title or "Иное требование",
                    generic_detail or "Требуется проверка профильных нетарифных требований.",
                    "non_tariff_measures",
                    prio,
                )
            )
    return out


def _requirements_from_regulatory_ai_extracts(hs: str, db: Session) -> list[ComplianceRequirement]:
    out: list[ComplianceRequirement] = []
    prefixes = _hs_prefix_chain(hs, min_len=2)
    if not prefixes:
        return out
    rows = (
        db.query(RegulatoryAiExtract)
        .filter(RegulatoryAiExtract.hs_code_norm.in_(prefixes))
        .limit(600)
        .all()
    )
    for r in rows:
        code = _norm_hs(r.hs_code_norm)
        if not code or code == "0000000000" or not hs.startswith(code):
            continue
        mtype = str(r.measure_type or "").strip().lower()
        if mtype not in {"tr_ts", "license", "vet_control", "ban", "export_control"}:
            continue
        text_blob = _norm_text(r.document_name or "", r.source_excerpt or "")
        tr_codes = _extract_tr_codes(text_blob)
        prio = 560 + len(code) * 5
        if mtype == "tr_ts":
            if tr_codes:
                for tcode in tr_codes:
                    legal_ref, label = _format_doc("ДС", tcode)
                    out.append(ComplianceRequirement("ДС", legal_ref, label, label, "regulatory_ai_extracts", prio + 120))
            else:
                out.append(_generic_doc_requirement("ДС", source="regulatory_ai_extracts", priority=prio + 90))
        elif mtype == "license":
            out.append(_generic_doc_requirement("Лицензия", source="regulatory_ai_extracts", priority=prio + 80))
        elif mtype == "vet_control":
            out.append(_generic_doc_requirement("Ветконтроль", source="regulatory_ai_extracts", priority=prio + 70))
        elif mtype == "export_control":
            out.append(
                ComplianceRequirement(
                    "Лицензия",
                    "Экспортный контроль",
                    "Лицензия/разрешение по линии экспортного контроля",
                    "Проверить необходимость лицензии/разрешения по линии экспортного контроля.",
                    "regulatory_ai_extracts",
                    prio + 65,
                )
            )
        elif mtype == "ban":
            out.append(
                ComplianceRequirement(
                    "Иное",
                    "Запрет/ограничение",
                    "Запрет/ограничение по НПА",
                    "Проверить действующий запрет или ограничение по профильному НПА.",
                    "regulatory_ai_extracts",
                    prio + 60,
                )
            )
    return out


def _gate_by_hs(requirements: list[ComplianceRequirement], hs: str) -> list[ComplianceRequirement]:
    """Универсальный HS-gate для ВСЕХ кодов.

    Отсекает любые требования типа "Ветконтроль/Фитоконтроль/ФСБ/СГР/РУ/Маркировка",
    если код ТН ВЭД не входит в профильный whitelist (_DOC_TYPE_HS_GATE).
    """
    out: list[ComplianceRequirement] = []
    for r in requirements:
        if _is_doc_type_applicable_for_hs(r.doc_type, hs):
            out.append(r)
    return out


def _apply_strict_profile_filters(
    requirements: list[ComplianceRequirement],
    *,
    hs: str,
    feats: dict[str, bool],
) -> list[ComplianceRequirement]:
    # --- ШАГ 0. Универсальный HS-gate: отсекаем абсурдные связки (ветсертификат на 8517 и т. п.).
    requirements = _gate_by_hs(requirements, hs)

    # Смартфон/связь: только DS + ФСБ + радиоразрешение.
    if hs.startswith("8517"):
        keep = {"ДС", "Нотификация ФСБ", "Лицензия"}
        reqs: list[ComplianceRequirement] = []
        for r in requirements:
            if r.doc_type not in keep:
                continue
            if r.doc_type == "ДС":
                if not any(code in r.legal_ref for code in ("004/2011", "020/2011", "037/2016")):
                    continue
            if r.doc_type == "Лицензия":
                if "радиочастот" not in r.title.casefold() and "ркн" not in r.title.casefold() and "гкрч" not in r.title.casefold():
                    continue
            reqs.append(r)
        # Явно радиоразрешение.
        if feats.get("has_radio"):
            reqs.append(
                ComplianceRequirement(
                    "Лицензия",
                    "РКН/ГКРЧ",
                    "Радиочастотное разрешение/заключение",
                    "Радиочастотное разрешение/заключение РКН (ГКРЧ) при ввозе РЭС, использующих радиочастотный спектр РФ.",
                    "matrix",
                    950,
                )
            )
        return reqs

    if hs.startswith("2202"):
        keep = {"ДС"}
        return [r for r in requirements if r.doc_type in keep]

    if hs.startswith("9503"):
        keep = {"СС", "Маркировка"}
        return [r for r in requirements if r.doc_type in keep]

    if hs.startswith("2106"):
        keep = {"ДС", "СГР"}
        return [r for r in requirements if r.doc_type in keep]

    return requirements


def resolve_compliance_requirements(
    hs_code: str,
    item_data: dict[str, Any] | None,
    db: Session,
) -> list[ComplianceRequirement]:
    hs = _norm_hs(hs_code)
    if len(hs) < 2:
        return []
    feats = _features(item_data, hs)

    reqs = []
    reqs.extend(_requirements_from_matrix(hs, feats))
    reqs.extend(_requirements_from_non_tariff_rules(hs, db))
    reqs.extend(_requirements_from_non_tariff_measures(hs, db))
    reqs.extend(_requirements_from_regulatory_ai_extracts(hs, db))

    if hs.startswith("8517") and feats.get("has_encryption"):
        reqs.append(
            ComplianceRequirement(
                "Нотификация ФСБ",
                "ФСБ РФ",
                "Нотификация ФСБ",
                "Нотификация ФСБ России при наличии шифровальных (криптографических) функций.",
                "matrix",
                960,
            )
        )

    if feats.get("is_kids") and hs.startswith("9503"):
        reqs.append(
            ComplianceRequirement(
                "Маркировка",
                "ПП РФ (маркировка)",
                "Маркировка «Честный знак»",
                "Маркировка «Честный знак» по постановлению Правительства РФ для соответствующей группы детских товаров (проверка актуальной редакции обязательна).",
                "matrix",
                940,
            )
        )
    if feats.get("is_baad") and hs.startswith("2106"):
        reqs.append(
            ComplianceRequirement(
                "СГР",
                "ЕАЭС",
                "СГР для БАД по требованиям ЕАЭС",
                "СГР для БАД по требованиям ЕАЭС (перед выпуском требуется номер госрегистрации).",
                "matrix",
                940,
            )
        )

    reqs = _apply_strict_profile_filters(reqs, hs=hs, feats=feats)

    # Дедуп и сортировка.
    out: list[ComplianceRequirement] = []
    seen: set[tuple[str, str, str]] = set()
    for r in sorted(reqs, key=lambda x: (-int(x.priority), x.doc_type, x.legal_ref, x.title)):
        key = (r.doc_type.strip().upper(), r.legal_ref.strip().upper(), r.title.strip().upper())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    if not out:
        out.append(
            ComplianceRequirement(
                "Иное",
                "ЕТТ ЕАЭС / решения ЕЭК",
                "Требуется ручная проверка применимых нетарифных мер",
                "Для кода не найдено прямых записей в локальной матрице. Выполнить ручную проверку действующих мер по ЕТТ ЕАЭС и профильным решениям ЕЭК.",
                "fallback",
                10,
            )
        )
    return out


def apply_compliance_resolution_to_enrichment(
    enrichment: dict[str, Any],
    hs_code: str,
    item_data: dict[str, Any] | None,
    db: Session,
) -> None:
    reqs = resolve_compliance_requirements(hs_code, item_data, db)
    if not reqs:
        return

    nt: list[dict[str, str]] = []
    for r in reqs:
        measure_type_map = {
            "ДС": "declaration",
            "СС": "certificate",
            "СГР": "sgr",
            "Нотификация ФСБ": "fsb_notification",
            "Лицензия": "license",
            "Маркировка": "marking",
            "РУ": "registration_certificate",
            "Ветконтроль": "vet_control",
            "Фитоконтроль": "phyto_control",
            "Иное": "other",
        }
        nt.append(
            {
                "measure_type": measure_type_map.get(r.doc_type, "compliance"),
                "document_required": r.title[:255],
                "description": r.detail[:500],
                "regulatory_act": r.legal_ref[:255],
            }
        )

    enrichment["non_tariff"] = nt

    # Краткая строка сертификатов для общего поля.
    cert_bits: list[str] = []
    for r in reqs:
        if r.doc_type in {"ДС", "СС", "СГР", "Нотификация ФСБ", "Лицензия", "Маркировка", "РУ", "Ветконтроль", "Фитоконтроль", "Иное"}:
            cert_bits.append(r.title)
    if cert_bits:
        enrichment["Required_Certificates"] = "; ".join(cert_bits)[:2000]


def _lookup_normative_notes(hs: str, db: Session) -> list[NormativeNote]:
    hs2 = hs[:2]
    prefixes = _hs_prefix_chain(hs, min_len=4)
    rows = (
        db.query(NormativeNote)
        .filter(
            or_(
                (NormativeNote.scope_type == "global"),
                ((NormativeNote.scope_type == "chapter") & (NormativeNote.scope_value == hs2)),
                ((NormativeNote.scope_type == "hs_code") & (NormativeNote.scope_value == hs)),
                ((NormativeNote.scope_type == "prefix") & (NormativeNote.scope_value.in_(prefixes))),
            )
        )
        .order_by(NormativeNote.sort_order.asc(), NormativeNote.id.asc())
        .limit(50)
        .all()
    )
    return rows


def _extract_item_blob(item_data: dict[str, Any] | None) -> str:
    d = item_data or {}
    return _norm_text(
        str(d.get("name_ru") or ""),
        str(d.get("name") or ""),
        str(d.get("name_cn") or ""),
        str(d.get("material") or ""),
        str(d.get("usage") or ""),
        str(d.get("brand") or ""),
    )


def _ai_keyword_warnings(hs: str, item_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    blob = _extract_item_blob(item_data)
    out: list[dict[str, Any]] = []
    if any(k in blob for k in ("bluetooth", "wifi", "wi-fi", "nfc", "шифр", "крипт")):
        out.append(
            {
                "doc_type": "Нотификация ФСБ",
                "legal_ref": "ФСБ РФ / шифровальные средства",
                "title": "Риск: нотификация ФСБ по признакам беспроводной/крипто-функции",
                "detail": "Описание содержит признаки Bluetooth/Wi-Fi/криптографии. Требуется экспертная проверка обязательности нотификации ФСБ.",
                "source": "ai_keyword_risk",
                "priority": 995,
                "registry_match": None,
                "compliance_status": "WARNING",
            }
        )
    if any(k in blob for k in ("chemical", "chem", "хим", "реагент", "solvent", "насос", "pump")):
        out.append(
            {
                "doc_type": "Лицензия",
                "legal_ref": "Экспортный контроль / профильные ограничения",
                "title": "Риск: экспортный контроль / лицензирование",
                "detail": "Описание содержит признаки химической продукции или насосного оборудования. Требуется экспертная проверка по экспортному контролю и лицензионным ограничениям.",
                "source": "ai_keyword_risk",
                "priority": 990,
                "registry_match": None,
                "compliance_status": "WARNING",
            }
        )
    # Для общих кодов электроники усиливаем предупреждение по ФСБ.
    if hs.startswith(("84", "85", "90")) and any(k in blob for k in ("radio", "беспровод", "gsm", "lte", "5g")):
        out.append(
            {
                "doc_type": "Нотификация ФСБ",
                "legal_ref": "ФСБ РФ / шифровальные средства",
                "title": "Риск: возможна нотификация ФСБ для электроники",
                "detail": "Код и описание указывают на радиоэлектронику. Даже при общем коде требуется ручная экспертная проверка на нотификацию ФСБ.",
                "source": "ai_keyword_risk",
                "priority": 985,
                "registry_match": None,
                "compliance_status": "WARNING",
            }
        )
    # Dual-use / экспортный контроль: технические характеристики высокой точности/мощности.
    dual_use_markers = (
        "rpm",
        "об/мин",
        "оборотов",
        "точност",
        "precision",
        "micron",
        "мкм",
        "μm",
        "watt",
        "kw",
        "mw",
        "ghz",
        "мощност",
        "излучен",
        "positioning",
        "позиционирован",
    )
    if any(k in blob for k in dual_use_markers):
        out.append(
            {
                "doc_type": "SANCTION_CONTROL",
                "legal_ref": "Экспортный контроль / Dual-Use",
                "title": "Риск: признаки товара двойного назначения (Dual-Use)",
                "detail": "В описании есть технические характеристики (точность/обороты/мощность/излучение), требующие проверки по экспортному контролю и перечням двойного назначения.",
                "source": "ai_keyword_risk",
                "priority": 1000,
                "registry_match": None,
                "compliance_status": "WARNING",
            }
        )
    return out


def _check_sanction_risks(
    hs_code: str,
    country: str | None,
    item_data: dict[str, Any] | None,
    db: Session,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Проверка санкционных рисков:
    - sanction_import_risks по иерархии префиксов HS (10/9/.../4);
    - country_risks + geo_special_duties(embargo);
    - entity-check по OFAC/EU (ILIKE) для производителя/контрагента.
    """
    docs: list[dict[str, Any]] = []
    blocking_issue = False
    hs = _norm_hs(hs_code)
    fallback_prefixes = [hs[:10], hs[:8], hs[:6], hs[:4]]

    def _country_to_iso2(raw: str | None) -> str:
        c = str(raw or "").strip().upper()
        mapping = {
            "USA": "US",
            "UNITED STATES": "US",
            "U.S.": "US",
            "GERMANY": "DE",
            "DEUTSCHLAND": "DE",
            "CHINA": "CN",
            "VIETNAM": "VN",
        }
        return mapping.get(c, c[:2] if len(c) > 2 and c.isalpha() else c)

    c_iso = _country_to_iso2(country)

    try:
        risk_rows: list[SanctionImportRisk] = []
        for pref in fallback_prefixes:
            if len(pref) < 4:
                continue
            logger.debug("Searching sanctions for prefix: {}", pref)
            rows = db.query(SanctionImportRisk).filter(SanctionImportRisk.hs_code_prefix == pref).all()
            if rows:
                risk_rows = rows
                break
        for r in risk_rows:
            lvl = str(r.risk_level or "risk").strip().lower()
            is_critical = lvl in {"forbidden", "ban", "embargo", "critical"}
            if is_critical:
                blocking_issue = True
            docs.append(
                {
                    "doc_type": "SANCTION_CONTROL",
                    "legal_ref": f"{str(r.jurisdiction or '').strip().upper()} sanctions / HS {r.hs_code_prefix}",
                    "title": "Санкционный риск по коду ТН ВЭД",
                    "detail": str(r.description or "Требуется проверка санкционных ограничений по юрисдикциям."),
                    "source": "sanction_import_risks",
                    "priority": 1400 if is_critical else 1250,
                    "registry_match": None,
                    "compliance_status": "CRITICAL_RISK" if is_critical else "WARNING",
                }
            )
    except Exception as e:
        logger.warning("_check_sanction_risks: sanction_import_risks lookup failed: {}", e)

    try:
        if c_iso:
            cr = db.query(CountryRisk).filter(CountryRisk.iso_code == c_iso).first()
            if cr and bool(cr.is_unfriendly):
                blocking_issue = True
                docs.append(
                    {
                        "doc_type": "SANCTION_CONTROL",
                        "legal_ref": f"CountryRisk/{c_iso}",
                        "title": f"Страна {c_iso} в перечне недружественных юрисдикций",
                        "detail": "Для поставок из данной страны требуется расширенная санкционная проверка; возможны запреты ввоза по отдельным товарным группам.",
                        "source": "country_risks",
                        "priority": 1500,
                        "registry_match": None,
                        "compliance_status": "CRITICAL_RISK",
                    }
                )
            emb = None
            for pref in fallback_prefixes:
                if len(pref) < 4:
                    continue
                logger.debug("Searching embargo for prefix: {}", pref)
                emb = (
                    db.query(GeoSpecialDuty)
                    .filter(
                        GeoSpecialDuty.measure_type == "embargo",
                        GeoSpecialDuty.country_iso.in_([c_iso, "ALL_UNFRIENDLY"]),
                        GeoSpecialDuty.hs_code_prefix == pref,
                    )
                    .first()
                )
                if emb:
                    break
            if emb:
                blocking_issue = True
                docs.append(
                    {
                        "doc_type": "SANCTION_CONTROL",
                        "legal_ref": str(emb.document_basis or f"GeoSpecialDuty/{c_iso}")[:255],
                        "title": "Выявлено эмбарго/запрет ввоза",
                        "detail": str(emb.document_link or "Импорт по данному коду/стране может быть запрещён."),
                        "source": "geo_special_duties",
                        "priority": 1600,
                        "registry_match": None,
                        "compliance_status": "CRITICAL_RISK",
                    }
                )
    except Exception as e:
        logger.warning("_check_sanction_risks: country/embargo lookup failed: {}", e)

    try:
        d = item_data or {}
        entities_raw = [
            d.get("manufacturer"),
            d.get("producer"),
            d.get("counterparty"),
            d.get("supplier"),
            d.get("seller"),
            d.get("exporter"),
            d.get("consignor"),
            d.get("brand"),
        ]
        entities = [str(x).strip() for x in entities_raw if str(x or "").strip()]
        for name in entities[:8]:
            if len(name) < 3:
                continue
            ofac_hit = db.query(OfacSdnList).filter(OfacSdnList.name.ilike(f"%{name}%")).first()
            if ofac_hit:
                blocking_issue = True
                docs.append(
                    {
                        "doc_type": "SANCTION_CONTROL",
                        "legal_ref": "OFAC SDN",
                        "title": f"Контрагент/производитель найден в SDN: {name}",
                        "detail": f"Совпадение с OFAC SDN: {ofac_hit.name} ({ofac_hit.type}). Требуется блокирующая проверка.",
                        "source": "ofac_sdn_list",
                        "priority": 1700,
                        "registry_match": None,
                        "compliance_status": "CRITICAL_RISK",
                    }
                )
            eu_hit = db.query(EuSanctionsList).filter(EuSanctionsList.entity_name.ilike(f"%{name}%")).first()
            if eu_hit:
                docs.append(
                    {
                        "doc_type": "SANCTION_CONTROL",
                        "legal_ref": f"EU sanctions / HS {eu_hit.hs_code or 'N/A'}",
                        "title": f"Контрагент/производитель найден в списке санкций ЕС: {name}",
                        "detail": str(eu_hit.description or eu_hit.entity_name or "")[:1200],
                        "source": "eu_sanctions_list",
                        "priority": 1450,
                        "registry_match": None,
                        "compliance_status": "CRITICAL_RISK" if (eu_hit.hs_code and hs.startswith(str(eu_hit.hs_code))) else "WARNING",
                    }
                )
                if eu_hit.hs_code and hs.startswith(str(eu_hit.hs_code)):
                    blocking_issue = True
    except Exception as e:
        logger.warning("_check_sanction_risks: entity sanctions lookup failed: {}", e)

    return docs, blocking_issue


def build_compliance_document_items(
    hs_code: str,
    item_data: dict[str, Any] | None,
    country: str | None,
    db: Session,
) -> dict[str, Any]:
    """
    Финальная сборка документов комплаенса для payment_profile:
    - база требований из non_tariff_measures/non_tariff_rules + tr_ts_acts;
    - заметки из normative_notes;
    - AI-предупреждения по ключевым словам;
    - проверка реестров (registry_matcher) с присвоением REQUIRED/MATCHED/WARNING.
    """
    hs = _norm_hs(hs_code)
    reqs = resolve_compliance_requirements(hs, item_data, db)

    tr_rows = db.query(TrTsAct).all()
    tr_title_by_code: dict[str, str] = {str(x.act_code or "").strip(): str(x.short_name or x.full_title or "").strip() for x in tr_rows}

    docs: list[dict[str, Any]] = []
    blocking_issue = False
    for r in reqs:
        tr_codes = _extract_tr_codes(r.legal_ref, r.title, r.detail)
        extra_tr = ""
        if tr_codes:
            named = [f"{c} ({tr_title_by_code[c]})" for c in tr_codes if tr_title_by_code.get(c)]
            if named:
                extra_tr = " | Техрегламенты: " + "; ".join(named)

        reg_match = match_document_in_registries(
            doc_type=r.doc_type,
            title=r.title,
            legal_ref=r.legal_ref,
            item_data=item_data,
            db=db,
        )
        status = "MATCHED" if reg_match else "REQUIRED"
        docs.append(
            {
                "doc_type": r.doc_type,
                "legal_ref": r.legal_ref,
                "title": r.title,
                "detail": (r.detail + extra_tr)[:1200],
                "source": r.source,
                "priority": int(r.priority),
                "registry_match": reg_match,
                "compliance_status": status,
            }
        )

    # Нормативные примечания: всегда как WARNING для эксперта.
    for note in _lookup_normative_notes(hs, db):
        cat = str(note.category or "").strip() or "general"
        docs.append(
            {
                "doc_type": "Иное",
                "legal_ref": f"NormativeNote/{cat}",
                "title": str(note.title or "Нормативное примечание")[:255],
                "detail": str(note.body or "")[:1200],
                "source": "normative_notes",
                "priority": 520,
                "registry_match": None,
                "compliance_status": "WARNING",
            }
        )

    docs.extend(_ai_keyword_warnings(hs, item_data))

    sanction_docs, sanction_blocking = _check_sanction_risks(hs, country, item_data, db)
    if sanction_docs:
        # Санкционный блок должен идти в начале списка.
        docs = sanction_docs + docs
    if sanction_blocking:
        blocking_issue = True

    # Если страна не указана — добавляем предупреждение для экспертной проверки рисков.
    if not str(country or "").strip():
        docs.append(
            {
                "doc_type": "Иное",
                "legal_ref": "Страна происхождения",
                "title": "Недостаточно данных для полной комплаенс-проверки",
                "detail": "Не указана страна происхождения. Проверка санкционных/страновых ограничений и отдельных нетарифных мер требует верификации экспертом.",
                "source": "resolver_guard",
                "priority": 510,
                "registry_match": None,
                "compliance_status": "WARNING",
            }
        )

    # Дедуп и сортировка.
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for d in sorted(docs, key=lambda x: (-int(x.get("priority") or 0), str(x.get("doc_type") or ""), str(x.get("title") or ""))):
        key = (
            str(d.get("doc_type") or "").strip().upper(),
            str(d.get("legal_ref") or "").strip().upper(),
            str(d.get("title") or "").strip().upper(),
            str(d.get("compliance_status") or "").strip().upper(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return {"documents": out, "blocking_issue": bool(blocking_issue)}
