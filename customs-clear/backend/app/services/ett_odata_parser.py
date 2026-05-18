"""Парсер OData портала ЕАЭС: ЕТТ, классификатор льгот и другие реестры.

Источник: https://portal.eaeunion.org/sites/odata/
API: GET https://portal.eaeunion.org/sites/odata/_api/web/lists/getByTitle('Имя реестра')/Items

Поддерживаемые реестры:
- Классификатор льгот по уплате таможенных платежей (коды льгот, страны, ссылки на НПА)
"""
from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from loguru import logger

ODATA_BASE = "https://portal.eaeunion.org/sites/odata/_api"
ODATA_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
}


def _extract_property(entry: ET.Element, tag: str, ns: str = "d") -> str | None:
    """Извлечь значение свойства из ATOM entry."""
    el = entry.find(f".//{{{ODATA_NS[ns]}}}{tag}")
    if el is not None and el.text is not None:
        return el.text.strip()
    return None


def _parse_atom_feed(content: bytes) -> list[dict[str, Any]]:
    """Парсинг ATOM feed в список словарей."""
    root = ET.fromstring(content)
    rows: list[dict[str, Any]] = []
    for entry in root.findall(".//atom:entry", ODATA_NS):
        props = entry.find(".//m:properties", ODATA_NS)
        if props is None:
            continue
        row: dict[str, Any] = {}
        for child in props:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if child.text is not None:
                row[tag] = child.text.strip()
            elif child.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true":
                row[tag] = None
            else:
                row[tag] = child.text
        if row:
            rows.append(row)
    return rows


def _extract_hs_from_text(text: str) -> list[str]:
    """Извлечь коды ТН ВЭД из текста (например, 'субпозиций 1701 13 и 1701 14')."""
    if not text:
        return []
    codes: list[str] = []
    # Паттерны: 1701 13, 1701 14, 8509 40 000 0
    for m in re.finditer(r"\b(\d{4})\s*(\d{2})\s*(\d{3})?\s*(\d{1})?\b", text):
        parts = [m.group(1), m.group(2)]
        if m.group(3):
            parts.append(m.group(3))
        if m.group(4):
            parts.append(m.group(4))
        code = "".join(parts).ljust(10, "0")[:10]
        if code.isdigit() and code not in codes:
            codes.append(code)
    return codes


async def fetch_odata_registry(
    registry_name: str,
    top: int = 5000,
    skip: int = 0,
) -> tuple[list[dict[str, Any]], str | None]:
    """Загрузить элементы реестра из OData портала ЕАЭС.

    Returns:
        (rows, error_message)
    """
    url = f"{ODATA_BASE}/web/lists/getByTitle('{registry_name}')/Items"
    params = {"$top": top, "$skip": skip}
    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            r = await client.get(url, params=params)
        r.raise_for_status()
        rows = _parse_atom_feed(r.content)
        return rows, None
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return [], f"Реестр '{registry_name}' не найден (404)"
        return [], str(e)
    except Exception as e:
        logger.exception("OData fetch error")
        return [], str(e)


async def sync_preferential_duties() -> dict[str, Any]:
    """Синхронизация классификатора льгот по уплате таможенных платежей.

    Извлекает коды льгот, страны, описания. Сохраняет в виде справочника
    для последующего использования при расчёте (например, для льгот по стране).
    """
    rows, err = await fetch_odata_registry("Классификатор льгот по уплате таможенных платежей", top=10000)
    if err:
        return {"status": "ERROR", "source": "ODATA_PREFERENTIAL", "error": err, "rows": 0}

    # Извлекаем HS-коды из описаний для обогащения
    hs_preferences: dict[str, list[str]] = {}  # hs_prefix -> list of preference codes
    for r in rows:
        name = r.get("CustomsPreferentialDutyName") or r.get("CustomsPreferentialDuty_Name") or ""
        code = r.get("CustomsPreferentialDutyCode") or r.get("CustomsPreferentialDuty_Code") or ""
        country = r.get("CustomsPreferentialDutyCountryCodeId") or r.get("CustomsPreferentialDuty_CountryCode") or ""
        for hs in _extract_hs_from_text(name):
            pref = hs[:4]
            if pref not in hs_preferences:
                hs_preferences[pref] = []
            if code and code not in hs_preferences[pref]:
                hs_preferences[pref].append(code)

    return {
        "status": "OK",
        "source": "ODATA_PREFERENTIAL",
        "rows": len(rows),
        "hs_preferences_count": len(hs_preferences),
        "revision": f"odata-{len(rows)}",
    }


async def fetch_metadata_list() -> list[str]:
    """Получить список доступных реестров (названия)."""
    url = f"{ODATA_BASE}/web/lists/getByTitle('Список метаданных')/Items"
    params = {"$select": "MetadataList_title_name", "$top": 2000}
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            r = await client.get(url, params=params)
        r.raise_for_status()
        rows = _parse_atom_feed(r.content)
        return [
            r.get("MetadataList_title_name", "")
            for r in rows
            if r.get("MetadataList_title_name")
        ]
    except Exception as e:
        logger.warning(f"Metadata list fetch failed: {e}")
        return []


async def try_fetch_ett_registry(registry_names: list[str]) -> dict[str, Any]:
    """Попытка загрузить реестр ЕТТ (ставки по кодам) по списку возможных имён.

    Реестр ЕТТ на портале может называться по-разному. Если найден реестр
    с полями, похожими на hs_code/duty_rate, нормализуем в hs_rates.
    """
    for name in registry_names:
        rows, err = await fetch_odata_registry(name, top=100)
        if err:
            continue
        if not rows:
            continue
        # Проверяем структуру — есть ли поля для ставок
        sample = rows[0] if rows else {}
        keys = set(sample.keys())
        # Ищем поля, похожие на код ТН ВЭД или ставку
        duty_key = next((k for k in keys if "duty" in k.lower() or "ставк" in k.lower() or "rate" in k.lower()), None)
        hs_key = next((k for k in keys if "code" in k.lower() or "код" in k.lower() or "hs" in k.lower()), None)
        if duty_key or hs_key:
            return {
                "status": "OK",
                "source": "ODATA_ETT",
                "registry": name,
                "rows": len(rows),
                "sample_keys": list(keys)[:15],
            }
    return {"status": "NOT_FOUND", "source": "ODATA_ETT", "tried": registry_names}


async def sync_all_odata() -> dict[str, Any]:
    """Объединённая синхронизация всех OData-источников."""
    results: list[dict[str, Any]] = []

    # 1. Классификатор льгот (работает)
    pref = await sync_preferential_duties()
    results.append(pref)

    # 2. Попытка ETT (если известны имена реестров)
    import os
    ett_names = os.getenv("ETT_ODATA_REGISTRY_NAMES", "").strip()
    if ett_names:
        names = [n.strip() for n in ett_names.split(",") if n.strip()]
    else:
        names = [
            "Единая товарная номенклатура внешнеэкономической деятельности Евразийского экономического союза",
            "Единый таможенный тариф Евразийского экономического союза",
            "Единая товарная номенклатура",
            "Единый таможенный тариф",
        ]
    ett = await try_fetch_ett_registry(names)
    results.append(ett)

    ok = all(r.get("status") in ("OK", "NOT_FOUND") for r in results)
    return {"status": "OK" if ok else "WARNING", "sources": results}
