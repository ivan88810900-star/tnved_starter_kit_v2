from __future__ import annotations

# Классификационные решения ФТС: ORM `ClassificationDecision` в app.models.core;
# upsert/search — функции ниже (данные с tks.ru и др.).

import re
from datetime import date, datetime, timezone
from typing import Any, Literal

from loguru import logger
from sqlalchemy import func, literal, or_

from ..db import SessionLocal, engine
from .hs_matching import get_hs_prefixes, normalize_hs_code, specificity


def normalize_hs_duty_rate_string(value: Any) -> str:
    """
    Ставка пошлины для колонки hs_rates.duty_rate (текст): пусто / беспошлинно → «0»,
    иначе строка без ведущих/хвостовых пробелов (до 2048 символов).
    """
    if value is None:
        return "0"
    if isinstance(value, float):
        try:
            import math

            if math.isnan(value):
                return "0"
        except Exception:
            pass
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        s = str(value).strip()
        if s in ("", "nan", "NaN"):
            return "0"
        if isinstance(value, float) and value == int(value):
            return str(int(value))
        return s
    s = str(value).strip()
    if not s:
        return "0"
    low = s.lower()
    if "беспошлин" in low or "освобожден от пошлины" in low or low == "free":
        return "0"
    return s[:2048]


from ..models import (
    Chapter,
    ClassificationDecision,
    Commodity,
    CountryRisk,
    CountryTariffPreference,
    CustomsCalculationHistory,
    GeoSpecialDuty,
    HsRate,
    IngestedDocument,
    NonTariffRule,
    NormativeNote,
    PreliminaryDecision,
    SourceStatus,
    SyncLog,
    Section,
    TnvedEntry,
    TnvedEntryEmbedding,
    TrTsAct,
)


