"""Проверка разрешительных документов (СС, ДС, СГР) — автопоиск в реестрах."""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from .cache_layer import PERMITS_PREFIX, cache_get, cache_set

_PERMITS_TTL = int(os.getenv("PERMITS_CACHE_TTL_SECONDS", os.getenv("CACHE_TTL_SECONDS", "3600")))

# Реестры ФСА (при 403 можно использовать внешний API: FSA_EXTERNAL_API_URL)
FSA_CERT_URL = os.getenv("FSA_CERT_URL", "https://pub.fsa.gov.ru/rss/certificate")
FSA_DECL_URL = os.getenv("FSA_DECL_URL", "https://pub.fsa.gov.ru/rds/declaration")
FSA_API_DECL = "https://pub.fsa.gov.ru/api/v1/rds/declaration"
FSA_API_CERT = "https://pub.fsa.gov.ru/api/v1/rss/certificate"
FSA_EXTERNAL_API = os.getenv("FSA_EXTERNAL_API_URL", "").rstrip("/")  # Опционально: URL платного API
SGR_SEARCH_URL = "https://fp.crc.ru/evrazes/"

# Пауза между запросами к ФСА (сайт блокирует при частых запросах)
FSA_DELAY_SEC = float(os.getenv("FSA_REQUEST_DELAY", "2.0"))
FSA_RETRIES = int(os.getenv("FSA_RETRIES", "2"))
_LAST_FSA_REQUEST: float = 0
_FSA_LOCK = asyncio.Lock()
REGISTRY_SOURCE = "pub.fsa.gov.ru (Росаккредитация)"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
# Некоторые gov-сайты (fp.crc.ru) могут иметь проблемы с SSL — отключить: PERMITS_VERIFY_SSL=false
HTTP_VERIFY_SSL = os.getenv("PERMITS_VERIFY_SSL", "true").lower() not in ("0", "false", "no")


def normalize_number(raw: str) -> str:
    """Приводит номер ДС/СС/СГР к стабильному виду.

    Не удаляем латинскую «N» внутри кода (например CN в «Д-CN.…»): ранее
    удаление всех символов N и № портило номера ЕАЭС.
    """
    if not raw:
        return ""
    s = str(raw).upper().strip()
    s = re.sub(r"№+", "", s)
    # «ЕАЭС N RU» / «EAEU N RU» — служебный маркер номера, не часть кода
    s = re.sub(r"(?<=(?:ЕАЭС|EAEU))\s+N\s+", " ", s)
    s = re.sub(r"\s+", "", s)
    return s


