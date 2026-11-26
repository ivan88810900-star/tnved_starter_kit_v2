"""Read-only evidence available to the local normative-block endpoint."""
import hashlib
import json
import os
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from .normative_requirements_block import build_normative_requirements_block
from .normative_store import lookup_tr_ts_acts_by_codes
from .tr_ts_catalog import get_tr_ts_requirements


# Only the checksum of the permitted local excerpt is part of the product.
_SGR_EXCERPT_SHA256 = "7b2072665d3200f5987571221ba6033ef907c313ae9d19d9c552f73010a0afa1"


def _product_documents(permits: list[dict] | None) -> dict:
    declared = [p for p in permits or [] if p.get("type", "").strip() and p.get("number", "").strip()]
    result = {
        "submitted_count": len(declared),
        "status": "SUBMITTED_UNVERIFIED" if declared else "NOT_PROVIDED",
        "registry_checked": False,
        "registry_matches": 0,
        "shipment_verified": False,
    }
    numbers = {
        p["number"].strip().upper() for p in declared
        if p["type"].strip().upper() in {"СГР", "SGR", "СВИДЕТЕЛЬСТВО О ГОСУДАРСТВЕННОЙ РЕГИСТРАЦИИ"}
    }
    if not numbers:
        return result
    path = os.getenv("TARIFF_PILOT_SGR_EVIDENCE")
    if not path:
        result["comparison"] = "EXCERPT_NOT_CONFIGURED"
        return result
    try:
        source = Path(path)
        if not source.is_file():
            raise ValueError("missing excerpt")
        with source.open("rb") as handle:
            raw = handle.read(16_385)
        if len(raw) > 16_384 or hashlib.sha256(raw).hexdigest() != _SGR_EXCERPT_SHA256:
            raise ValueError("unexpected excerpt")
        record = json.loads(raw)
    except (OSError, ValueError) as error:
        raise HTTPException(503, "Требуется проверить локальный фрагмент реестра СГР.") from error
    result.update(
        registry_checked=True, comparison="NO_NUMBER_IN_LOCAL_EXCERPT",
        registry_scope="LOCAL_ONE_RECORD", snapshot_date=record["snapshot_date"],
    )
    if record["number"].upper() in numbers:
        result.update(
            registry_matches=1, comparison="NUMBER_MATCH_ONLY",
            registry_status=record["registry_status"], issued_on=record["issued_on"],
            registered_product=record["product"],
        )
    return result


def _cosmetics_review(description: str, country: str | None, permits: list[dict] | None) -> dict:
    decision = "https://docs.eaeunion.org/documents/435/9762/"
    questions = [
        "Каковы назначение и способ применения по этикетке? Есть ли исключение из статьи 1 пункта 3?",
        "Это готовая косметика, косметика на носителе или косметика, нанесённая на изделие? Для последней категории действуют особые условия статьи 1 пункта 2.",
        "Для какого возраста предназначен товар? Проверьте состав, назначение и все категории приложения 12.",
        "Когда продукцию выпускают в обращение и какая редакция действует на эту дату?",
    ]
    if not description.strip():
        questions.insert(0, "Как обозначены на этикетке изделие, изготовитель и артикул?")
    if not (country or "").strip():
        questions.append("Какова страна происхождения товара?")
    documents = _product_documents(permits)
    if documents["submitted_count"]:
        questions.append("Совпадают ли запись реестра, изготовитель, продукция, область и срок представленного документа?")
    else:
        questions.append("Есть ли документ на эту продукцию и запись о нём в официальном реестре?")

    return {
        "status": "NEEDS_CLARIFICATION",
        "questions": questions,
        "source_routes": [
            {
                "document_type": "Государственная регистрация",
                "condition": "Если к продукции применима статья 6 с учётом статьи 1 пунктов 2 и 3 и товар соответствует позиции приложения 12, включая детскую косметику.",
                "locator": "ТР ТС 009/2011, ст. 6 п. 2, приложение 12; решение № 114, приложение, пп. 6, 13",
                "source_url": decision,
            },
            {
                "document_type": "Декларация о соответствии",
                "condition": "Если к продукции применима статья 6 с учётом статьи 1 пунктов 2 и 3 и товар не входит ни в одну позицию приложения 12.",
                "locator": "ТР ТС 009/2011, ст. 6 п. 2; решение № 114, приложение, п. 6",
                "source_url": decision,
            },
        ],
        "product_documents": documents,
        "edition": {
            "status": "PARTIALLY_RECONSTRUCTED",
            "scope": {"locator": "Решение № 114, приложение, п. 2 → ст. 1, пп. 1–3", "source_url": decision},
            "scope_limit": "Для косметики, нанесённой на изделия и не относящейся к косметике на носителях, ст. 1 п. 2 предусматривает только перечисленные требования ст. 5.",
            "decisions": [
                {"number": 114, "general_effective_date": "2025-12-24", "source_url": decision},
                {"number": 24, "general_effective_date": "2025-12-24", "source_url": "https://docs.eaeunion.org/documents/446/9894/"},
                {"number": 74, "general_effective_date": "2026-10-28", "source_url": "https://docs.eaeunion.org/documents/447/10246/"},
                {"number": 31, "general_effective_date": "2026-10-28", "source_url": "https://docs.eaeunion.org/documents/463/10557/"},
            ],
            "limit": "Для отдельных положений сроки отличаются. Для ранее выданного документа сверяют п. 1 решений № 24 и № 31, в том числе исключение в подп. «д» решения № 31.",
        },
    }