SEED_RATES: list[dict[str, Any]] = [
    {
        "hs_prefix": "8509",
        "duty_rate": "8",
        "vat_import_rate": 22.0,
        "vat_rule": "none",
        "vat_rule_basis": "НК РФ ст. 164 п. 3 (общая ставка 22%)",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": False,
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "8516",
        "duty_rate": "8",
        "vat_import_rate": 22.0,
        "vat_rule": "none",
        "vat_rule_basis": "НК РФ ст. 164 п. 3 (общая ставка 22%)",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": False,
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "8517",
        "duty_rate": "0",
        "vat_import_rate": 22.0,
        "vat_rule": "none",
        "vat_rule_basis": "НК РФ ст. 164 п. 3 (общая ставка 22%)",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": False,
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "8471",
        "duty_rate": "0",
        "vat_import_rate": 22.0,
        "vat_rule": "none",
        "vat_rule_basis": "НК РФ ст. 164 п. 3 (общая ставка 22%)",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": False,
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "2203",  # пиво — акциз
        "duty_rate": "5",
        "vat_import_rate": 22.0,
        "vat_rule": "none",
        "vat_rule_basis": "НК РФ ст. 164 п. 3 (общая ставка 22%)",
        "excise_type": "percent",
        "excise_value": 5.0,
        "excise_basis": "НК РФ ст. 193: пиво — ставка акциза по объёму или проценту от стоимости (упрощённый пример)",
        "has_antidumping": False,
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "2208",  # крепкий алкоголь — акциз фиксированный
        "duty_rate": "15",
        "vat_import_rate": 22.0,
        "vat_rule": "none",
        "vat_rule_basis": "НК РФ ст. 164 п. 3 (общая ставка 22%)",
        "excise_type": "fixed",
        "excise_value": 613.0,
        "excise_basis": "НК РФ ст. 193: алкогольная продукция с долей спирта свыше 9% — 613 руб/л (2024)",
        "has_antidumping": False,
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "0201",  # говядина свежая — НДС 10%
        "duty_rate": "15",
        "vat_import_rate": 10.0,
        "vat_rule": "reduced10",
        "vat_rule_basis": "НК РФ ст. 164 п. 2 пп. 1: продовольственные товары (мясо крупного рогатого скота) — ставка 10%",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": False,
        "source_url": "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-21/statia-164/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "0401",  # молоко — НДС 10%
        "duty_rate": "5",
        "vat_import_rate": 10.0,
        "vat_rule": "reduced10",
        "vat_rule_basis": "НК РФ ст. 164 п. 2 пп. 1: продовольственные товары (молоко) — ставка 10%",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": False,
        "source_url": "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-21/statia-164/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "1001",  # пшеница — НДС 10%
        "duty_rate": "5",
        "vat_import_rate": 10.0,
        "vat_rule": "reduced10",
        "vat_rule_basis": "НК РФ ст. 164 п. 2 пп. 1: продовольственные товары (зерно) — ставка 10%",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": False,
        "source_url": "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-21/statia-164/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "3004",  # лекарства — НДС 10%
        "duty_rate": "0",
        "vat_import_rate": 10.0,
        "vat_rule": "reduced10",
        "vat_rule_basis": "НК РФ ст. 164 п. 2 пп. 4: лекарственные средства — ставка 10%",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": False,
        "source_url": "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-21/statia-164/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "9503",  # детские игрушки — НДС 10%
        "duty_rate": "5",
        "vat_import_rate": 10.0,
        "vat_rule": "reduced10",
        "vat_rule_basis": "НК РФ ст. 164 п. 2 пп. 2: товары для детей (игрушки) — ставка 10%",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": False,
        "source_url": "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-21/statia-164/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "7214",  # арматура — антидемпинг (Украина/Китай)
        "duty_rate": "10",
        "vat_import_rate": 22.0,
        "vat_rule": "none",
        "vat_rule_basis": "НК РФ ст. 164 п. 3 (общая ставка 22%)",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": True,
        "antidumping_type": "percent",
        "antidumping_value": 18.0,
        "antidumping_condition": "Решение Коллегии ЕЭК № 186 от 07.11.2017. Применяется к прутку из нелегированной стали.",
        "antidumping_countries": "CN,UA",
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
        "valid_from": "2018-01-01",
        "valid_to": "2028-01-01",
    },
    {
        "hs_prefix": "6302",  # постельное бельё
        "duty_rate": "12",
        "vat_import_rate": 22.0,
        "vat_rule": "none",
        "vat_rule_basis": "НК РФ ст. 164 п. 3 (общая ставка 22%)",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": False,
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
    {
        "hs_prefix": "6109",  # футболки
        "duty_rate": "12",
        "vat_import_rate": 22.0,
        "vat_rule": "none",
        "vat_rule_basis": "НК РФ ст. 164 п. 3 (общая ставка 22%)",
        "excise_type": "none",
        "excise_value": 0.0,
        "has_antidumping": False,
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
        "valid_from": "2024-01-01",
    },
]

# Нетарифные правила для инициализации БД
SEED_NON_TARIFF_RULES: list[dict[str, Any]] = [
    {
        "name": "Бытовая электроника",
        "hs_prefix": "8509",
        "tr_ts": "004/2011,020/2011,037/2016",
        "required_permits": "СС,ДС",
        "tr_ts_edition": "Уточняйте действующую редакцию ТР ТС на портале ЕЭК / в консультант-плюс.",
        "exception_note": "Исключения по субпозициям и комплектующим — отдельная классификация; пример для демонстрации полей БД.",
        "priority": 5,
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Бытовая электроника (нагрев)",
        "hs_prefix": "8516",
        "tr_ts": "004/2011,020/2011",
        "required_permits": "СС,ДС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Телефоны и связное оборудование",
        "hs_prefix": "8517",
        "tr_ts": "004/2011,020/2011,037/2016",
        "required_permits": "СС,ДС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Компьютеры и оргтехника",
        "hs_prefix": "8471",
        "tr_ts": "004/2011,020/2011",
        "required_permits": "ДС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Косметика и парфюмерия (уход за кожей)",
        "hs_prefix": "3304",
        "tr_ts": "009/2011,021/2011",
        "required_permits": "СГР,ДС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Средства по уходу за волосами",
        "hs_prefix": "3305",
        "tr_ts": "009/2011,021/2011",
        "required_permits": "СГР,ДС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Дезодоранты и средства гигиены",
        "hs_prefix": "3307",
        "tr_ts": "009/2011,021/2011",
        "required_permits": "СГР,ДС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Одежда 1-й слой (трикотаж женский)",
        "hs_prefix": "6109",
        "tr_ts": "017/2011",
        "required_permits": "СС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Одежда 2–3 слой (пальто женское)",
        "hs_prefix": "6202",
        "tr_ts": "017/2011",
        "required_permits": "ДС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Одежда 2–3 слой (пальто мужское)",
        "hs_prefix": "6201",
        "tr_ts": "017/2011",
        "required_permits": "ДС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Детские товары (игрушки)",
        "hs_prefix": "9503",
        "tr_ts": "007/2011,008/2011",
        "required_permits": "СС,СГР",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Детская одежда",
        "hs_prefix": "6209",
        "tr_ts": "007/2011,017/2011",
        "required_permits": "СС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Посуда керамическая (столовая)",
        "hs_prefix": "6911",
        "tr_ts": "021/2011",
        "required_permits": "ДС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Посуда керамическая (кухонная)",
        "hs_prefix": "6912",
        "tr_ts": "021/2011",
        "required_permits": "ДС",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
    {
        "name": "Лекарственные средства",
        "hs_prefix": "3004",
        "tr_ts": "061/2012",
        "required_permits": "РУ",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
    },
]

# Карточки техрегламентов ТР ТС (код NNNN/YYYY → справочная информация; не заменяет официальный текст)
SEED_TR_TS_ACTS: list[dict[str, Any]] = [
    {
        "act_code": "004/2011",
        "short_name": "ТР ТС 004/2011",
        "full_title": "О безопасности низковольтного оборудования",
        "edition_note": "Проверяйте действующую редакцию и переходные положения на портале ЕЭК / в консультант-плюс.",
        "source_url": "https://eec.eaeunion.org/",
        "source_revision": "seed-2026-03",
    },
    {
        "act_code": "020/2011",
        "short_name": "ТР ТС 020/2011",
        "full_title": "Электромагнитная совместимость технических средств",
        "edition_note": "",
        "source_url": "https://eec.eaeunion.org/",
        "source_revision": "seed-2026-03",
    },
    {
        "act_code": "037/2016",
        "short_name": "ТР ЕАЭС 037/2016",
        "full_title": "О безопасности продукции, связанной с радиоизлучением",
        "edition_note": "",
        "source_url": "https://eec.eaeunion.org/",
        "source_revision": "seed-2026-03",
    },
    {
        "act_code": "009/2011",
        "short_name": "ТР ТС 009/2011",
        "full_title": "О безопасности парфюмерно-косметической продукции",
        "edition_note": "",
        "source_url": "https://eec.eaeunion.org/",
        "source_revision": "seed-2026-03",
    },
    {
        "act_code": "021/2011",
        "short_name": "ТР ТС 021/2011",
        "full_title": "О безопасности пищевой продукции (в т.ч. посуда при контакте с пищей — уточняйте применимость)",
        "edition_note": "Границы применения к конкретной номенклатуре уточняйте по официальному тексту и классификации.",
        "source_url": "https://eec.eaeunion.org/",
        "source_revision": "seed-2026-03",
    },
    {
        "act_code": "017/2011",
        "short_name": "ТР ТС 017/2011",
        "full_title": "О безопасности продукции лёгкой промышленности",
        "edition_note": "",
        "source_url": "https://eec.eaeunion.org/",
        "source_revision": "seed-2026-03",
    },
    {
        "act_code": "007/2011",
        "short_name": "ТР ТС 007/2011",
        "full_title": "О безопасности продукции, предназначенной для детей и подростков",
        "edition_note": "",
        "source_url": "https://eec.eaeunion.org/",
        "source_revision": "seed-2026-03",
    },
    {
        "act_code": "008/2011",
        "short_name": "ТР ТС 008/2011",
        "full_title": "О безопасности игрушек",
        "edition_note": "",
        "source_url": "https://eec.eaeunion.org/",
        "source_revision": "seed-2026-03",
    },
    {
        "act_code": "061/2012",
        "short_name": "ТР ЕАЭС 061/2012",
        "full_title": "О безопасности лекарственных средств (обобщённо; детали — официальный текст)",
        "edition_note": "",
        "source_url": "https://eec.eaeunion.org/",
        "source_revision": "seed-2026-03",
    },
]

TR_TS_ACT_CODE_RE = re.compile(r"\b(\d{3}/\d{4})\b")


def extract_tr_ts_act_codes(labels: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    """Извлекает коды вида 004/2011 из произвольных подписей ТР ТС."""
    seen: set[str] = set()
    out: list[str] = []
    for lab in labels:
        for m in TR_TS_ACT_CODE_RE.findall(str(lab)):
            if m not in seen:
                seen.add(m)
                out.append(m)
    return out


# Демонстрационные записи справочника ТН ВЭД (полный перечень — через импорт пакета / Excel+бандл)
SEED_TNVED: list[dict[str, Any]] = [
    {
        "hs_code": "8509400000",
        "parent_hs": "850940",
        "level": 10,
        "title": "Электрические чайники и прочие электроприборы для кипячения воды",
        "description": "Включает бытовые электрочайники. Уточняйте субпозицию по конструкции и мощности по действующей редакции ТН ВЭД ЕАЭС.",
        "chapter": "85",
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
    },
    {
        "hs_code": "850940",
        "parent_hs": "8509",
        "level": 6,
        "title": "Электромеханические бытовые приборы с встроенным электродвигателем",
        "description": "",
        "chapter": "85",
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
    },
]

SEED_NORMATIVE_NOTES: list[dict[str, Any]] = [
    {
        "scope_type": "prefix",
        "scope_value": "8509",
        "category": "ett",
        "title": "Ввозная пошлина",
        "body": "Ставки ЕТТ ЕАЭС по кодам группы 85 см. действующую редакцию Единого таможенного тарифа на портале ЕЭК.",
        "source_url": "https://eec.eaeunion.org/comission/department/catr/ett/",
        "source_revision": "seed-2026-03",
        "sort_order": 10,
    },
    {
        "scope_type": "prefix",
        "scope_value": "8509",
        "category": "non_tariff",
        "title": "Техническое регулирование",
        "body": "Бытовые электроприборы: ТР ТС 004/2011 (безопасность низковольтного оборудования), 020/2011 (ЭМС), при необходимости 037/2016 (радио).",
        "source_url": "https://eec.eaeunion.org/comission/department/nts/",
        "source_revision": "seed-2026-03",
        "sort_order": 20,
    },
]


def _sqlite_patch_non_tariff_columns() -> None:
    """Добавить колонки в non_tariff_rules на старых SQLite-файлах (без полного alembic)."""
    from sqlalchemy import inspect, text

    if not str(engine.url).startswith("sqlite"):
        return
    insp = inspect(engine)
    if not insp.has_table("non_tariff_rules"):
        return
    cols = {c["name"] for c in insp.get_columns("non_tariff_rules")}
    patches = [
        ("tr_ts_edition", "VARCHAR(512) NOT NULL DEFAULT ''"),
        ("exception_note", "TEXT NOT NULL DEFAULT ''"),
        ("priority", "INTEGER NOT NULL DEFAULT 0"),
    ]
    with engine.begin() as conn:
        for col_name, decl in patches:
            if col_name not in cols:
                conn.execute(text(f"ALTER TABLE non_tariff_rules ADD COLUMN {col_name} {decl}"))


def _run_alembic_upgrade_to_head() -> None:
    """Схема БД только через Alembic (единый источник правды; готово к PostgreSQL)."""
    import os
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parent.parent.parent
    ini_path = backend_root / "alembic.ini"
    if not ini_path.is_file():
        raise FileNotFoundError(
            f"Не найден {ini_path}. Установите backend и запускайте API из каталога backend "
            "или задайте корректный путь к alembic.ini."
        )
    cfg = Config(str(ini_path))
    # env.py: os.getenv("DATABASE_URL") or get_main_option — выравниваем с тем же URL, что у engine
    db_url = os.getenv("DATABASE_URL") or str(engine.url)
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")


def init_db() -> None:
    _run_alembic_upgrade_to_head()
    _sqlite_patch_non_tariff_columns()
    seed_data()
    try:
        from .tnved_fts import ensure_fts_index

        ensure_fts_index()
    except Exception as exc:  # поисковый индекс не критичен для старта
        logger.warning("init_db: не удалось построить FTS-индекс ТН ВЭД: %s", exc)


def seed_data() -> None:
    with SessionLocal() as db:
        for row in SEED_RATES:
            hs_prefix = row["hs_prefix"]
            obj = db.query(HsRate).filter(HsRate.hs_prefix == hs_prefix).first()
            if not obj:
                db.add(HsRate(hs_code=hs_prefix, **row))
            else:
                # Always update fields that may be empty from a previous (pre-migration) seed
                for field in ("vat_rule", "vat_rule_basis", "excise_type", "excise_value",
                              "excise_basis", "antidumping_countries", "source_revision", "valid_from"):
                    if field in row:
                        setattr(obj, field, row[field])
                # Also refresh antidumping fields from seed
                for field in ("has_antidumping", "antidumping_type", "antidumping_value",
                              "antidumping_condition", "duty_rate", "vat_import_rate"):
                    if field in row:
                        setattr(obj, field, row[field])

        for row in SEED_NON_TARIFF_RULES:
            obj = (
                db.query(NonTariffRule)
                .filter(
                    NonTariffRule.hs_prefix == row["hs_prefix"],
                    NonTariffRule.name == row["name"],
                )
                .first()
            )
            if not obj:
                db.add(NonTariffRule(**row))
            else:
                for k, v in row.items():
                    if hasattr(obj, k) and k not in ("id",):
                        setattr(obj, k, v)

        for row in SEED_TNVED:
            exists = db.query(TnvedEntry).filter(TnvedEntry.hs_code == row["hs_code"]).first()
            if not exists:
                db.add(TnvedEntry(**row))

        for row in SEED_NORMATIVE_NOTES:
            exists = (
                db.query(NormativeNote)
                .filter(
                    NormativeNote.scope_type == row["scope_type"],
                    NormativeNote.scope_value == row["scope_value"],
                    NormativeNote.category == row["category"],
                    NormativeNote.title == row["title"],
                )
                .first()
            )
            if not exists:
                db.add(NormativeNote(**row))

        for row in SEED_TR_TS_ACTS:
            exists = db.query(TrTsAct).filter(TrTsAct.act_code == row["act_code"]).first()
            if not exists:
                db.add(TrTsAct(**row))
            else:
                for k, v in row.items():
                    if hasattr(exists, k) and k != "id":
                        setattr(exists, k, v)

        source_defaults = [
            (
                "EEC_ETT",
                "ТН ВЭД и ЕТТ ЕАЭС",
                "https://eec.eaeunion.org/comission/department/catr/ett/",
                "seed-2026-03",
                False,
                "Начальная инициализация локального набора ставок.",
            ),
            (
                "NDS_NK164",
                "НДС при ввозе (НК РФ ст. 164)",
                "http://sudact.ru/law/nk-rf-chast2/razdel-viii/glava-21/statia-164/",
                "seed-2026-03",
                False,
                "Используется как нормативная ссылка для ставки НДС при ввозе.",
            ),
            (
                "TRADE_DEFENSE",
                "Меры торговой защиты ЕАЭС",
                "https://eec.eaeunion.org/comission/department/catr/trade-protect/",
                "seed-2026-03",
                False,
                "Антидемпинговые, компенсационные и защитные меры.",
            ),
        ]
        for code, name, url, rev, stale, note in source_defaults:
            exists = db.query(SourceStatus).filter(SourceStatus.source_code == code).first()
            if exists:
                continue
            db.add(
                SourceStatus(
                    source_code=code,
                    source_name=name,
                    source_url=url,
                    revision=rev,
                    synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    is_stale=stale,
                    note=note,
                )
            )
        db.commit()


def upsert_source_status(
    source_code: str,
    source_name: str,
    source_url: str,
    revision: str,
    is_stale: bool,
    note: str,
) -> None:
    with SessionLocal() as db:
        obj = db.query(SourceStatus).filter(SourceStatus.source_code == source_code).first()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if not obj:
            db.add(
                SourceStatus(
                    source_code=source_code,
                    source_name=source_name,
                    source_url=source_url,
                    revision=revision,
                    synced_at=now,
                    is_stale=is_stale,
                    note=note,
                )
            )
        else:
            obj.source_name = source_name
            obj.source_url = source_url
            obj.revision = revision
            obj.synced_at = now
            obj.is_stale = is_stale
            obj.note = note
        db.commit()


def append_sync_log(
    source_code: str,
    status: str,
    revision: str,
    rows_affected: int,
    note: str,
) -> None:
    with SessionLocal() as db:
        db.add(
            SyncLog(
                source_code=source_code,
                synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                status=status,
                revision=revision,
                rows_affected=rows_affected,
                note=note,
            )
        )
        db.commit()


def upsert_hs_rate(row: dict[str, Any]) -> None:
    with SessionLocal() as db:
        hs_code = str(row.get("hs_code") or "").strip().replace(" ", "")
        hs_prefix = str(row.get("hs_prefix") or (hs_code[:4] if hs_code else "")).strip()
        if not hs_prefix:
            return
        row = dict(row)
        if "duty_rate" in row:
            row["duty_rate"] = normalize_hs_duty_rate_string(row.get("duty_rate"))
        # Уникальность по hs_code — каждая позиция ТН ВЭД отдельно (не перезаписывать по hs_prefix)
        lookup = hs_code if len(hs_code) >= 4 else hs_prefix
        obj = db.query(HsRate).filter(HsRate.hs_code == lookup).first()
        if not obj:
            allowed = {"duty_rate", "vat_import_rate", "vat_rule", "vat_rule_basis", "excise_type", "excise_value", "excise_basis", "has_antidumping", "antidumping_type", "antidumping_value", "antidumping_condition", "antidumping_countries", "source_url", "source_revision"}
            create_kwargs = {k: v for k, v in row.items() if k in allowed}
            db.add(HsRate(hs_code=lookup or hs_prefix, hs_prefix=hs_prefix, **create_kwargs))
        else:
            for k, v in row.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
            obj.hs_code = lookup or obj.hs_code
            obj.hs_prefix = hs_prefix
        db.commit()


def upsert_classification_decision(row: dict[str, Any]) -> None:
    """UPSERT по уникальному decision_number (источник TKS и др.)."""
    dn = str(row.get("decision_number") or "").strip()
    if not dn:
        return
    hs = re.sub(r"\D", "", str(row.get("hs_code") or ""))[:10]
    pname = str(row.get("product_name") or "")
    desc = str(row.get("description") or "")
    tent = str(row.get("target_entity") or "")[:512]
    idate = str(row.get("issue_date") or "")[:32]
    with SessionLocal() as db:
        obj = db.query(ClassificationDecision).filter(ClassificationDecision.decision_number == dn).first()
        if obj is None:
            db.add(
                ClassificationDecision(
                    hs_code=hs,
                    product_name=pname,
                    description=desc,
                    target_entity=tent,
                    decision_number=dn,
                    issue_date=idate,
                )
            )
        else:
            obj.hs_code = hs or obj.hs_code
            obj.product_name = pname or obj.product_name
            obj.description = desc or obj.description
            obj.target_entity = tent
            obj.issue_date = idate or obj.issue_date
        db.commit()


def upsert_preliminary_decision(row: dict[str, Any], *, source: str = "fts_alta") -> None:
    """
    UPSERT в ``preliminary_decisions`` по паре (hs_code, description, source).
    Используется для наполнения практикой из публичных реестров ПКР/предварительных решений.
    """
    hs = re.sub(r"\D", "", str(row.get("hs_code") or ""))[:10]
    desc = str(row.get("description") or "").strip()
    if not hs or not desc:
        return
    src = str(source or "fts_alta").strip()[:32]
    with SessionLocal() as db:
        exists = (
            db.query(PreliminaryDecision.id)
            .filter(
                PreliminaryDecision.hs_code == hs,
                PreliminaryDecision.description == desc,
                PreliminaryDecision.source == src,
            )
            .first()
        )
        if not exists:
            db.add(PreliminaryDecision(hs_code=hs, description=desc, source=src))
            db.commit()


def find_classification_precedents_for_invoice_item(
    item_data: dict[str, Any],
    *,
    limit: int = 8,
) -> tuple[str, str]:
    """
    Ищет записи classification_decisions по цифровым префиксам (4–10 знаков) в тексте строки
    и по ключевым словам (>=4 символов) только в target_entity и product_name (не по длинному description).

    Возвращает (блок_для_промпта, номера_решений_через_запятую).
    """
    parts = [
        (item_data.get("name_ru") or ""),
        (item_data.get("name_cn") or ""),
        (item_data.get("material") or ""),
        (item_data.get("usage") or ""),
        (item_data.get("brand") or ""),
    ]
    blob = " ".join(str(p) for p in parts if p).strip()
    if not blob:
        return "", ""

    digit_runs = re.findall(r"\d{4,10}", re.sub(r"[^\d]+", " ", blob))
    prefixes: list[str] = []
    seen_pref: set[str] = set()
    for run in digit_runs:
        d = re.sub(r"\D", "", run)
        if len(d) < 4:
            continue
        for L in (6, 5, 4):
            if len(d) >= L:
                p = d[:L]
                if p not in seen_pref:
                    seen_pref.add(p)
                    prefixes.append(p)

    low = blob.lower()
    raw_tokens = re.split(r"[^\w\u0400-\u04ff]+", low, flags=re.UNICODE)
    keywords = [t for t in raw_tokens if len(t) >= 4][:10]

    collected: list[ClassificationDecision] = []
    seen_id: set[int] = set()

    def _add_rows(q) -> None:
        nonlocal collected
        for r in q:
            if r.id in seen_id or len(collected) >= limit:
                break
            seen_id.add(r.id)
            collected.append(r)

    with SessionLocal() as db:
        for pr in prefixes[:20]:
            if len(collected) >= limit:
                break
            _add_rows(
                db.query(ClassificationDecision)
                .filter(ClassificationDecision.hs_code.startswith(pr))
                .order_by(ClassificationDecision.issue_date.desc())
                .limit(5)
            )

        for tok in keywords:
            if len(collected) >= limit:
                break
            pat = f"%{tok}%"
            _add_rows(
                db.query(ClassificationDecision)
                .filter(
                    or_(
                        ClassificationDecision.target_entity.ilike(pat),
                        ClassificationDecision.product_name.ilike(pat),
                    )
                )
                .order_by(ClassificationDecision.issue_date.desc())
                .limit(5)
            )

    if not collected:
        return "", ""

    lines: list[str] = []
    nums: list[str] = []
    for r in collected[:limit]:
        nums.append(r.decision_number)
        pn = (r.product_name or "").replace("\n", " ").strip()[:400]
        te = (getattr(r, "target_entity", None) or "").replace("\n", " ").strip()[:200]
        ds = (r.description or "").replace("\n", " ").strip()[:300]
        lines.append(
            f"- Решение №{r.decision_number} от {r.issue_date or '—'}: код ТН ВЭД {r.hs_code or '—'}; "
            f"главный объект: {te or '—'}; наименование: {pn or '—'}; фрагмент описания: {ds or '—'}"
        )
    block = (
        "=== ПРЕЦЕДЕНТЫ ФТС ===\n"
        + "\n".join(lines)
        + "\nОбязательно учитывай эту практику при выборе кода и ссылайся на номер решения в обосновании.\n\n"
    )
    return block, ",".join(dict.fromkeys(nums))


def is_leaf_hs_code(hs_code: str) -> bool:
    """
    True если код — реальный лист ЕТТ (есть прямая ставка в hs_rates или не групповой заголовок).

    Групповые заголовки часто оканчиваются на ``0000`` / ``000000`` без строки в hs_rates
    (например ``8703230000``). Исключения вроде ``8471300000`` имеют прямую запись в hs_rates.
    """
    code = normalize_hs_code(hs_code)
    if len(code) != 10:
        return False
    if code.endswith("000000") or code.endswith("0000"):
        with SessionLocal() as db:
            exists = db.query(HsRate.id).filter(HsRate.hs_code == code).first()
        return exists is not None
    return True


def find_suggested_leaf_codes(hs_code: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Дочерние коды-листья из hs_rates для группового заголовка."""
    code = normalize_hs_code(hs_code)
    if len(code) != 10:
        return []
    prefix = code.rstrip("0")
    if len(prefix) < 4:
        prefix = code[:4]
    with SessionLocal() as db:
        rate_rows = (
            db.query(HsRate.hs_code, HsRate.duty_rate)
            .filter(HsRate.hs_code.like(f"{prefix}%"), HsRate.hs_code != code)
            .order_by(HsRate.hs_code)
            .limit(limit)
            .all()
        )
        if not rate_rows:
            return []
        codes = [r[0] for r in rate_rows]
        commodities = (
            db.query(Commodity.code, Commodity.description)
            .filter(Commodity.code.in_(codes))
            .all()
        )
        desc_by_code = {c.code: (c.description or "").strip() for c in commodities}
    return [
        {
            "code": hc,
            "duty_rate": str(dr or "0"),
            "description": desc_by_code.get(hc, ""),
        }
        for hc, dr in rate_rows
    ]


def find_rate_for_hs(hs_code: str) -> tuple[HsRate | None, int]:
    """Returns (rate, matched_prefix_length). Length 0 means no match."""
    code = (hs_code or "").strip().replace(" ", "")
    if not code:
        return None, 0
    prefixes: list[tuple[str, int]] = []
    for length in (10, 8, 6, 4, 2):
        if len(code) >= length:
            prefixes.append((code[:length], length))
    if not prefixes:
        return None, 0
    by_pref = {pref: mlen for pref, mlen in prefixes}
    with SessionLocal() as db:
        rows = (
            db.query(HsRate)
            .filter(or_(HsRate.hs_code.in_(list(by_pref.keys())), HsRate.hs_prefix.in_(list(by_pref.keys()))))
            .all()
        )
    if not rows:
        return None, 0
    best = max(rows, key=lambda r: max(by_pref.get(r.hs_code or "", 0), by_pref.get(r.hs_prefix or "", 0)))
    return best, max(by_pref.get(best.hs_code or "", 0), by_pref.get(best.hs_prefix or "", 0))


_NtDateParse = Literal["open", "ok", "invalid"]


def _parse_non_tariff_rule_date(raw: str | None) -> tuple[_NtDateParse, date | None]:
    """
    Разбор даты в non_tariff_rules (строка до 20 символов, в сидах — ISO YYYY-MM-DD).

    Пустая строка → граница не задана (``open``, ``None``).
    Непустая, но не ISO-дата в первых 10 символах → ``invalid``.
    """
    s = (raw or "").strip()
    if not s:
        return "open", None
    fragment = s[:10]
    try:
        return "ok", date.fromisoformat(fragment)
    except ValueError:
        return "invalid", None


def _non_tariff_rule_active_on(
    valid_from: str | None,
    valid_to: str | None,
    as_of: date,
    *,
    rule_id: int | None = None,
    rule_name: str = "",
    hs_prefix: str = "",
) -> bool:
    """
    Правило активно на дату as_of, если:
    (valid_from пусто или дата <= as_of) и (valid_to пусто или as_of <= valid_to).

    Некорректная непустая дата → правило не применяется, в лог — warning.
    """
    ctx = f"rule_id={rule_id} name={rule_name!r} hs_prefix={hs_prefix!r}"
    lo_kind, lo = _parse_non_tariff_rule_date(valid_from)
    hi_kind, hi = _parse_non_tariff_rule_date(valid_to)
    if lo_kind == "invalid":
        logger.warning(
            "non_tariff_rules: invalid valid_from={!r}; rule excluded ({})",
            (valid_from or "").strip(),
            ctx,
        )
        return False
    if hi_kind == "invalid":
        logger.warning(
            "non_tariff_rules: invalid valid_to={!r}; rule excluded ({})",
            (valid_to or "").strip(),
            ctx,
        )
        return False
    if lo is not None and as_of < lo:
        return False
    if hi is not None and as_of > hi:
        return False
    return True


def find_non_tariff_rules_for_hs(hs_code: str, *, as_of: date | None = None) -> list[dict[str, Any]]:
    """Find non-tariff rules from DB, matching by hs_prefix of any length (4–10 chars).

    Учитываются ``valid_from`` / ``valid_to`` (строки ISO YYYY-MM-DD или пусто = без границы).
    Дата проверки по умолчанию — сегодня (локальный календарь); для тестов — ``as_of=``.
    """
    code = normalize_hs_code(hs_code)
    if not code:
        return []
    check_date = as_of if as_of is not None else date.today()
    with SessionLocal() as db:
        results = []
        seen_ids: set[int] = set()
        # Как раньше: только уровни 10/8/6/4 (без 2-значной главы).
        for pref in get_hs_prefixes(code, levels=(10, 8, 6, 4)):
            rows = db.query(NonTariffRule).filter(NonTariffRule.hs_prefix == pref).all()
            for r in rows:
                if r.id not in seen_ids:
                    vf = getattr(r, "valid_from", None) or ""
                    vt = getattr(r, "valid_to", None) or ""
                    if not _non_tariff_rule_active_on(
                        vf,
                        vt,
                        check_date,
                        rule_id=r.id,
                        rule_name=r.name or "",
                        hs_prefix=r.hs_prefix or "",
                    ):
                        continue
                    seen_ids.add(r.id)
                    results.append({
                        "name": r.name,
                        "hs_prefix": r.hs_prefix,
                        "tr_ts": [x.strip() for x in r.tr_ts.split(",") if x.strip()],
                        "required_permits": [x.strip() for x in r.required_permits.split(",") if x.strip()],
                        "tr_ts_edition": getattr(r, "tr_ts_edition", None) or "",
                        "exception_note": getattr(r, "exception_note", None) or "",
                        "priority": int(getattr(r, "priority", 0) or 0),
                        "source_url": r.source_url,
                        "source_revision": r.source_revision,
                    })
        results.sort(
            key=lambda x: (
                -specificity(str(x.get("hs_prefix") or "")),
                -int(x.get("priority") or 0),
                str(x.get("hs_prefix") or ""),
                str(x.get("name") or ""),
            ),
        )
        return results


def search_hs_rates(query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Поиск товаров по коду ТН ВЭД (префикс)."""
    q = (query or "").strip().replace(" ", "")
    if not q or len(q) < 2:
        return []
    with SessionLocal() as db:
        from ..models import HsRate
        rows = (
            db.query(HsRate)
            .filter(
                (HsRate.hs_code.like(f"{q}%")) | (HsRate.hs_prefix.like(f"{q}%"))
            )
            .order_by(HsRate.hs_code)
            .limit(limit)
            .all()
        )
        return [
            {
                "hs_code": r.hs_code,
                "hs_prefix": r.hs_prefix,
                "duty_rate": str(r.duty_rate or "0"),
                "vat_rate": float(r.vat_import_rate),
                "vat_rule": r.vat_rule or "none",
            }
            for r in rows
        ]


def search_hs_rates_enriched(query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Поиск по ставкам + наименование из tnved_entries (если есть)."""
    base = search_hs_rates(query, limit=limit)
    if not base:
        terms = _expand_query_terms(query)
        if not terms:
            return []
        with SessionLocal() as db:
            filters = [func.lower(Commodity.description).like(f"%{t}%") for t in terms]
            commodities = (
                db.query(Commodity)
                .filter(or_(*filters))
                .order_by(Commodity.code.asc())
                .limit(limit)
                .all()
            )
            if not commodities:
                return []
            out: list[dict[str, Any]] = []
            for c in commodities:
                hs = (
                    db.query(HsRate)
                    .filter(or_(HsRate.hs_code == c.code, HsRate.hs_prefix == c.code[:4]))
                    .order_by(HsRate.hs_code.desc())
                    .first()
                )
                out.append(
                    {
                        "hs_code": c.code,
                        "hs_prefix": (hs.hs_prefix if hs else c.code[:4]),
                        "duty_rate": str(hs.duty_rate or "0") if hs else "",
                        "vat_rate": float(hs.vat_import_rate) if hs else 0.0,
                        "vat_rule": (hs.vat_rule or "none") if hs else "none",
                        "title": (c.description or "").strip(),
                        "tnved_in_db": True,
                    }
                )
            return out
    codes = [r["hs_code"] for r in base if r.get("hs_code")]
    with SessionLocal() as db:
        entries = (
            db.query(TnvedEntry)
            .filter(TnvedEntry.hs_code.in_(codes))
            .all()
            if codes
            else []
        )
        by_code = {e.hs_code: e for e in entries}
    out: list[dict[str, Any]] = []
    for r in base:
        item = dict(r)
        ent = by_code.get(r["hs_code"])
        item["title"] = (ent.title if ent else "") or ""
        item["tnved_in_db"] = bool(ent and (ent.title or ent.description))
        out.append(item)
    return out


def get_integrated_data_stats() -> dict[str, Any]:
    """Количество позиций в приложении (интегрированные данные)."""
    with SessionLocal() as db:
        hs_count = db.query(HsRate).count()
        nt_count = db.query(NonTariffRule).count()
        tnved_count = db.query(TnvedEntry).count()
        notes_count = db.query(NormativeNote).count()
        tr_ts_count = db.query(TrTsAct).count()
        ingested_count = db.query(IngestedDocument).count()
        emb_count = db.query(TnvedEntryEmbedding).filter(TnvedEntryEmbedding.embedding.isnot(None)).count()
        calc_hist_count = db.query(CustomsCalculationHistory).count()
        return {
            "hs_rates_count": hs_count,
            "non_tariff_rules_count": nt_count,
            "tnved_entries_count": tnved_count,
            "normative_notes_count": notes_count,
            "tr_ts_acts_count": tr_ts_count,
            "ingested_documents_count": ingested_count,
            "tnved_embeddings_count": emb_count,
            "customs_calculation_history_count": calc_hist_count,
        }


def get_normative_data_hints() -> list[dict[str, Any]]:
    """Короткие подсказки по заполненности и свежести данных (для UI / мониторинга)."""
    hints: list[dict[str, Any]] = []
    stats = get_integrated_data_stats()
    if stats.get("tnved_entries_count", 0) == 0:
        hints.append(
            {
                "level": "info",
                "code": "TNVED_EMPTY",
                "text": "Справочник наименований ТН ВЭД пуст — загрузите JSON-пакет или импорт с секцией tnved (см. docs/integration/NORMATIVE_PIPELINE.md).",
            }
        )
    if stats.get("normative_notes_count", 0) == 0:
        hints.append(
            {
                "level": "info",
                "code": "NOTES_EMPTY",
                "text": "Нет нормативных примечаний в БД — при необходимости добавьте секцию notes в пакете.",
            }
        )
    if stats.get("hs_rates_count", 0) < 5:
        hints.append(
            {
                "level": "warning",
                "code": "RATES_SPARSE",
                "text": "В базе мало ставок (hs_rates) — импортируйте Excel TWS.BY или расширьте пакет/фиды.",
            }
        )
    if stats.get("tr_ts_acts_count", 0) == 0:
        hints.append(
            {
                "level": "info",
                "code": "TR_TS_REGISTRY_EMPTY",
                "text": "Справочник карточек ТР ТС пуст — после миграции выполните перезапуск (init_db/seed) или импорт пакета.",
            }
        )
    with SessionLocal() as db:
        eec = db.query(SourceStatus).filter(SourceStatus.source_code == "EEC_ETT").first()
        if eec and (eec.is_stale or (eec.revision or "") == "unavailable"):
            hints.append(
                {
                    "level": "warning",
                    "code": "EEC_STALE_OR_UNAVAILABLE",
                    "text": "Источник EEC_ETT недоступен или устарел — выполните POST /api/sources/sync при доступе в интернет.",
                }
            )
    return hints


def _digits_hs(code: str) -> str:
    return re.sub(r"\D", "", (code or ""))[:10]


def _hs_lookup_variants(code: str) -> list[str]:
    d = _digits_hs(code)
    if not d:
        return []
    out = [d]
    if len(d) < 10:
        out.append(d.ljust(10, "0"))
    # уникальные, порядок сохранён
    seen: set[str] = set()
    return [x for x in out if not (x in seen or seen.add(x))]


_SYNONYM_MAP: dict[str, list[str]] = {
    "планшет": ["портативн", "вычислительн", "tablet", "8471"],
    "ноутбук": ["портативн", "вычислительн", "компьютер", "laptop", "8471"],
    "компьютер": ["вычислительн", "обработк данн", "8471"],
    "ноут": ["портативн", "вычислительн", "8471"],
    "лэптоп": ["портативн", "вычислительн", "8471"],
    "телефон": ["аппарат телефонн", "смартфон", "8517"],
    "смартфон": ["аппарат телефонн", "телефон", "8517"],
    "айфон": ["аппарат телефонн", "смартфон", "8517"],
    "мобильн": ["аппарат телефонн", "сотов", "8517"],
    "холодильник": ["холодильн", "8418"],
    "морозильник": ["морозильн", "холодильн", "8418"],
    "кондиционер": ["кондиционирован", "8415"],
    "стиральн": ["стиральн", "машин для стирк", "8450"],
    "посудомоечн": ["посудомоечн", "8422"],
    "телевизор": ["приемник телевиз", "монитор", "8528"],
    "монитор": ["монитор", "видеоконтрольн", "8528"],
    "телек": ["приемник телевиз", "8528"],
    "автомобиль": ["моторн транспортн", "легков", "8703"],
    "машина": ["моторн транспортн", "легков", "8703"],
    "авто": ["моторн транспортн", "легков", "8703"],
    "грузовик": ["грузов", "транспортн средств", "8704"],
    "мотоцикл": ["мотоцикл", "8711"],
    "велосипед": ["велосипед", "8712"],
    "обувь": ["обувь", "6401", "6402", "6403", "6404", "6405"],
    "кроссовки": ["обувь", "спортивн", "6402", "6404"],
    "туфли": ["обувь", "6403", "6404"],
    "ботинки": ["обувь", "6403", "6402"],
    "сапоги": ["обувь", "6401", "6402", "6403"],
    "куртка": ["курт", "одежд", "6201", "6202"],
    "пальто": ["пальто", "одежд", "6201", "6202"],
    "шуба": ["мех", "одежд", "4303", "6201"],
    "футболка": ["трикотажн", "одежд", "6109"],
    "джинсы": ["брюк", "одежд", "6203", "6204"],
    "рубашка": ["рубаш", "одежд", "6205", "6206"],
    "платье": ["плат", "одежд", "6104", "6204"],
    "костюм": ["костюм", "одежд", "6103", "6203"],
    "яблок": ["яблок", "свеж", "0808"],
    "банан": ["банан", "0803"],
    "апельсин": ["апельсин", "цитрус", "0805"],
    "помидор": ["томат", "помидор", "0702"],
    "картофель": ["картофел", "0701"],
    "картошк": ["картофел", "0701"],
    "мясо": ["мяс", "говяд", "свинин", "0201", "0202", "0203"],
    "говядин": ["говяд", "крупн рогат", "0201", "0202"],
    "свинин": ["свинин", "0203"],
    "курица": ["куриц", "птиц", "домашн", "0207"],
    "курятин": ["куриц", "птиц", "0207"],
    "рыба": ["рыб", "0302", "0303", "0304"],
    "лосось": ["лосос", "форел", "0302", "0304"],
    "молоко": ["молок", "молочн", "0401", "0402"],
    "сыр": ["сыр", "0406"],
    "масло": ["масл", "подсолнечн", "оливков", "1512", "1509"],
    "сахар": ["сахар", "1701"],
    "кофе": ["кофе", "0901"],
    "чай": ["чай", "0902"],
    "шоколад": ["шоколад", "какао", "1806"],
    "вино": ["вино", "виноградн", "2204"],
    "пиво": ["пиво", "солодов", "2203"],
    "водка": ["водка", "спиртн", "2208"],
    "виски": ["виски", "спиртн", "2208"],
    "сигарет": ["сигарет", "табак", "2402"],
    "табак": ["табак", "табачн", "2401", "2402"],
    "бензин": ["бензин", "нефтепродукт", "2710"],
    "дизель": ["дизельн", "топлив", "газойл", "2710"],
    "нефть": ["нефт", "сыр", "2709"],
    "газ": ["газ природн", "сжиженн", "2711"],
    "лекарств": ["лекарственн", "фармацевтич", "медикамент", "3003", "3004"],
    "таблетк": ["лекарственн", "фармацевтич", "3004"],
    "витамин": ["витамин", "провитамин", "2936"],
    "косметик": ["косметическ", "парфюмерн", "3304"],
    "шампунь": ["шампун", "средств для волос", "3305"],
    "мыло": ["мыл", "3401"],
    "духи": ["парфюмерн", "туалетн вод", "3303"],
    "пластик": ["пластмасс", "полимер", "3901", "3902", "3903"],
    "полиэтилен": ["полиэтилен", "3901"],
    "резина": ["резин", "каучук", "4001", "4002"],
    "шина": ["шин", "пневматическ", "4011"],
    "покрышк": ["шин", "пневматическ", "4011"],
    "бумага": ["бумаг", "картон", "4801", "4802"],
    "картон": ["картон", "бумаг", "4819"],
    "книга": ["книг", "печатн", "4901"],
    "ткань": ["ткан", "текстильн"],
    "хлопок": ["хлопк", "хлопчатобумажн", "5201", "5208", "5209"],
    "шерсть": ["шерст", "5101"],
    "шелк": ["шёлк", "шелк", "5002", "5007"],
    "лен": ["льн", "5301", "5309"],
    "керамик": ["керамическ", "фарфор", "6901", "6911"],
    "стекло": ["стекл", "7003", "7005", "7006"],
    "сталь": ["сталь", "прокат", "металл", "7208", "7209"],
    "алюминий": ["алюмини", "7601", "7606"],
    "медь": ["мед", "7401", "7403", "7408"],
    "золото": ["золот", "7108"],
    "серебро": ["серебр", "7106"],
    "мебель": ["мебел", "9401", "9403"],
    "стул": ["стул", "сиден", "9401"],
    "стол": ["стол", "письменн", "9403"],
    "кровать": ["кроват", "9404"],
    "матрас": ["матрас", "матрац", "9404"],
    "игрушка": ["игрушк", "9503"],
    "кукла": ["кукл", "9503"],
    "велосипед": ["велосипед", "8712"],
    "коляска": ["коляск", "детск", "8715"],
    "часы": ["час", "наручн", "9101", "9102"],
    "очки": ["очк", "оптическ", "9004"],
    "линза": ["линз", "9001"],
    "фотоаппарат": ["фотокамер", "фотоаппарат", "9006"],
    "камера": ["камер", "видеокамер", "8525"],
    "принтер": ["принтер", "печатающ", "8443"],
    "сканер": ["сканер", "считыв", "8471"],
    "наушники": ["наушник", "головн телефон", "8518"],
    "колонка": ["громкоговорител", "динамик", "8518"],
    "микрофон": ["микрофон", "8518"],
    "батарея": ["аккумулятор", "батаре", "8507"],
    "аккумулятор": ["аккумулятор", "электрическ", "8507"],
    "провод": ["провод", "кабел", "электрическ", "8544"],
    "кабель": ["кабел", "провод", "8544"],
    "лампа": ["ламп", "осветительн", "8539", "9405"],
    "светильник": ["осветительн", "светильник", "9405"],
    "насос": ["насос", "8413"],
    "двигатель": ["двигател", "мотор", "8407", "8408", "8501"],
    "генератор": ["генератор", "электрогенератор", "8502"],
    "трансформатор": ["трансформатор", "8504"],
    "подшипник": ["подшипник", "8482"],
    "болт": ["болт", "винт", "7318"],
    "гвоздь": ["гвозд", "7317"],
    "труба": ["труб", "7304", "7305", "7306"],
    "удобрение": ["удобрен", "3102", "3103", "3104", "3105"],
    "цемент": ["цемент", "2523"],
    "кирпич": ["кирпич", "6901"],
    "краска": ["краск", "лак", "3208", "3209", "3210"],
    "клей": ["клей", "клеящ", "3506"],
    "лошадь": ["лошад", "живот", "0101"],
    "собака": ["собак", "0106"],
    "кошка": ["кошк", "домашн живот", "0106"],
    "корова": ["крупн рогат", "0102"],
    "свинья": ["свинь", "живые свинь", "0103"],
    "зерно": ["зерн", "пшениц", "1001"],
    "пшеница": ["пшениц", "1001"],
    "рис": ["рис", "1006"],
    "кукуруза": ["кукуруз", "1005"],
    "подсолнечник": ["подсолнечн", "семена", "1206"],
    "соя": ["соев", "1201"],
    "древесина": ["древесин", "лесоматериал", "4403", "4407"],
    "доска": ["пиломатериал", "доск", "4407"],
    "фанера": ["фанер", "4412"],
}

_SEARCH_SUGGESTIONS: list[dict[str, str]] = [
    {"term": "планшет", "hint": "8471 — Вычислительные машины"},
    {"term": "ноутбук", "hint": "8471 — Портативные вычислительные машины"},
    {"term": "телефон", "hint": "8517 — Аппараты телефонные"},
    {"term": "холодильник", "hint": "8418 — Холодильники, морозильники"},
    {"term": "автомобиль", "hint": "8703 — Моторные транспортные средства"},
    {"term": "обувь", "hint": "6401–6405 — Обувь"},
    {"term": "одежда", "hint": "6101–6211 — Одежда"},
    {"term": "мебель", "hint": "9401–9403 — Мебель"},
    {"term": "лекарство", "hint": "3003–3004 — Фармацевтическая продукция"},
    {"term": "косметика", "hint": "3304 — Косметические средства"},
]


def _expand_query_terms(query: str) -> list[str]:
    q = (query or "").strip().lower()
    if not q:
        return []
    terms = [q]
    for key, vals in _SYNONYM_MAP.items():
        if key in q:
            terms.extend(vals)
    # Stem-like prefix matching: trim last 1-2 chars for Russian morphology
    if len(q) >= 4 and not any(c.isdigit() for c in q):
        stem = q.rstrip("аеёиоуыэюяйьъ")
        if len(stem) >= 3 and stem != q:
            terms.append(stem)
    seen: set[str] = set()
    return [t for t in terms if t and not (t in seen or seen.add(t))]


def get_search_suggestions() -> list[dict[str, str]]:
    return _SEARCH_SUGGESTIONS


def upsert_tnved_entry(row: dict[str, Any]) -> None:
    with SessionLocal() as db:
        code = str(row.get("hs_code") or "").strip()
        if not code:
            return
        obj = db.query(TnvedEntry).filter(TnvedEntry.hs_code == code).first()
        fields = {
            "parent_hs": str(row.get("parent_hs") or "").strip(),
            "level": int(row.get("level") or len(code)),
            "title": str(row.get("title") or "").strip(),
            "description": str(row.get("description") or "").strip(),
            "chapter": str(row.get("chapter") or code[:2])[:4].strip(),
            "source_url": str(row.get("source_url") or "").strip(),
            "source_revision": str(row.get("source_revision") or "import").strip(),
        }
        if not obj:
            db.add(TnvedEntry(hs_code=code, **fields))
        else:
            for k, v in fields.items():
                setattr(obj, k, v)
        db.commit()


def upsert_normative_note(row: dict[str, Any]) -> None:
    with SessionLocal() as db:
        st = str(row.get("scope_type") or "prefix").strip()
        sv = str(row.get("scope_value") or "").strip()
        cat = str(row.get("category") or "general").strip()
        title = str(row.get("title") or "").strip() or "Примечание"
        obj = (
            db.query(NormativeNote)
            .filter(
                NormativeNote.scope_type == st,
                NormativeNote.scope_value == sv,
                NormativeNote.category == cat,
                NormativeNote.title == title,
            )
            .first()
        )
        body = str(row.get("body") or "").strip()
        payload = {
            "body": body,
            "source_url": str(row.get("source_url") or "").strip(),
            "source_revision": str(row.get("source_revision") or "import").strip(),
            "sort_order": int(row.get("sort_order") or 0),
        }
        if not obj:
            db.add(
                NormativeNote(
                    scope_type=st,
                    scope_value=sv,
                    category=cat,
                    title=title,
                    **payload,
                )
            )
        else:
            for k, v in payload.items():
                setattr(obj, k, v)
        db.commit()


def upsert_non_tariff_rule(row: dict[str, Any]) -> None:
    with SessionLocal() as db:
        name = str(row.get("name") or "").strip()
        hs_prefix = str(row.get("hs_prefix") or "").strip()
        if not name or not hs_prefix:
            return
        obj = (
            db.query(NonTariffRule)
            .filter(NonTariffRule.hs_prefix == hs_prefix, NonTariffRule.name == name)
            .first()
        )
        allowed = {
            "tr_ts",
            "required_permits",
            "tr_ts_edition",
            "exception_note",
            "valid_from",
            "valid_to",
            "source_url",
            "source_revision",
        }
        fields = {}
        for k in allowed:
            if k == "source_revision":
                fields[k] = str(row.get(k) or "import").strip()
            elif k == "exception_note":
                fields[k] = str(row.get(k) or "").strip()
            elif k == "tr_ts_edition":
                fields[k] = str(row.get(k) or "").strip()
            else:
                fields[k] = str(row.get(k) or "").strip()
        fields["priority"] = int(row.get("priority") or 0)
        if not obj:
            db.add(NonTariffRule(name=name, hs_prefix=hs_prefix, **fields))
        else:
            for k, v in fields.items():
                setattr(obj, k, v)
        db.commit()


def find_tnved_entry(hs_code: str) -> TnvedEntry | None:
    code = (hs_code or "").strip()
    if not code:
        return None
    with SessionLocal() as db:
        for variant in _hs_lookup_variants(code):
            obj = db.query(TnvedEntry).filter(TnvedEntry.hs_code == variant).first()
            if obj:
                return obj
        # префиксы 8,6,4
        d = _digits_hs(code)
        for length in (8, 6, 4, 2):
            if len(d) >= length:
                pref = d[:length]
                obj = db.query(TnvedEntry).filter(TnvedEntry.hs_code == pref).first()
            if obj:
                return obj
        return None


def get_tnved_breadcrumb(hs_code: str) -> list[dict[str, Any]]:
    """Цепочка от корня к найденной позиции (по parent_hs)."""
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = find_tnved_entry(hs_code)
    with SessionLocal() as db:
        while current is not None and current.hs_code not in seen:
            seen.add(current.hs_code)
            chain.append(
                {
                    "hs_code": current.hs_code,
                    "title": current.title or "",
                    "level": current.level,
                }
            )
            parent = (current.parent_hs or "").strip()
            if not parent:
                break
            current = db.query(TnvedEntry).filter(TnvedEntry.hs_code == parent).first()
    if chain:
        return list(reversed(chain))

    # Fallback: если иерархия в tnved_entries неполная, строим крошки из каталога tnved_commodities.
    d = _digits_hs(hs_code)
    if not d:
        return []
    with SessionLocal() as db:
        commodity = db.query(Commodity).filter(Commodity.code == d).first()
        if not commodity and len(d) >= 4:
            commodity = (
                db.query(Commodity)
                .filter(Commodity.code.like(f"{d[:4]}%"))
                .order_by(Commodity.code.asc())
                .first()
            )
        if not commodity:
            return []
        chapter = db.query(Chapter).filter(Chapter.id == commodity.chapter_id).first()
        section = db.query(Section).filter(Section.id == chapter.section_id).first() if chapter else None

    out: list[dict[str, Any]] = []
    if section:
        out.append(
            {
                "hs_code": section.roman_number or f"S{section.id}",
                "title": section.title or "",
                "level": 1,
            }
        )
    if chapter:
        out.append(
            {
                "hs_code": chapter.code or "",
                "title": chapter.title or "",
                "level": 2,
            }
        )
    out.append(
        {
            "hs_code": commodity.code,
            "title": (commodity.description or "").strip(),
            "level": 10,
        }
    )
    return out


def search_tnved(query: str, limit: int = 40) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if len(q) < 2:
        return []
    with SessionLocal() as db:
        qd = _digits_hs(q)
        # Основной путь — релевантный FTS5-поиск; сохраняет порядок релевантности.
        from .tnved_fts import search_commodities_fts

        fts_rows = search_commodities_fts(q, limit=limit)
        if fts_rows is not None:
            codes = [r["code"] for r in fts_rows if r.get("code")]
            if not codes:
                return []
            by_code = {
                c.code: c
                for c in db.query(Commodity).filter(Commodity.code.in_(codes)).all()
            }
            rows = [by_code[c] for c in codes if c in by_code]
        else:
            terms = _expand_query_terms(q)
            if not terms:
                return []
            filters = [func.lower(Commodity.description).like(f"%{t}%") for t in terms]
            if qd and len(qd) >= 2:
                filters.append(Commodity.code.like(f"{qd}%"))
            rows = (
                db.query(Commodity)
                .filter(or_(*filters))
                .order_by(Commodity.code.asc())
                .limit(limit)
                .all()
            )
        if not rows:
            return []

        expanded: dict[str, Commodity] = {r.code: r for r in rows}
        for row in rows:
            code = (row.code or "").strip()
            if len(code) == 10 and code.endswith("0000"):
                pref6 = code[:6]
                kids = (
                    db.query(Commodity)
                    .filter(Commodity.code.like(f"{pref6}%"))
                    .order_by(Commodity.code.asc())
                    .limit(max(1, limit - len(expanded)))
                    .all()
                )
                for k in kids:
                    if len(expanded) >= limit:
                        break
                    expanded.setdefault(k.code, k)
            if len(expanded) >= limit:
                break
        rows = sorted(expanded.values(), key=lambda x: x.code)[:limit]

        codes = [r.code for r in rows if r.code]
        entries = db.query(TnvedEntry).filter(TnvedEntry.hs_code.in_(codes)).all() if codes else []
        by_code = {e.hs_code: e for e in entries}

        return [
            {
                "code": r.code,
                "description": (r.description or "").strip(),
                "hs_code": (by_code.get(r.code).hs_code if by_code.get(r.code) else None),
                # Для обратной совместимости текущих клиентов.
                "title": (by_code.get(r.code).title if by_code.get(r.code) else (r.description or "").strip()),
                "level": (by_code.get(r.code).level if by_code.get(r.code) else 10),
                "chapter": (by_code.get(r.code).chapter if by_code.get(r.code) else (r.code[:2] if r.code else "")),
            }
            for r in rows
        ]


def find_normative_notes_for_hs(hs_code: str) -> list[dict[str, Any]]:
    """Примечания, применимые к коду (глобальные, глава, префиксы, точное совпадение)."""
    d = _digits_hs(hs_code)
    if not d:
        return []
    chapter = d[:2] if len(d) >= 2 else ""
    with SessionLocal() as db:
        collected: list[NormativeNote] = []
        seen_ids: set[int] = set()

        def add_rows(rows: list[NormativeNote]) -> None:
            for n in rows:
                if n.id not in seen_ids:
                    seen_ids.add(n.id)
                    collected.append(n)

        add_rows(
            db.query(NormativeNote)
            .filter(NormativeNote.scope_type == "global")
            .order_by(NormativeNote.sort_order, NormativeNote.id)
            .all()
        )
        if chapter:
            add_rows(
                db.query(NormativeNote)
                .filter(
                    NormativeNote.scope_type == "chapter",
                    NormativeNote.scope_value == chapter,
                )
                .order_by(NormativeNote.sort_order, NormativeNote.id)
                .all()
            )
        for length in (10, 8, 6, 4):
            if len(d) >= length:
                pref = d[:length]
                add_rows(
                    db.query(NormativeNote)
                    .filter(
                        NormativeNote.scope_type == "prefix",
                        NormativeNote.scope_value == pref,
                    )
                    .order_by(NormativeNote.sort_order, NormativeNote.id)
                    .all()
                )
        add_rows(
            db.query(NormativeNote)
            .filter(
                NormativeNote.scope_type == "hs_code",
                NormativeNote.scope_value == d,
            )
            .order_by(NormativeNote.sort_order, NormativeNote.id)
            .all()
        )
        add_rows(
            db.query(NormativeNote)
            .filter(
                NormativeNote.scope_type == "hs_code",
                NormativeNote.scope_value == d.ljust(10, "0"),
            )
            .order_by(NormativeNote.sort_order, NormativeNote.id)
            .all()
        )

        return [
            {
                "id": n.id,
                "scope_type": n.scope_type,
                "scope_value": n.scope_value,
                "category": n.category,
                "title": n.title,
                "body": n.body,
                "source_url": n.source_url,
                "source_revision": n.source_revision,
                "sort_order": n.sort_order,
            }
            for n in sorted(collected, key=lambda x: (x.sort_order, x.id))
        ]


def get_tnved_context_for_hs(hs_code: str) -> dict[str, Any]:
    """Сводка для калькулятора / API: наименование, иерархия, примечания."""
    entry = find_tnved_entry(hs_code)
    breadcrumb = get_tnved_breadcrumb(hs_code)
    commodity_title = ""
    commodity_description = ""
    d = _digits_hs(hs_code)
    if d and (entry is None or not (entry.title or "").strip() or not (entry.description or "").strip()):
        with SessionLocal() as db:
            commodity = db.query(Commodity).filter(Commodity.code == d).first()
            if not commodity and len(d) >= 4:
                commodity = (
                    db.query(Commodity)
                    .filter(Commodity.code.like(f"{d[:4]}%"))
                    .order_by(Commodity.code.asc())
                    .first()
                )
            if commodity:
                commodity_title = (commodity.description or "").strip()
                commodity_description = (commodity.description or "").strip()
    notes = find_normative_notes_for_hs(hs_code)
    official = "https://eec.eaeunion.org/comission/department/catr/ett/"
    return {
        "hs_code": _digits_hs(hs_code),
        "title": (entry.title if entry else "") or commodity_title,
        "description": (entry.description if entry else "") or commodity_description,
        "breadcrumb": breadcrumb,
        "notes": notes,
        "official_ett_url": official,
        "source_revision": (entry.source_revision if entry else "") or "",
    }


def list_source_status() -> list[dict[str, Any]]:
    """Список источников с датой обновления, версией и флагом деградации (fallback)."""
    with SessionLocal() as db:
        rows = db.query(SourceStatus).order_by(SourceStatus.source_code.asc()).all()
        return [
            {
                "source_code": r.source_code,
                "source_name": r.source_name,
                "source_url": r.source_url,
                "revision": r.revision,
                "synced_at": r.synced_at.isoformat() if r.synced_at else None,
                "is_stale": r.is_stale,
                "fallback": r.is_stale or r.revision in ("unavailable", "seed"),
                "note": r.note,
            }
            for r in rows
        ]


def list_sync_log(source_code: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        q = db.query(SyncLog)
        if source_code:
            q = q.filter(SyncLog.source_code == source_code)
        rows = q.order_by(SyncLog.synced_at.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "source_code": r.source_code,
                "synced_at": r.synced_at.isoformat() if r.synced_at else None,
                "status": r.status,
                "revision": r.revision,
                "rows_affected": r.rows_affected,
                "note": r.note,
            }
            for r in rows
        ]


def list_tr_ts_acts(query: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Справочник карточек ТР ТС (для UI и сверки с правилами)."""
    q = (query or "").strip().lower()
    with SessionLocal() as db:
        rows = db.query(TrTsAct).order_by(TrTsAct.act_code.asc()).all()
    out: list[dict[str, Any]] = []
    for r in rows:
        if q and q not in (r.act_code or "").lower() and q not in (r.short_name or "").lower():
            continue
        out.append(
            {
                "act_code": r.act_code,
                "short_name": r.short_name or "",
                "full_title": r.full_title or "",
                "edition_note": r.edition_note or "",
                "source_url": r.source_url or "",
                "source_revision": r.source_revision or "",
            }
        )
        if len(out) >= limit:
            break
    return out


def lookup_tr_ts_acts_by_codes(codes: list[str]) -> list[dict[str, Any]]:
    """Детализация по кодам NNN/YYYY в порядке запроса (с плейсхолдером, если нет в БД)."""
    if not codes:
        return []
    uniq: list[str] = []
    seen: set[str] = set()
    for c in codes:
        c = str(c).strip()
        if not c or c in seen:
            continue
        seen.add(c)
        uniq.append(c)
    with SessionLocal() as db:
        rows = db.query(TrTsAct).filter(TrTsAct.act_code.in_(uniq)).all()
        by_code = {r.act_code: r for r in rows}
    out: list[dict[str, Any]] = []
    for c in uniq:
        r = by_code.get(c)
        if r:
            out.append(
                {
                    "act_code": r.act_code,
                    "short_name": r.short_name or "",
                    "full_title": r.full_title or "",
                    "edition_note": r.edition_note or "",
                    "source_url": r.source_url or "",
                    "source_revision": r.source_revision or "",
                    "in_registry": True,
                }
            )
        else:
            out.append(
                {
                    "act_code": c,
                    "short_name": "",
                    "full_title": "",
                    "edition_note": "",
                    "source_url": "",
                    "source_revision": "",
                    "in_registry": False,
                    "note": "Карточка не заведена в БД приложения",
                }
            )
    return out


def get_country_risk_by_iso(iso: str | None) -> CountryRisk | None:
    """Справочник CountryRisk по ISO-2 (верхний регистр)."""
    if not iso:
        return None
    code = str(iso).strip().upper()[:2]
    if len(code) != 2 or not code.isalpha():
        return None
    with SessionLocal() as db:
        return db.query(CountryRisk).filter(CountryRisk.iso_code == code).first()


def get_tariff_preference(iso: str | None) -> CountryTariffPreference | None:
    """Тарифная преференция по ISO-2 коду страны."""
    if not iso:
        return None
    code = str(iso).strip().upper()[:2]
    if len(code) != 2 or not code.isalpha():
        return None
    with SessionLocal() as db:
        return (
            db.query(CountryTariffPreference)
            .filter(CountryTariffPreference.country_code == code)
            .first()
        )


_GEO_DUTY_MEASURE_TYPES = frozenset({"increased_duty", "anti_dumping"})


def _query_geo_special_rows_sql(
    db,
    p_norm: str,
    origin_iso: str,
    *,
    country_is_unfriendly: bool,
) -> list[GeoSpecialDuty]:
    """Строки geo_special_duties: код начинается с сохранённого префикса; страна ISO2 или ALL_UNFRIENDLY."""
    o = origin_iso.strip().upper()[:2]
    if len(o) != 2 or not o.isalpha():
        return []
    country_clause = (
        or_(GeoSpecialDuty.country_iso == o, GeoSpecialDuty.country_iso == "ALL_UNFRIENDLY")
        if country_is_unfriendly
        else (GeoSpecialDuty.country_iso == o)
    )
    rows = (
        db.query(GeoSpecialDuty)
        .filter(
            literal(p_norm).like(func.concat(GeoSpecialDuty.hs_code_prefix, "%")),
            country_clause,
        )
        .all()
    )
    out: list[GeoSpecialDuty] = []
    for row in rows:
        c = (row.country_iso or "").strip().upper()
        if c == "ALL_UNFRIENDLY" and not country_is_unfriendly:
            continue
        if c not in ("ALL_UNFRIENDLY", o):
            continue
        out.append(row)
    return out


def _pick_longest_hs_prefix(rows: list[GeoSpecialDuty]) -> GeoSpecialDuty | None:
    best: GeoSpecialDuty | None = None
    best_len = -1
    for row in rows:
        pref = re.sub(r"\D", "", (row.hs_code_prefix or ""))[:10]
        if not pref or len(pref) < 2:
            continue
        lp = len(pref)
        if lp > best_len:
            best_len = lp
            best = row
    return best


def find_geo_embargo_match(
    hs_digits: str,
    origin_iso: str | None,
    *,
    country_is_unfriendly: bool,
) -> GeoSpecialDuty | None:
    """Эмбарго / запрет ввоза (measure_type == embargo), самый длинный префикс ТН ВЭД."""
    p = re.sub(r"\D", "", hs_digits or "")[:10]
    if len(p) < 4 or not origin_iso:
        return None
    o = str(origin_iso).strip().upper()[:2]
    if len(o) != 2 or not o.isalpha():
        return None
    with SessionLocal() as db:
        rows = _query_geo_special_rows_sql(db, p, o, country_is_unfriendly=country_is_unfriendly)
    cand = [r for r in rows if (r.measure_type or "increased_duty").strip().lower() == "embargo"]
    return _pick_longest_hs_prefix(cand)


def find_geo_duty_override_row(
    hs_digits: str,
    origin_iso: str | None,
    *,
    country_is_unfriendly: bool,
) -> GeoSpecialDuty | None:
    """Повышенная / антидемпинговая ставка (не preference, не embargo)."""
    p = re.sub(r"\D", "", hs_digits or "")[:10]
    if len(p) < 4 or not origin_iso:
        return None
    o = str(origin_iso).strip().upper()[:2]
    if len(o) != 2 or not o.isalpha():
        return None
    with SessionLocal() as db:
        rows = _query_geo_special_rows_sql(db, p, o, country_is_unfriendly=country_is_unfriendly)
    cand = [
        r for r in rows if (r.measure_type or "increased_duty").strip().lower() in _GEO_DUTY_MEASURE_TYPES
    ]
    return _pick_longest_hs_prefix(cand)


def find_geo_special_duty(
    hs_digits: str,
    origin_iso: str | None,
    *,
    country_is_unfriendly: bool,
) -> GeoSpecialDuty | None:
    """
    Повышенная ставка из geo_special_duties: префикс ТН ВЭД (4–10 знаков)
    и country_iso == ISO2 либо ALL_UNFRIENDLY при недружественной стране.
    Возвращает строку с самым длинным подходящим hs_code_prefix (только increased_duty / anti_dumping).
    """
    return find_geo_duty_override_row(
        hs_digits, origin_iso, country_is_unfriendly=country_is_unfriendly
    )


def upsert_geo_special_duty(
    *,
    hs_code_prefix: str,
    country_iso: str,
    duty_rate: str | float | int,
    document_basis: str,
    measure_type: str = "increased_duty",
    document_link: str = "",
) -> None:
    """Идемпотентная запись по паре (префикс ТН ВЭД, document_basis, country_iso)."""
    pref = re.sub(r"\D", "", hs_code_prefix or "")[:10]
    basis = (document_basis or "").strip()[:512]
    ciso = (country_iso or "").strip().upper()[:20]
    mt = (measure_type or "increased_duty").strip()[:32] or "increased_duty"
    link = (document_link or "").strip()
    duty_s = normalize_hs_duty_rate_string(duty_rate)[:512]
    if len(pref) < 2 or not basis or not ciso:
        return
    with SessionLocal() as db:
        row = (
            db.query(GeoSpecialDuty)
            .filter(
                GeoSpecialDuty.hs_code_prefix == pref,
                GeoSpecialDuty.document_basis == basis,
                GeoSpecialDuty.country_iso == ciso,
            )
            .first()
        )
        if row:
            row.duty_rate = duty_s
            row.measure_type = mt
            row.document_link = link
        else:
            db.add(
                GeoSpecialDuty(
                    hs_code_prefix=pref,
                    country_iso=ciso,
                    duty_rate=duty_s,
                    document_basis=basis,
                    measure_type=mt,
                    document_link=link,
                )
            )
        db.commit()


def find_classification_rulings(hs_code: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Find formal classification rulings matching an HS code by prefix."""
    from ..models.tnved import ClassificationRuling

    d = _digits_hs(hs_code)
    if not d or len(d) < 4:
        return []
    prefixes = []
    for length in (10, 8, 6, 4):
        if len(d) >= length:
            prefixes.append(d[:length])
    with SessionLocal() as db:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for pref in prefixes:
            rows = (
                db.query(ClassificationRuling)
                .filter(ClassificationRuling.assigned_hs_code.like(f"{pref}%"))
                .order_by(ClassificationRuling.ruling_date.desc())
                .limit(limit)
                .all()
            )
            for r in rows:
                if r.ruling_number in seen:
                    continue
                seen.add(r.ruling_number)
                results.append({
                    "ruling_number": r.ruling_number,
                    "ruling_date": r.ruling_date or "",
                    "agency": r.agency or "",
                    "goods_description": r.goods_description or "",
                    "assigned_hs_code": r.assigned_hs_code or "",
                    "rationale": r.rationale or "",
                    "source_url": r.source_url or "",
                    "is_official": bool(getattr(r, "is_official", True)),
                })
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
    results.sort(key=lambda x: x["ruling_date"], reverse=True)
    return results[:limit]


def find_declaration_documents(hs_code: str) -> list[dict[str, Any]]:
    """Lookup required documents for customs declaration by HS code.

    Returns universal documents (hs_prefix='') plus code-specific ones,
    sorted: mandatory first, then by category.
    """
    from ..models.tnved import DeclarationDocument

    d = _digits_hs(hs_code)
    prefixes = [""]
    if d:
        for length in (10, 8, 6, 4, 2):
            if len(d) >= length:
                prefixes.append(d[:length])
    with SessionLocal() as db:
        rows = db.query(DeclarationDocument).filter(
            DeclarationDocument.hs_prefix.in_(prefixes)
        ).all()
    if not rows:
        return []
    seen_types: set[str] = set()
    results: list[dict[str, Any]] = []
    rows_sorted = sorted(rows, key=lambda r: (
        0 if r.hs_prefix else 1,
        -len(r.hs_prefix),
        0 if r.is_mandatory else 1,
    ))
    for r in rows_sorted:
        key = f"{r.doc_type}:{r.doc_name}"
        if key in seen_types:
            continue
        seen_types.add(key)
        results.append({
            "hs_prefix": r.hs_prefix,
            "doc_type": r.doc_type,
            "doc_name": r.doc_name,
            "is_mandatory": r.is_mandatory,
            "condition": r.condition or "",
            "legal_ref": r.legal_ref or "",
            "category": r.category or "general",
        })
    cat_order = {"general": 0, "commercial": 1, "transport": 2, "conformity": 3, "special": 4, "origin": 5, "payment": 6}
    results.sort(key=lambda x: (
        0 if x["is_mandatory"] else 1,
        cat_order.get(x["category"], 99),
        x["doc_name"],
    ))
    return results


def find_import_restrictions(hs_code: str, *, country: str | None = None) -> list[dict[str, Any]]:
    """Lookup import restrictions (bans, quotas, sanctions, dual-use, licensing) for an HS code."""
    from ..models.tnved import ImportRestriction

    d = _digits_hs(hs_code)
    if not d or len(d) < 4:
        return []
    prefixes = []
    for length in (10, 8, 6, 4):
        if len(d) >= length:
            prefixes.append(d[:length])
    with SessionLocal() as db:
        rows = db.query(ImportRestriction).filter(
            ImportRestriction.hs_prefix.in_(prefixes)
        ).all()
    if not rows:
        return []
    results: list[dict[str, Any]] = []
    country_upper = (country or "").strip().upper()
    for r in rows:
        if country_upper and r.country_code != "ALL" and r.country_code != country_upper:
            continue
        results.append({
            "hs_prefix": r.hs_prefix,
            "restriction_type": r.restriction_type,
            "country_code": r.country_code,
            "description": r.description or "",
            "legal_ref": r.legal_ref or "",
            "effective_from": r.effective_from or "",
            "effective_to": r.effective_to or "",
            "severity": r.severity or "warning",
            "source_url": r.source_url or "",
        })
    results.sort(key=lambda x: (
        {"block": 0, "warning": 1}.get(x["severity"], 2),
        x["hs_prefix"],
    ))
    return results


def get_recycling_fee(hs_code: str, *, is_new: bool = True, engine_volume: int | None = None) -> list[dict[str, Any]]:
    """Lookup recycling fees for a vehicle HS code (8701-8705, 8711).

    Returns matching fee rows sorted by specificity (exact volume match first).
    """
    from ..models.tnved import RecyclingFee

    d = _digits_hs(hs_code)
    if not d or len(d) < 4:
        return []
    prefix = d[:4]
    vehicle_prefixes = {"8701", "8702", "8703", "8704", "8705", "8711"}
    if prefix not in vehicle_prefixes:
        return []
    with SessionLocal() as db:
        q = db.query(RecyclingFee).filter(
            RecyclingFee.hs_prefix == prefix,
            RecyclingFee.is_new == is_new,
        )
        rows = q.all()
    if not rows:
        return []
    results: list[dict[str, Any]] = []
    for r in rows:
        vol_from = r.engine_volume_from
        vol_to = r.engine_volume_to
        if engine_volume is not None and vol_from is not None:
            if engine_volume < vol_from:
                continue
            if vol_to is not None and engine_volume >= vol_to:
                continue
        results.append({
            "vehicle_type": r.vehicle_type,
            "is_new": r.is_new,
            "base_rate": float(r.base_rate),
            "coefficient": float(r.coefficient),
            "fee_amount": round(float(r.base_rate) * float(r.coefficient), 2),
            "engine_volume_from": r.engine_volume_from,
            "engine_volume_to": r.engine_volume_to,
            "description": r.description or "",
            "legal_ref": r.legal_ref or "",
        })
    results.sort(key=lambda x: (
        0 if (x["engine_volume_from"] is not None and engine_volume is not None) else 1,
        x.get("engine_volume_from") or 0,
    ))
    return results


def format_applied_special_duty_label(document_basis: str) -> str:
    """Краткая подпись для колонки Excel (например «ПП РФ №2140»)."""
    s = (document_basis or "").strip()
    if not s:
        return ""
    if "2140" in s:
        return "ПП РФ №2140"
    return s[:80]