def _extract_sgr_from_html(html: str, search_number: str) -> Dict[str, Any]:
    """Парсинг страницы fp.crc.ru — поиск по номеру СГР."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()
    norm = normalize_number(search_number)

    # «Найдено 0 документов» — не найдено
    if "Найдено 0 документов" in text or "найдено 0 документов" in text.lower():
        return {
            "type": "СГР",
            "status": "NOT_FOUND",
            "number": norm,
            "holder": None,
            "valid_from": None,
            "valid_to": None,
            "registry_link": f"{SGR_SEARCH_URL}?oper=s&text_svid={quote(norm)}&type=max",
            "raw": None,
        }

    # Ищем «Найдено N документов» и проверяем, что наш номер есть в результатах
    # (fp.crc.ru при нечётком поиске может вернуть полный список)
    match = re.search(r"Найдено\s+(\d+)\s+документ", text, re.I)
    if match and int(match.group(1)) > 0:
        # Точное совпадение номера в тексте страницы (формат RU.XX.XX...)
        if norm not in text and norm.replace(".", "") not in text.replace(".", ""):
            return {
                "type": "СГР",
                "status": "NOT_FOUND",
                "number": norm,
                "holder": None,
                "valid_from": None,
                "valid_to": None,
                "registry_link": f"{SGR_SEARCH_URL}?oper=s&text_svid={quote(norm)}&type=max",
                "raw": None,
            }
        holder = None
        product = None
        valid_to = None
        # Пытаемся извлечь первый результат
        for block in soup.find_all(["div", "td", "p"]):
            t = block.get_text(strip=True)
            if "Номер свидетельства и дата" in t or "Номер свидетельства" in t:
                continue
            if "Изготовитель" in t or "Получатель" in t:
                holder = re.sub(r"^(Изготовитель|Получатель)\s*[—\-:]\s*", "", t, flags=re.I)[:200]
            if "Продукция" in t and "—" in t:
                product = re.sub(r"^Продукция\s*[—\-:]\s*", "", t, flags=re.I)[:150]
            if "Действует до" in t:
                valid_to = re.sub(r"^Действует до\s*[—\-:]\s*", "", t, flags=re.I).strip()
            if holder and product:
                break

        return {
            "type": "СГР",
            "status": "VALID",
            "number": norm,
            "holder": holder,
            "valid_from": None,
            "valid_to": valid_to,
            "registry_link": f"{SGR_SEARCH_URL}?oper=s&text_svid={quote(norm)}&type=max",
            "raw": {"product": product} if product else None,
        }

    return {
        "type": "СГР",
        "status": "UNKNOWN",
        "number": norm,
        "holder": None,
        "valid_from": None,
        "valid_to": None,
        "registry_link": f"{SGR_SEARCH_URL}?oper=s&text_svid={quote(norm)}&type=max",
        "raw": None,
    }


async def _delay_fsa() -> None:
    """Пауза перед запросом к ФСА, чтобы избежать блокировки."""
    async with _FSA_LOCK:
        global _LAST_FSA_REQUEST
        elapsed = time.monotonic() - _LAST_FSA_REQUEST
        if elapsed < FSA_DELAY_SEC:
            await asyncio.sleep(FSA_DELAY_SEC - elapsed)
        _LAST_FSA_REQUEST = time.monotonic()


def _collect_tnved_from_obj(obj: Any, out: List[str], depth: int = 0) -> None:
    """Рекурсивно ищет коды ТН ВЭД в JSON реестра ФСА."""
    if depth > 12:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if any(x in lk for x in ("tnved", "tn_ved", "tnvedcode", "productcode", "кодтнвэд")):
                if isinstance(v, str) and re.match(r"^\d{4,10}$", re.sub(r"\s", "", v)):
                    out.append(re.sub(r"\s", "", v)[:10])
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, str) and re.match(r"^\d{4,10}$", re.sub(r"\s", "", x)):
                            out.append(re.sub(r"\s", "", x)[:10])
            _collect_tnved_from_obj(v, out, depth + 1)
    elif isinstance(obj, list):
        for it in obj:
            _collect_tnved_from_obj(it, out, depth + 1)


def _parse_first_fsa_record(content: list[Any]) -> Dict[str, Any]:
    """Извлекает поля из первой записи content API ФСА."""
    if not content or not isinstance(content[0], dict):
        return {}
    row = content[0]
    holder = (
        row.get("applicantName")
        or row.get("declarantName")
        or row.get("manufacturerName")
        or row.get("holderName")
    )
    vfrom = row.get("beginDate") or row.get("startDate") or row.get("issueDate")
    vto = row.get("endDate") or row.get("expiryDate") or row.get("validTo")
    tnveds: List[str] = []
    _collect_tnved_from_obj(row, tnveds)
    return {
        "holder": str(holder)[:500] if holder else None,
        "valid_from": str(vfrom)[:32] if vfrom else None,
        "valid_to": str(vto)[:32] if vto else None,
        "registry_tnved_codes": list(dict.fromkeys(tnveds))[:50],
    }


def match_item_hs_to_registry(item_hs: str, registry_codes: List[str]) -> Dict[str, Any]:
    """Сверка кода позиции с ТН ВЭД из карточки реестра."""
    code = re.sub(r"\D", "", item_hs or "")[:10]
    if not code or not registry_codes:
        return {"hs_match": "unknown", "detail": "Нет кодов ТН ВЭД в ответе реестра или не указан код позиции"}
    reg_norm = [re.sub(r"\D", "", c)[:10] for c in registry_codes if c]
    for rc in reg_norm:
        if not rc:
            continue
        if code == rc or code.startswith(rc) or rc.startswith(code[: len(rc)]):
            return {"hs_match": "ok", "detail": f"Совпадение с реестром: {rc}", "matched_registry_code": rc}
        if len(rc) >= 4 and code[:4] == rc[:4]:
            return {"hs_match": "partial", "detail": f"Частичное совпадение (группа {rc[:4]})", "matched_registry_code": rc}
    return {"hs_match": "mismatch", "detail": f"Код позиции {code} не найден среди ТН ВЭД реестра: {reg_norm[:8]}", "matched_registry_code": None}


def _extract_fsa_from_json(data: Any, doc_type: str, search_number: str) -> Dict[str, Any] | None:
    """Парсинг JSON-ответа API ФСА."""
    norm = normalize_number(search_number)
    if isinstance(data, dict):
        content = data.get("content") or data.get("data") or data.get("items") or []
        total = data.get("totalElements") or data.get("total")
        if isinstance(content, list):
            n = len(content)
            if total is None:
                total = n
        else:
            n = 0
        link = f"{FSA_CERT_URL if doc_type == 'СС' else FSA_DECL_URL}?q={quote(norm)}"
        if (isinstance(total, int) and total > 0) or (isinstance(content, list) and len(content) > 0):
            extra = _parse_first_fsa_record(content if isinstance(content, list) else [])
            raw: Dict[str, Any] = {"count": total if isinstance(total, int) else n}
            if extra.get("registry_tnved_codes"):
                raw["registry_tnved_codes"] = extra["registry_tnved_codes"]
            return {
                "type": doc_type,
                "status": "VALID",
                "number": norm,
                "holder": extra.get("holder"),
                "valid_from": extra.get("valid_from"),
                "valid_to": extra.get("valid_to"),
                "registry_link": link,
                "raw": raw,
            }
        return {
            "type": doc_type,
            "status": "NOT_FOUND",
            "number": norm,
            "holder": None,
            "valid_from": None,
            "valid_to": None,
            "registry_link": link,
            "raw": None,
        }
    return None


def _extract_fsa_from_html(html: str, doc_type: str, search_number: str) -> Dict[str, Any]:
    """Парсинг страницы pub.fsa.gov.ru — поиск СС или ДС."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()
    norm = normalize_number(search_number)

    # Признаки «не найдено» на ФСА
    not_found_phrases = [
        "ничего не найдено",
        "не найдено",
        "записей не найдено",
        "0 записей",
        "результатов не найдено",
    ]
    if any(p in text.lower() for p in not_found_phrases):
        return {
            "type": doc_type,
            "status": "NOT_FOUND",
            "number": norm,
            "holder": None,
            "valid_from": None,
            "valid_to": None,
            "registry_link": f"{FSA_CERT_URL if doc_type == 'СС' else FSA_DECL_URL}?q={quote(norm)}",
            "raw": None,
        }

    # Ищем таблицу с результатами (старый HTML; сейчас чаще отдаётся SPA-оболочка без таблицы)
    table = soup.find("table")
    if table:
        rows = table.find_all("tr")
        if len(rows) > 1:
            return {
                "type": doc_type,
                "status": "VALID",
                "number": norm,
                "holder": None,
                "valid_from": None,
                "valid_to": None,
                "registry_link": f"{FSA_CERT_URL if doc_type == 'СС' else FSA_DECL_URL}?q={quote(norm)}",
                "raw": {"rows_count": len(rows) - 1},
            }

    # Angular/PrimeNG: данные подгружаются в браузере; API /api/v1/... часто отвечает 403 ботам
    if "data-critters-container" in html or "ng-version" in html:
        return {
            "type": doc_type,
            "status": "UNKNOWN",
            "number": norm,
            "holder": None,
            "valid_from": None,
            "valid_to": None,
            "registry_link": f"{FSA_CERT_URL if doc_type == 'СС' else FSA_DECL_URL}?q={quote(norm)}",
            "raw": {
                "spa_shell": True,
                "note": (
                    "Сайт pub.fsa.gov.ru отдал только оболочку SPA без таблицы в HTML; "
                    "автопроверка из скрипта недоступна. Откройте registry_link в браузере "
                    "или задайте FSA_EXTERNAL_API_URL для своего прокси к API ФСА."
                ),
            },
        }

    return {
        "type": doc_type,
        "status": "UNKNOWN",
        "number": norm,
        "holder": None,
        "valid_from": None,
        "valid_to": None,
        "registry_link": f"{FSA_CERT_URL if doc_type == 'СС' else FSA_DECL_URL}?q={quote(norm)}",
        "raw": None,
    }