# Only the source rows examined in the official publication are projected here.
_TABLEWARE_SOURCE = "https://publication.pravo.gov.ru/document/0001202505150040"
_TABLEWARE_ROWS = {
    "2.1": (
        "Стальная эмалированная хозяйственная посуда для взрослых.",
        "7323 94 000 0", 219,
    ),
    "3.1": (
        "Хозяйственная посуда из коррозионностойкой стали для взрослых.",
        "7323 93 000 0", 221,
    ),
    "4.1": (
        "Столовые приборы и кухонные принадлежности из коррозионностойкой стали, кроме изделий для детей.",
        "7323 93 000 0 или из группы 82", 221,
    ),
    "47.1": (
        "Хозяйственная посуда из бесцветного жаростойкого стекла либо из ситаллов.",
        "из 7013", 407,
    ),
}


def _tableware_candidates(code: str) -> tuple[str, ...]:
    if code.startswith("7013"):
        return ("47.1",)
    # The published «из 82» is narrower than group 82. The local catalog
    # explicitly identifies these cutlery positions as stainless steel.
    return {
        "7323940000": ("2.1",),
        "7323930000": ("3.1", "4.1"),
        "8215201000": ("4.1",),
        "8215991000": ("4.1",),
    }.get(code, ())


def _unverified_submitted_documents(permits: list[dict] | None) -> dict:
    submitted = sum(1 for p in permits or [] if p.get("type", "").strip() and p.get("number", "").strip())
    return {
        "submitted_count": submitted,
        "status": "SUBMITTED_UNVERIFIED" if submitted else "NOT_PROVIDED",
        "registry_checked": False, "registry_matches": 0, "shipment_verified": False,
    }


def _tableware_review(positions: tuple[str, ...], permits: list[dict] | None) -> dict:
    routes = []
    for position in positions:
        description, selector, page = _TABLEWARE_ROWS[position]
        routes.append({
            "document_type": "Декларация о соответствии",
            "condition": description + " Проверяется сочетание описания и кода: " + selector + ".",
            "locator": f"ПП РФ № 2425, перечень декларирования, п. {position}, сноска 2. Редакция № 642, PDF с. {page}.",
            "source_url": f"{_TABLEWARE_SOURCE}?index={page}",
        })
    questions = [
        "Каковы материал и покрытие по этикетке или паспорту изделия?",
        "Что это за изделие и для какого возраста оно предназначено? Для детской продукции отдельно проверьте область ТР ТС 007/2011.",
        "Когда и где товар выпускают в обращение? Проверьте применимость российских правил и переходных положений на эту дату.",
        "Есть ли протокол аккредитованной лаборатории и документ, охватывающий данный товар, изготовителя и партию или серию?",
    ]
    if "47.1" in positions:
        questions[0] = "Подтверждены ли бесцветное жаростойкое стекло или ситалл и хозяйственное назначение посуды?"
    elif "4.1" in positions:
        questions[0] = "Это посуда, столовый прибор или кухонная принадлежность? Подтверждена ли коррозионностойкая сталь?"
    else:
        questions[0] = "Подтверждены ли стальная основа и эмаль? Изделие из чугунного литья имеет другой код."

    return {
        "family": "RF_TABLEWARE",
        "status": "NEEDS_CLARIFICATION",
        "questions": questions,
        "source_routes": routes,
        "product_documents": _unverified_submitted_documents(permits),
        "edition": {
            "status": "PARTIALLY_RECONSTRUCTED",
            "review_date": "2026-11-25",
            "scope": {"locator": "ПП РФ № 2425, перечень декларирования, сноска 2 в редакции № 642",
                      "source_url": _TABLEWARE_SOURCE + "?index=670"},
            "scope_limit": (
                "Сноска 2 связывает декларацию с протоколом испытаний аккредитованной лаборатории. "
                "ПП № 63 перенесло возможность выбора эквивалентной схемы сертификации в заголовок графы «Наименование продукции». "
                "Для товара детского назначения отдельно проверяется союзный регламент."
            ),
            "decisions": [
                {"number": 642, "label": "ПП РФ № 642", "general_effective_date": "2025-09-01",
                 "source_url": _TABLEWARE_SOURCE},
                {"number": 1403, "label": "ПП РФ № 1403", "general_effective_date": "2025-09-11",
                 "source_url": "https://publication.pravo.gov.ru/document/0001202509110019"},
                {"number": 63, "label": "ПП РФ № 63", "general_effective_date": "2026-01-29",
                 "source_url": "https://publication.pravo.gov.ru/document/0001202601290022"},
                {"number": 797, "label": "Решение КТС № 797 о ТР ТС 007/2011",
                 "source_url": "https://docs.eaeunion.org/documents/201/670/"},
            ],
            "limit": (
                "№ 63 распространяется на отношения с 01.09.2025. Для охваченной № 1403 продукции "
                "с изменившимися стандартами предел действия старых документов — 01.09.2026. "
                "Заключение о поставке требует даты операции и проверки документа в реестре."
            ),
        },
    }


