"""Read-only evidence available to the local normative-block endpoint."""
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from .normative_requirements_block import build_normative_requirements_block
from .normative_store import lookup_tr_ts_acts_by_codes
from .tr_ts_catalog import get_tr_ts_requirements


def archive_normative_block(code: str, description: str) -> dict:
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
    return {**result, "normative_block": block}