def _enrich_verification_record(data: Dict[str, Any], item_hs_code: str) -> Dict[str, Any]:
    """Метаданные проверки Росаккредитации и сверка ТН ВЭД."""
    out = dict(data)
    out["verified_at"] = datetime.now(timezone.utc).isoformat()
    if out.get("type") == "СГР":
        out["registry_source"] = "fp.crc.ru (Роспотребнадзор, реестр СГР)"
    else:
        out["registry_source"] = REGISTRY_SOURCE
    codes: List[str] = []
    raw = out.get("raw")
    if isinstance(raw, dict):
        codes = list(raw.get("registry_tnved_codes") or [])
    if not codes:
        _collect_tnved_from_obj(raw, codes)
    out["hs_code_check"] = match_item_hs_to_registry(item_hs_code, codes)
    return out


async def _fetch_fsa(doc_type: str, norm: str, url: str, api_url: str) -> Dict[str, Any]:
    """Общая логика запроса к ФСА: пауза, сессия, внешний API → API → HTML (с повторами)."""
    base = {
        "type": doc_type,
        "status": "UNKNOWN",
        "number": norm,
        "holder": None,
        "valid_from": None,
        "valid_to": None,
        "registry_link": f"{url}?q={quote(norm)}",
        "raw": None,
    }
    await _delay_fsa()
    # Внешний API (если настроен)
    if FSA_EXTERNAL_API:
        try:
            ext_url = f"{FSA_EXTERNAL_API}/{'declaration' if doc_type == 'ДС' else 'certificate'}"
            async with httpx.AsyncClient(timeout=15.0, verify=HTTP_VERIFY_SSL) as client:
                r = await client.get(ext_url, params={"number": norm, "q": norm})
            if r.status_code == 200:
                parsed = _extract_fsa_from_json(r.json(), doc_type, norm)
                if parsed:
                    return parsed
        except Exception as e:
            logger.debug(f"FSA external API: {e}")

    api_headers = {
        **BROWSER_HEADERS,
        "Accept": "application/json",
        "Referer": f"{url}",
        "Origin": "https://pub.fsa.gov.ru",
    }

    last_err: Exception | None = None
    for attempt in range(max(1, FSA_RETRIES)):
        try:
            async with httpx.AsyncClient(
                timeout=25.0, follow_redirects=True, verify=HTTP_VERIFY_SSL
            ) as client:
                await client.get(url, headers=BROWSER_HEADERS)
                await asyncio.sleep(0.5)
                r = await client.get(api_url, params={"number": norm, "size": 10}, headers=api_headers)
                if r.status_code == 200 and "application/json" in r.headers.get("content-type", ""):
                    parsed = _extract_fsa_from_json(r.json(), doc_type, norm)
                    if parsed:
                        return parsed
                r2 = await client.get(f"{url}?q={quote(norm)}", headers=BROWSER_HEADERS)
                r2.raise_for_status()
                return _extract_fsa_from_html(r2.text, doc_type, norm)
        except Exception as e:
            last_err = e
            logger.warning(f"ФСА {doc_type} {norm} попытка {attempt + 1}/{FSA_RETRIES}: {e}")
            await asyncio.sleep(1.2 * (attempt + 1))

    if last_err:
        logger.warning(f"ФСА {doc_type} {norm}: исчерпаны попытки: {last_err}")
    return base