_CHILD_TR = "https://docs.eaeunion.org/documents/201/670/"
_CHILD_AMENDMENT = "https://docs.eaeunion.org/documents/317/3175/"


def _child_tableware_review(code: str, use: str | None, age: str | None, permits: list[dict] | None) -> dict:
    drinking_vessel = code == "7013371000"
    tableware = code in {"7013420000", "7013491000", "7013499100", "7013499900"}
    routes = []
    questions = [
        "Выпускается ли новая посуда в обращение в ЕАЭС? Проверьте этикетку и назначение для контакта с пищей. Изделия медицинского назначения, игрушки и изделия по индивидуальному заказу исключены из области регламента.",
        "Есть ли документ на это изделие и изготовителя в официальном реестре? Сверьте дату выпуска, партию или серию и срок документа.",
    ]
    if not drinking_vessel and (not tableware or use == "child_drinking_cup"):
        questions.insert(0, "Указанный код выходит за проверенные позиции стеклянной столовой посуды. Сверьте материал, вид изделия и выбранный код.")
    elif drinking_vessel and use != "child_drinking_cup":
        questions.insert(0, "Обозначил ли изготовитель стакан для питья как детскую чашку, поильник или аналогичное по функции изделие? Проверьте маркировку или техническое описание.")
    elif not drinking_vessel and use != "child_food_glass":
        questions.insert(0, "Уточните материал и пищевое назначение посуды по маркировке изготовителя.")
    elif age in ("under_3", "over_3"):
        younger = age == "under_3"
        document = "Государственная регистрация с последующим декларированием соответствия" if younger else "Сертификат соответствия"
        category = "для детей до 3 лет" if younger else "для детей старше 3 лет и подростков"
        paragraph, amendment = ("2", "а") if younger else ("4", "в")
        product = "новую стеклянную пищевую посуду"
        locator = f"ТР ТС 007/2011, ст. 12 п. {paragraph}. Решение Совета ЕЭК № 51, приложение, п. 6 подп. «{amendment}»."
        source = _CHILD_AMENDMENT
        if drinking_vessel:
            product = "новую детскую стеклянную чашку, поильник или функционально аналогичный сосуд для питья"
            entry = "6" if younger else "6¹"
            locator += f" Перечень № 28, раздел IV, поз. {entry}, «из 7013», с изменениями № 235."
            source = "https://docs.eaeunion.org/documents/251/9400/" if younger else "https://docs.eaeunion.org/documents/335/4893/"
        routes.append({
            "document_type": document,
            "condition": f"Если изготовитель предназначил {product} {category} и выполнены условия статьи 1.",
            "locator": locator,
            "source_url": source,
        })
    elif age == "exactly_3":
        questions.insert(0, "Формулировки статьи 12 — «до 3 лет» и «старше 3 лет». Уточните у изготовителя полный возрастной диапазон: по одному указанию «3 года» форма документа не определена.")
    elif age == "adult":
        questions.insert(0, "Детское назначение и выбор возраста «для взрослых» противоречат друг другу. Сверьте маркировку изготовителя.")
    else:
        questions.insert(0, "Для какого возраста изготовитель предназначил эту посуду? Проверьте полный диапазон на маркировке.")
    return {
        "family": "EAEU_CHILD_GLASS_TABLEWARE",
        "status": "NEEDS_CLARIFICATION",
        "questions": questions,
        "source_routes": routes,
        "product_documents": _unverified_submitted_documents(permits),
        "edition": {
            "status": "PARTIALLY_RECONSTRUCTED",
            "review_date": "2026-11-25",
            "scope": {"locator": "ТР ТС 007/2011, ст. 1 п. 1, ст. 2, приложение № 1 (посуда), ст. 4 п. 4", "source_url": _CHILD_TR},
            "scope_limit": "Возраст определяется по назначению на маркировке изготовителя. Дети — до 14 лет, подростки — от 14 до 18 лет. Для горячей пищи и контактирующей с пищей поверхности стекла проверяют требования статьи 4 пункта 4.",
            "decisions": [
                {"number": 797, "label": "Решение КТС № 797 (начало действия ТР)", "general_effective_date": "2012-07-01", "source_url": _CHILD_TR},
                {"number": 51, "label": "Решение Совета ЕЭК № 51", "general_effective_date": "2018-09-25", "source_url": _CHILD_AMENDMENT},
                {"number": 195, "label": "Решение Коллегии ЕЭК № 195", "general_effective_date": "2023-01-15", "source_url": "https://docs.eaeunion.org/documents/399/7129/"},
                {"number": 147, "label": "Решение Совета ЕЭК № 147", "general_effective_date": "2023-03-26", "source_url": "https://docs.eaeunion.org/documents/401/6944/"},
            ],
            "limit": "Переход по № 195 касается продукции, затронутой № 147. Для её СГР, выданных до 26.03.2023, действует срок документа с пределом 25.03.2028 включительно. Охват конкретной поставки требует проверки.",
        },
    }


