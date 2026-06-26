"""AI-классификация документов: к каким HS-кодам относится."""
from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from ..db import SessionLocal
from ..models.regulatory import RegulatoryDocHsMapping, RegulatoryDocument


def _build_classification_prompt(doc: RegulatoryDocument) -> str:
    return f"""Ты эксперт по таможенному регулированию ЕАЭС.

Документ ведомства:
Ведомство: {doc.agency or ""}
Тип: {doc.doc_type or ""}
Номер: {doc.doc_number or ""}
Заголовок: {doc.title}

Текст (первые 3000 символов):
{(doc.body or "")[:3000]}

ЗАДАЧА: определи к каким товарам по ТН ВЭД относится этот документ.

Верни JSON массив (или [] если документ носит общий характер):
[
  {{
    "hs_prefix": "8528",
    "scope": "import|export|both",
    "relevance": "direct|domain|implicit",
    "confidence": 0.0,
    "note": "Краткое пояснение почему именно эта связь"
  }}
]

Правила:
- hs_prefix: 2, 4, 6, 8 или 10 знаков
- direct = HS-код явно упомянут
- domain = упомянута товарная группа
- implicit = по контексту
- confidence: 1.0 для direct, 0.7-0.9 для domain, 0.5-0.7 для implicit
- Если документ общий (методика для всех товаров) — верни []
- Максимум 20 привязок

ТОЛЬКО JSON."""


KEYWORD_HS_MAP: dict[str, list[str]] = {
    "смартфон": ["851712"],
    "телефон мобильный": ["851712"],
    "мобильный телефон": ["851712"],
    "ноутбук": ["847130"],
    "планшет": ["847130"],
    "компьютер": ["8471"],
    "телевизор": ["8528"],
    "монитор": ["852849"],
    "пылесос": ["8508"],
    "холодильник": ["8418"],
    "стиральная машина": ["8450"],
    "кондиционер": ["841510"],
    "автомобиль легковой": ["8703"],
    "электромобиль": ["870380"],
    "мотоцикл": ["8711"],
    "грузовик": ["8704"],
    "шина": ["4011"],
    "покрышка": ["4011"],
    "обувь": ["6403"],
    "кроссовки": ["6404"],
    "одежд": ["61", "62"],
    "текстиль": ["61", "62", "63"],
    "мебель": ["9401", "9403"],
    "игрушка": ["9503"],
    "косметика": ["3304"],
    "парфюмерия": ["3303"],
    "шампунь": ["330510"],
    "лекарств": ["3004"],
    "медицинск": ["9018"],
    "бад": ["210690"],
    "биологически активн": ["210690"],
    "вино": ["2204"],
    "пиво": ["2203"],
    "виски": ["220830"],
    "алкогол": ["2208"],
    "табак": ["2401"],
    "сигарет": ["2402"],
    "мясо": ["0201", "0202"],
    "говядин": ["0201"],
    "свинин": ["0203"],
    "курятин": ["0207"],
    "рыба": ["0302", "0303"],
    "молок": ["0401", "0402"],
    "сыр": ["0406"],
    "масло сливочн": ["0405"],
    "яблок": ["0808"],
    "бананы": ["080390"],
    "картофель": ["0701"],
    "пшениц": ["1001"],
    "кофе": ["0901"],
    "чай": ["0902"],
    "сахар": ["1701"],
    "шоколад": ["1806"],
    "удобрен": ["31"],
    "пластмасс": ["39"],
    "каучук": ["40"],
    "резин": ["40"],
    "бумаг": ["48"],
    "стекл": ["70"],
    "сталь": ["72"],
    "алюмини": ["76"],
    "медь": ["74"],
    "аккумулятор": ["8507"],
    "батаре": ["8506"],
    "провод": ["8544"],
    "кабел": ["8544"],
    "лампа": ["9405"],
    "светодиод": ["940540"],
    "часы": ["91"],
    "оружи": ["93"],
    "боеприпас": ["9306"],
    "взрывчат": ["36"],
    "драгоценн": ["71"],
    "алмаз": ["7102"],
    "золот": ["7108"],
    "нефт": ["2709"],
    "бензин": ["2710"],
    "дизельн": ["271019"],
    "дезинфицирующ": ["3808"],
    "пестицид": ["3808"],
    "гербицид": ["3808"],
}


