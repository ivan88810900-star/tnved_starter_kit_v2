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


def _extract_explicit_hs_codes(text: str) -> list[str]:
    """Явные коды в тексте: только 6/8/10 знаков (4-значные дают много ложных срабатываний)."""
    if not text:
        return []
    pattern = re.compile(r"(?<!\d)(\d{10}|\d{8}|\d{6})(?!\d)")
    candidates = pattern.findall(text)
    valid: list[str] = []
    for c in candidates:
        if not c.isdigit():
            continue
        ch = int(c[:2])
        if 1 <= ch <= 97:
            valid.append(c)
    return list(dict.fromkeys(valid))


async def classify_document(doc_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        doc = db.query(RegulatoryDocument).filter_by(id=doc_id).first()
        if not doc:
            logger.warning(f"Документ не найден: {doc_id}")
            return []

        explicit_codes = _extract_explicit_hs_codes(f"{doc.title} {doc.body or ''}")
        mappings_data: list[dict[str, Any]] = []

        for code in explicit_codes:
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
            RegulatoryDocHsMapping.source.in_(["ai", "regex"]),
        ).delete(synchronize_session=False)

        for m in mappings_data:
            db.add(RegulatoryDocHsMapping(doc_id=doc_id, **m))

        db.commit()
        logger.info(f"Документ {doc_id}: создано {len(mappings_data)} HS-привязок")
        return mappings_data