_CHILD_BOOK_TYPES = {
    "4901990000": {"child_printed_book"},
    "4903000000": {"child_picture_book", "child_coloring_book"},
}
_CHILD_BOOK_LIST = "https://docs.eaeunion.org/documents/251/9400/"


def _child_publication_review(code: str, kind: str | None, age: int | None, permits: list[dict] | None) -> dict:
    routes = []
    questions = []
    if code not in _CHILD_BOOK_TYPES:
        questions.append("Выбранный код выходит за проверенные позиции детских печатных книг. Сверьте вид издания и код.")
    elif kind == "textbook":
        questions.append("Статья 1 п. 1 исключает учебники, учебные пособия и электронные учебные издания. Сверьте назначение по выходным сведениям издателя.")
    elif kind == "toy_book":
        questions.append("Самостоятельная игрушка исключена из ст. 1 п. 1. Если это печатное издание с игрушкой, отдельно проверьте его текст по ст. 8 п. 10 и характеристики вложения.")
    elif not kind or kind == "unknown":
        questions.append("Укажите вид нового бумажного издания по сведениям издателя: книга для чтения, книжка-картинка или раскраска.")
    elif kind not in _CHILD_BOOK_TYPES[code]:
        questions.append("Вид издания и выбранный код расходятся. Сверьте назначение текста и рисунков по экземпляру и выходным сведениям.")
    elif age is None or not 0 <= age < 18:
        questions.append("Уточните младшую возрастную группу по читательскому адресу издателя. Одна отметка о содержании «0+» или «18+» не определяет назначение издания.")
    else:
        routes = [
            {"document_type": "Декларация о соответствии",
             "condition": "Для новой бумажной книги детской литературы, охваченной ст. 1, применяются схемы 3д, 4д или 6д с участием аккредитованной испытательной лаборатории.",
             "locator": "ТР ТС 007/2011, ст. 12 п. 3, издательская книжная и журнальная продукция",
             "source_url": _CHILD_TR},
            {"document_type": "Сертификат соответствия по выбору заявителя",
             "condition": "Заявитель может заменить декларирование сертификацией. В строке 40 для «из 4901» и «из 4903 00 000 0» предусмотрена альтернатива.",
             "locator": "Перечень № 28, раздел XIV, поз. 40, PDF с. 13. ТР ТС 007/2011, ст. 12 п. 3",
             "source_url": _CHILD_BOOK_LIST},
        ]
        if kind == "child_coloring_book":
            paper = "Сверьте вид и массу бумаги раскраски по ст. 8 п. 4. При использовании предусмотренной этим пунктом бумаги для графитного карандаша рисунок размещают на одной стороне листа."
            if 3 <= age <= 6:
                paper += " Для дошкольной раскраски размер элементов рисунка — от 5 мм."
            questions.append(paper)
        if kind == "child_picture_book":
            questions.append("При печати текста на цветном или сером фоне либо на многокрасочных иллюстрациях проверьте оформление по ст. 8 п. 9 и приложению № 21.")
        if age >= 3:
            appendix = next(number for maximum, number in ((6, 16), (10, 17), (14, 18), (17, 19)) if age <= maximum)
            questions.append(f"Сверено ли шрифтовое оформление с приложением № {appendix} для возраста читателя (ст. 8 п. 7)?")
        medium = "модельной среде (дистиллированной воде)" if age <= 3 else "воздушной среде"
        questions.append(f"Проверьте данные испытаний по ст. 8 п. 12 для указанного возраста в {medium}.")
        questions.append("Сверены ли вид бумаги, оформление, область и срок документа, издатель и идентичность партии или серии?")
    return {
        "family": "EAEU_CHILD_PRINTED_PUBLICATION",
        "status": "NEEDS_CLARIFICATION",
        "questions": questions,
        "source_routes": routes,
        "product_documents": _unverified_submitted_documents(permits),
        "edition": {
            "status": "PARTIALLY_RECONSTRUCTED", "review_date": "2026-11-26",
            "scope": {"locator": "ТР ТС 007/2011, ст. 1, ст. 8, приложение № 1 (издательская продукция)", "source_url": _CHILD_TR},
            "scope_limit": "Для новой продукции на рынке ЕАЭС сверяют книжный формат и читательский адрес издателя. Для 2–3 возрастных групп ст. 8 п. 2 требует учитывать самую младшую. Примечание к перечню № 28 требует сверять название вместе с кодом.",
            "decisions": [
                {"number": 797, "label": "Решение КТС № 797 (начало действия ТР)", "general_effective_date": "2012-07-01", "source_url": _CHILD_TR},
                {"number": 51, "label": "Решение Совета ЕЭК № 51", "general_effective_date": "2018-09-25", "source_url": _CHILD_AMENDMENT},
                {"number": 235, "label": "Решение Коллегии ЕЭК № 235 (изменение перечня)", "general_effective_date": "2020-01-26", "source_url": "https://docs.eaeunion.org/documents/335/4893/"},
                {"number": 147, "label": "Решение Совета ЕЭК № 147", "general_effective_date": "2023-03-26", "source_url": "https://docs.eaeunion.org/documents/401/6944/"},
            ],
            "limit": "Форму и редакцию сверяют на дату выпуска продукции. Для старого документа проверяют срок, запись реестра и применимость переходных условий.",
        },
    }