async def check_certificate(number: str) -> Dict[str, Any]:
    """Проверка сертификата соответствия (СС) в реестре ФСА pub.fsa.gov.ru."""
    norm = normalize_number(number)
    if not norm:
        return {"type": "СС", "status": "UNKNOWN", "number": number, "error": "Пустой номер"}

    cache_key = f"СС:{norm}"
    mem = await cache_get(PERMITS_PREFIX, cache_key)
    if mem is not None:
        return mem

    data = await _fetch_fsa("СС", norm, FSA_CERT_URL, FSA_API_CERT)
    logger.info(f"СС {norm}: {data['status']}")
    await cache_set(PERMITS_PREFIX, cache_key, data, _PERMITS_TTL)
    return data


async def check_declaration(number: str) -> Dict[str, Any]:
    """Проверка декларации о соответствии (ДС) в реестре ФСА pub.fsa.gov.ru."""
    norm = normalize_number(number)
    if not norm:
        return {"type": "ДС", "status": "UNKNOWN", "number": number, "error": "Пустой номер"}

    cache_key = f"ДС:{norm}"
    mem = await cache_get(PERMITS_PREFIX, cache_key)
    if mem is not None:
        return mem

    data = await _fetch_fsa("ДС", norm, FSA_DECL_URL, FSA_API_DECL)
    logger.info(f"ДС {norm}: {data['status']}")
    await cache_set(PERMITS_PREFIX, cache_key, data, _PERMITS_TTL)
    return data


