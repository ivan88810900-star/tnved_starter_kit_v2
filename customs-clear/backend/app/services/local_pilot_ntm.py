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


def archive_normative_block(
    code: str, description: str, *, country: str | None = None, permits: list[dict] | None = None
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
    if any(act["act_code"] == "009/2011" for act in block["archive_acts"]):
        block["product_review"] = _cosmetics_review(description, country, permits)
    return {**result, "normative_block": block}

