"""Реестр источников ведомственных документов."""
from __future__ import annotations

SOURCES: list[dict[str, object]] = [
    {"agency": "FTS", "name": "ФТС — документы", "url": "https://customs.gov.ru/document", "parser": "html_list", "active": True},
    {"agency": "FTS", "name": "ФТС — письма", "url": "https://customs.gov.ru/folder/483", "parser": "html_list", "active": True},
    {"agency": "MPT", "name": "Минпромторг", "url": "https://minpromtorg.gov.ru/docs/", "parser": "html_list", "active": True},
    {
        "agency": "MINPROM",
        "name": "Минпром РФ (наследие; часть функций — Минпромторг)",
        "url": "https://minpromtorg.gov.ru/",
        "parser": "html_list",
        "active": False,
    },
    {
        "agency": "RPN",
        "name": "Роспотребнадзор",
        "url": "https://www.rospotrebnadzor.ru/documents/orders.php",
        "parser": "html_list",
        "active": True,
    },
    {
        "agency": "RSN",
        "name": "Россельхознадзор",
        "url": "https://fsvps.gov.ru/normativnye-pravovye-akty/",
        "parser": "html_list",
        "active": True,
    },
    {"agency": "EEC", "name": "ЕЭК — Решения Коллегии", "url": "https://docs.eaeunion.org/docs/", "parser": "html_list", "active": True},
    {"agency": "EEC", "name": "ЕЭК — Решения Совета", "url": "https://docs.eaeunion.org/docs-eaeu", "parser": "html_list", "active": True},
    {
        "agency": "PRAVO_GOV",
        "name": "Официальный портал pravo.gov.ru",
        "url": "http://publication.pravo.gov.ru",
        "parser": "html_list",
        "active": True,
    },
    {"agency": "MIN_FIN", "name": "Минфин", "url": "https://minfin.gov.ru/ru/document/", "parser": "html_list", "active": True},
    {"agency": "CBR", "name": "ЦБ РФ", "url": "https://www.cbr.ru/about_br/publ/", "parser": "html_list", "active": True},
]

AGENCY_NAMES: dict[str, str] = {
    "FTS": "ФТС РФ",
    "MPT": "Минпромторг",
    "MINPROM": "Минпром РФ",
    "RPN": "Роспотребнадзор",
    "RSN": "Россельхознадзор",
    "EEC": "ЕЭК",
    "PRAVO_GOV": "pravo.gov.ru",
    "MIN_FIN": "Минфин",
    "CBR": "ЦБ РФ",
}

DOC_TYPE_NAMES: dict[str, str] = {
    "order": "Приказ",
    "letter": "Информационное письмо",
    "decision": "Решение",
    "info": "Информационное сообщение",
    "methodic": "Методические рекомендации",
    "decree": "Постановление",
    "regulation": "Регламент",
    "explanation": "Разъяснение",
}