async def check_sgr(number: str) -> Dict[str, Any]:
    """Проверка СГР в реестре Роспотребнадзора fp.crc.ru."""
    norm = normalize_number(number)
    if not norm:
        return {"type": "СГР", "status": "UNKNOWN", "number": number, "error": "Пустой номер"}

    cache_key = f"СГР:{norm}"
    mem = await cache_get(PERMITS_PREFIX, cache_key)
    if mem is not None:
        return mem

    base = {
        "type": "СГР",
        "status": "UNKNOWN",
        "number": norm,
        "holder": None,
        "valid_from": None,
        "valid_to": None,
        "registry_link": f"{SGR_SEARCH_URL}?oper=s&text_svid={quote(norm)}&type=max",
        "raw": None,
    }

    try:
        async with httpx.AsyncClient(
            timeout=15.0, follow_redirects=True, headers=BROWSER_HEADERS, verify=HTTP_VERIFY_SSL
        ) as client:
            resp = await client.get(f"{SGR_SEARCH_URL}?oper=s&text_svid={quote(norm)}&type=max")
        resp.raise_for_status()
        data = _extract_sgr_from_html(resp.text, norm)
        logger.info(f"СГР {norm}: {data['status']}")
    except Exception as e:
        logger.warning(f"СГР fp.crc.ru {norm}: {e}")
        data = base

    await cache_set(PERMITS_PREFIX, cache_key, data, _PERMITS_TTL)
    return data


async def clear_permits_cache() -> None:
    """Сброс кэша ответов ФСА/СГР (тесты, админ)."""
    from .cache_layer import purge_prefix

    await purge_prefix(PERMITS_PREFIX)


async def check_permits(
    permits: List[Dict[str, str]],
    item_hs_code: str = "",
    *,
    enrich: bool = True,
) -> List[Dict[str, Any]]:
    """Унифицированная проверка списка документов в реестрах ФСА / СГР."""
    try:
        from .permits_metrics import record_verify_batch

        record_verify_batch(len(permits))
    except Exception:
        pass
    results: List[Dict[str, Any]] = []
    for p in permits:
        p_type = (p.get("type") or "").strip().upper()
        number = (p.get("number") or "").strip()
        if p_type in ("СС", "СЕРТИФИКАТ"):
            row = await check_certificate(number)
        elif p_type in ("ДС", "ДЕКЛАРАЦИЯ"):
            row = await check_declaration(number)
        elif p_type in ("СГР",):
            row = await check_sgr(number)
        else:
            row = {
                "type": p_type or "UNKNOWN",
                "status": "UNKNOWN",
                "number": number,
                "error": "Неизвестный тип документа",
            }
        if enrich:
            row = _enrich_verification_record(row, item_hs_code)
        else:
            row = dict(row)
        results.append(row)
    return results
