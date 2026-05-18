"""Правила-триггеры для определения дополнительных мер по описанию."""

from __future__ import annotations

from typing import Any

TRIGGERS: list[dict[str, Any]] = [
    {
        "keywords": ["wi-fi", "wifi", "bluetooth", "беспроводн", "радиомодуль"],
        "negative": ["без wi-fi", "без wifi", "без bluetooth", "без беспровод"],
        "measure": {
            "measure_type": "notification",
            "permit_type": "НФ",
            "description": "Нотификация ФСБ (радиоэлектронные средства)",
            "document_required": "Нотификация ФСБ России",
            "regulatory_act": "Решение Коллегии ЕЭК №30",
        },
    },
    {
        "keywords": ["шифрован", "криптограф", "encrypt"],
        "negative": [],
        "measure": {
            "measure_type": "notification",
            "permit_type": "НФ",
            "description": "Нотификация ФСБ (криптография)",
            "document_required": "Нотификация ФСБ России",
            "regulatory_act": "Решение Коллегии ЕЭК №30",
        },
    },
    {
        "keywords": ["лазер"],
        "negative": [],
        "measure": {
            "measure_type": "certificate",
            "permit_type": "СЭЗ",
            "description": "Санитарно-эпидемиологическое заключение (лазерная техника)",
            "document_required": "СЭЗ Роспотребнадзора",
            "regulatory_act": "СанПиН 5804-91",
        },
    },
    {
        "keywords": ["детск", "ребенк", "ребёнк", "для детей", "детям"],
        "negative": [
            "для взрослых",
            "взрослый",
            "взрослая",
            "взрослое",
            "взрослые",
            "не для детей",
            "18+",
            "старше 18",
        ],
        "measure": {
            "measure_type": "certificate",
            "permit_type": "СС",
            "description": "Сертификация продукции для детей",
            "document_required": "СС по ТР ТС 007/2011",
            "regulatory_act": "ТР ТС 007/2011",
        },
    },
    {
        "keywords": ["пищевой контакт", "контакт с пищ", "посуда", "столов"],
        "negative": [],
        "measure": {
            "measure_type": "certificate",
            "permit_type": "ДС",
            "description": "Соответствие требованиям к материалам, контактирующим с пищей",
            "document_required": "ДС по ТР ТС 005/2011",
            "regulatory_act": "ТР ТС 005/2011",
        },
    },
    {
        "keywords": ["медицин", "медиц"],
        "negative": ["не медицинск"],
        "measure": {
            "measure_type": "permit",
            "permit_type": "РУ",
            "description": "Регистрационное удостоверение медицинского изделия",
            "document_required": "РУ Росздравнадзора",
            "regulatory_act": "ПП РФ №1416",
        },
    },
    {
        "keywords": ["алкоголь", "вино", "пиво", "крепкий", "спиртн"],
        "negative": ["безалкогол", "не содержит алкогол"],
        "measure": {
            "measure_type": "license",
            "permit_type": "ЛЗ",
            "description": "Лицензия на импорт алкогольной продукции",
            "document_required": "Лицензия Росалкогольрегулирования",
            "regulatory_act": "ФЗ №171",
        },
    },
    {
        "keywords": ["оруж", "патрон", "огнестрел"],
        "negative": ["игрушеч"],
        "measure": {
            "measure_type": "license",
            "permit_type": "ЛЗ",
            "description": "Лицензия на ввоз оружия",
            "document_required": "Разрешение МВД/ФСБ",
            "regulatory_act": "ФЗ №150",
        },
    },
]


def find_measures_by_description(description: str, hs_code: str) -> list[dict[str, Any]]:
    """Возвращает доп. меры на основе ключевых слов в описании."""
    if not description:
        return []

    desc_lower = description.lower()
    result: list[dict[str, Any]] = []

    for trigger in TRIGGERS:
        positive_match = any(kw in desc_lower for kw in trigger["keywords"])
        if not positive_match:
            continue
        negative_match = any(neg in desc_lower for neg in trigger.get("negative", []))
        if negative_match:
            continue
        measure = dict(trigger["measure"])
        measure.update(
            {
                "commodity_code": hs_code,
                "tr_ts_code": None,
                "match_prefix_len": 10,
                "source_level": "trigger",
                "trigger": next((kw for kw in trigger["keywords"] if kw in desc_lower), ""),
                "legal_ref": trigger["measure"].get("regulatory_act", ""),
            }
        )
        result.append(measure)

    return result