def archive_normative_block(
    code: str, description: str, *, country: str | None = None, permits: list[dict] | None = None,
    tableware_use: str | None = None, tableware_age: str | None = None,
    publication_kind: str | None = None, reader_age_years: int | None = None,
) -> dict:
    # The catalog prefixes are lookup hints. Only cards present in the pinned
    # registry may be displayed, and none of them establish applicability.
    references = get_tr_ts_requirements(code)
    try:
        acts = lookup_tr_ts_acts_by_codes([row["tr_ts"] for row in references])
    except SQLAlchemyError as error:
        raise HTTPException(503, "Архивные карточки регламентов недоступны.") from error

    result = {"status": "WARNING", "hs_code": code, "description": description}
    block = build_normative_requirements_block(result)
    block.update(
        assessment="INSUFFICIENT_EVIDENCE",
        empty_message="Недостаточно данных для вывода об обязательных документах.",
        notes=["Для проверки нужны характеристики товара, действующая редакция нормы и документ с областью действия на этот товар."],
        archive_acts=[
            {key: act[key] for key in ("act_code", "short_name", "source_revision", "source_url")}
            for act in acts if act["in_registry"]
        ],
    )
    positions = _tableware_candidates(code)
    child_age_given = tableware_age in {"under_3", "exactly_3", "over_3"}
    if code in _CHILD_BOOK_TYPES or publication_kind not in (None, "unknown"):
        block["product_review"] = _child_publication_review(code, publication_kind, reader_age_years, permits)
    elif tableware_use in {"child_food_glass", "child_drinking_cup"} or (code.startswith("7013") and child_age_given):
        block["product_review"] = _child_tableware_review(code, tableware_use, tableware_age, permits)
    elif positions:
        block["product_review"] = _tableware_review(positions, permits)
    elif any(act["act_code"] == "009/2011" for act in block["archive_acts"]):
        block["product_review"] = _cosmetics_review(description, country, permits)
    return {**result, "normative_block": block}