def _extract_explicit_hs_codes(text: str) -> list[str]:
    """Explicit codes in text: 4-10 digits when in clear HS context, 6-10 standalone."""
    if not text:
        return []
    valid: list[str] = []

    hs_context = re.compile(
        r"(?:ТН\s*ВЭД|HS|код(?:у|а|ом)?\s+ТН|позици[яиейю]|субпозици[яиейю]|товарн)"
        r"\s*(?:ЕАЭС\s*)?[:\s]*(\d{4,10})",
        re.IGNORECASE,
    )
    for m in hs_context.finditer(text):
        code = m.group(1)
        ch = int(code[:2])
        if 1 <= ch <= 97:
            valid.append(code)

    standalone = re.compile(r"(?<!\d)(\d{10}|\d{8}|\d{6})(?!\d)")
    for m in standalone.finditer(text):
        code = m.group(1)
        ch = int(code[:2])
        if 1 <= ch <= 97 and code not in valid:
            valid.append(code)

    return list(dict.fromkeys(valid))


def _extract_keyword_hs_codes(text: str) -> list[tuple[str, str]]:
    """Extract HS codes from product keywords in text. Returns (hs_prefix, keyword)."""
    if not text:
        return []
    text_lower = text.lower()
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for keyword, prefixes in KEYWORD_HS_MAP.items():
        if keyword in text_lower:
            for p in prefixes:
                if p not in seen:
                    seen.add(p)
                    found.append((p, keyword))
    return found


async def classify_document(doc_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        doc = db.query(RegulatoryDocument).filter_by(id=doc_id).first()
        if not doc:
            logger.warning(f"Документ не найден: {doc_id}")
            return []

        full_text = f"{doc.title} {doc.body or ''}"
        explicit_codes = _extract_explicit_hs_codes(full_text)
        mappings_data: list[dict[str, Any]] = []
        seen_prefixes: set[str] = set()

        for code in explicit_codes:
            seen_prefixes.add(code)
            mappings_data.append(
                {
                    "hs_prefix": code,
                    "scope": "import",
                    "relevance": "direct",
                    "confidence": 1.0,
                    "source": "regex",
                    "note": f"HS-код явно упомянут: {code}",
                }
            )

        keyword_hits = _extract_keyword_hs_codes(full_text)
        for hs_prefix, keyword in keyword_hits:
            if hs_prefix in seen_prefixes:
                continue
            seen_prefixes.add(hs_prefix)
            mappings_data.append(
                {
                    "hs_prefix": hs_prefix,
                    "scope": "import",
                    "relevance": "domain",
                    "confidence": 0.8,
                    "source": "keyword",
                    "note": f"Ключевое слово: {keyword}",
                }
            )

        try:
            from .ntm_enricher import call_llm

            prompt = _build_classification_prompt(doc)
            response = await call_llm(prompt, temperature=0.1)

            match = re.search(r"\[.*\]", response, re.DOTALL)
            if match:
                ai_items = json.loads(match.group(0))
                for item in ai_items[:20]:
                    if not isinstance(item, dict):
                        continue
                    hs_prefix = str(item.get("hs_prefix", "")).strip()
                    if not hs_prefix or not hs_prefix.isdigit():
                        continue
                    if any(m["hs_prefix"] == hs_prefix for m in mappings_data):
                        continue
                    mappings_data.append(
                        {
                            "hs_prefix": hs_prefix,
                            "scope": item.get("scope", "import"),
                            "relevance": item.get("relevance", "implicit"),
                            "confidence": float(item.get("confidence", 0.5)),
                            "source": "ai",
                            "note": str(item.get("note", ""))[:500],
                        }
                    )
        except Exception as e:
            logger.warning(f"AI не сработал для {doc_id}: {e}")

        db.query(RegulatoryDocHsMapping).filter(
            RegulatoryDocHsMapping.doc_id == doc_id,
            RegulatoryDocHsMapping.source.in_(["ai", "regex", "keyword"]),
        ).delete(synchronize_session=False)

        for m in mappings_data:
            db.add(RegulatoryDocHsMapping(doc_id=doc_id, **m))

        db.commit()
        logger.info(f"Документ {doc_id}: создано {len(mappings_data)} HS-привязок")
        return mappings_data
