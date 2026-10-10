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

_PERMITS_TTL = int(os.getenv("PERMITS_CACHE_TTL_SECONDS", "86400"))  # 24h default (#151)

PERMITS_DISCLAIMER_RU = (
    "Система определяет **необходимость** разрешительного документа по ТН ВЭД и ТР ТС, "
    "но не подтверждает наличие конкретного сертификата у импортёра. "
    "Проверка номера выполняется через реестр ФСА; при недоступности реестра используйте ссылку для ручной проверки."
)

FSA_SEARCH_CERT_URL = "https://pub.fsa.gov.ru/rss/certificate"
FSA_SEARCH_DECL_URL = "https://pub.fsa.gov.ru/rds/declaration"

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


def build_fsa_manual_link(doc_type: str, number: str) -> str:
    """Прямая ссылка для ручной проверки в браузере."""
    norm = normalize_number(number)
    base = FSA_SEARCH_CERT_URL if doc_type == "СС" else FSA_SEARCH_DECL_URL
    return f"{base}?page=1&size=10&filter={quote(norm)}"


def infer_doc_type_from_number(number: str) -> str:
    """Эвристика типа документа по номеру."""
    n = (number or "").upper()
    if n.startswith("Д-") or n.startswith("D-"):
        return "ДС"
    if "ДС" in n and "СС" not in n:
        return "ДС"
    return "СС"


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


_REGISTRY_PREFIXES = ("ЕАЭС", "EAEU", "РОСС", "ВП")


def canonical_cert_number(raw: str) -> str:
    """Канонический хвост номера без префиксов opendata (ЕАЭС/РОСС/ВП)."""
    s = normalize_number(raw)
    if not s:
        return ""
    for prefix in _REGISTRY_PREFIXES:
        if s.startswith(prefix):
            return s[len(prefix) :]
    return s


def cert_number_search_variants(raw: str) -> list[str]:
    """Варианты registry_number для поиска в fsa_certificates."""
    base = normalize_number(raw)
    if not base:
        return []
    variants: set[str] = {base}
    core = canonical_cert_number(raw)
    if core:
        variants.add(core)
        for prefix in _REGISTRY_PREFIXES:
            variants.add(f"{prefix}{core}")
    return list(variants)


def _parse_registry_date(value: str) -> datetime | None:
    raw = (value or "").strip()
    for fmt in ("%d.%m.%Y", "%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:10], fmt)
        except ValueError:
            continue
    return None


def _registry_status_to_verify(status: str, expiry: str) -> str:
    """Map only explicit registry state to a verification result.

    An unrecognised or missing status is evidence for manual review, never
    proof that the document is active.
    """
    st = " ".join((status or "").strip().lower().split())
    if any(
        marker in st
        for marker in (
            "недейств",
            "не действ",
            "прекращ",
            "аннулир",
            "отозван",
            "приостанов",
            "revoked",
            "withdrawn",
            "suspended",
            "terminated",
            "expired",
            "inactive",
            "not active",
            "not valid",
            "not registered",
            "не зарегистрирован",
            "незарегистрирован",
        )
    ):
        return "NOT_FOUND"
    exp = _parse_registry_date(expiry)
    if exp and exp.date() < datetime.now().date():
        return "NOT_FOUND"
    if any(marker in st for marker in ("действует", "действующий", "зарегистрирован")):
        return "VALID"
    if {"active", "valid", "registered"}.intersection(re.findall(r"[a-z]+", st)):
        return "VALID"
    return "UNKNOWN"


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


def _parse_fsa_record(row: Any) -> Dict[str, Any]:
    """Извлекает проверяемые поля из одной записи API ФСА."""
    if not isinstance(row, dict):
        return {}
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


def _parse_first_fsa_record(content: list[Any]) -> Dict[str, Any]:
    """Обратная совместимость для callers, читающих первую запись."""
    return _parse_fsa_record(content[0] if content else None)


_FSA_NUMBER_KEYS = (
    "registryNumber",
    "certificateNumber",
    "declarationNumber",
    "documentNumber",
    "regNumber",
)


def _fsa_record_number(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    for key in _FSA_NUMBER_KEYS:
        value = row.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value)
    return ""


def _fsa_record_status(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    value: Any = (
        row.get("status")
        or row.get("statusName")
        or row.get("documentStatus")
        or row.get("state")
    )
    if isinstance(value, dict):
        value = value.get("name") or value.get("title") or value.get("label") or value.get("value")
    return str(value).strip() if isinstance(value, (str, int)) else ""


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
        content = data.get("content")
        if content is None:
            content = data.get("data")
        if content is None:
            content = data.get("items")
        if content is None:
            content = []
        total = data.get("totalElements")
        if total is None:
            total = data.get("total")
        if isinstance(content, list):
            n = len(content)
            if total is None:
                total = n
        else:
            n = 0
        link = f"{FSA_CERT_URL if doc_type == 'СС' else FSA_DECL_URL}?q={quote(norm)}"
        rows = [row for row in content if isinstance(row, dict)] if isinstance(content, list) else []
        requested = canonical_cert_number(norm)
        numbered_rows = [(row, _fsa_record_number(row)) for row in rows]
        numbered_rows = [(row, number) for row, number in numbered_rows if number]
        matched_rows = [
            row
            for row, number in numbered_rows
            if canonical_cert_number(number) == requested
        ]
        fully_numbered = bool(rows) and len(numbered_rows) == len(rows) == n
        raw: Dict[str, Any] = {
            "count": total if isinstance(total, int) else n,
            "identity_match": True if matched_rows else (False if fully_numbered else None),
        }
        if matched_rows:
            extra = _parse_fsa_record(matched_rows[0])
            registry_statuses = [_fsa_record_status(row) for row in matched_rows]
            verify_statuses = [
                _registry_status_to_verify(
                    status, str(_parse_fsa_record(row).get("valid_to") or "")
                )
                for row, status in zip(matched_rows, registry_statuses)
            ]
            if "NOT_FOUND" in verify_statuses:
                verify_status = "NOT_FOUND"
            elif verify_statuses and all(status == "VALID" for status in verify_statuses):
                verify_status = "VALID"
            else:
                verify_status = "UNKNOWN"
            raw["matched_number"] = normalize_number(_fsa_record_number(matched_rows[0]))
            raw["matched_count"] = len(matched_rows)
            raw["registry_status"] = registry_statuses[0] or None
            if len(matched_rows) > 1:
                raw["registry_statuses"] = [status or None for status in registry_statuses]
            if extra.get("registry_tnved_codes"):
                raw["registry_tnved_codes"] = extra["registry_tnved_codes"]
            return {
                "type": doc_type,
                "status": verify_status,
                "number": norm,
                "holder": extra.get("holder"),
                "valid_from": extra.get("valid_from"),
                "valid_to": extra.get("valid_to"),
                "registry_link": link,
                "raw": raw,
            }
        if rows or (isinstance(total, int) and total > 0):
            if numbered_rows:
                raw["candidate_numbers"] = [
                    normalize_number(number) for _, number in numbered_rows[:10]
                ]
            return {
                "type": doc_type,
                "status": "NOT_FOUND" if fully_numbered else "UNKNOWN",
                "number": norm,
                "holder": None,
                "valid_from": None,
                "valid_to": None,
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

    # Признаки «не найдено» учитываются только после разбора таблиц: справочный
    # текст страницы не должен перекрывать точную запись и удалять evidence.
    not_found_phrases = [
        "ничего не найдено",
        "не найдено",
        "записей не найдено",
        "0 записей",
        "результатов не найдено",
    ]
    not_found_text = any(p in text.lower() for p in not_found_phrases)
    registry_link = (
        f"{FSA_CERT_URL if doc_type == 'СС' else FSA_DECL_URL}?q={quote(norm)}"
    )

    # Ищем все таблицы результатов. Наличие таблицы или строки само по себе не
    # подтверждает identity/status, а rowspan/colspan делает позиционные колонки
    # неоднозначными и потому не может участвовать в автоматическом выводе.
    tables = soup.find_all("table")
    result_table_count = 0
    result_row_count = 0
    recognized_row_count = 0
    incomplete_rows = 0
    candidates: list[dict[str, str]] = []

    def _span_is_one(cell: Any, name: str) -> bool:
        value = str(cell.get(name, "1") or "1").strip()
        return value == "1"

    def _header_is_number(header: str) -> bool:
        if any(marker in header for marker in ("запрос", "request", "поиска", "search")):
            return False
        return header.strip(" :") in {
            "регистрационный номер",
            "регистрационный номер документа",
            "регистрационный номер сертификата",
            "регистрационный номер декларации",
            "номер документа",
            "номер сертификата",
            "номер декларации",
            "registration number",
            "document registration number",
            "certificate number",
            "declaration number",
        }

    def _header_looks_like_number(header: str) -> bool:
        if any(
            marker in header
            for marker in ("запрос", "request", "поиска", "search", "организац", "organization")
        ):
            return False
        return any(
            marker in header
            for marker in (
                "регистрационный номер",
                "номер документа",
                "номер сертификата",
                "номер декларации",
                "registration number",
                "certificate number",
                "declaration number",
            )
        )

    def _header_is_status(header: str) -> bool:
        if any(marker in header for marker in ("запрос", "request", "поиска", "search")):
            return False
        return header in {"статус", "состояние", "status", "статус документа"}

    def _header_is_expiry(header: str) -> bool:
        return any(
            marker in header
            for marker in ("действует до", "срок действия", "expiry", "expiration", "valid to")
        )

    for table in tables:
        table_rows = table.find_all("tr")
        if not table_rows:
            continue
        result_row_count += max(0, len(table_rows) - 1)
        header_cells = table_rows[0].find_all(["th", "td"], recursive=False)
        headers = [
            " ".join(cell.get_text(" ", strip=True).lower().split())
            for cell in header_cells
        ]
        looks_like_result = any(_header_looks_like_number(header) for header in headers)
        if not header_cells or not all(
            _span_is_one(cell, "rowspan") and _span_is_one(cell, "colspan")
            for cell in header_cells
        ):
            if looks_like_result:
                data_count = max(0, len(table_rows) - 1)
                result_table_count += 1
                recognized_row_count += data_count
                incomplete_rows += data_count
            continue
        number_indexes = [idx for idx, header in enumerate(headers) if _header_is_number(header)]
        if len(number_indexes) != 1:
            if looks_like_result:
                data_count = max(0, len(table_rows) - 1)
                result_table_count += 1
                recognized_row_count += data_count
                incomplete_rows += data_count
            continue
        result_table_count += 1
        number_idx = number_indexes[0]
        status_indexes = [idx for idx, header in enumerate(headers) if _header_is_status(header)]
        expiry_indexes = [idx for idx, header in enumerate(headers) if _header_is_expiry(header)]
        status_idx = status_indexes[0] if len(status_indexes) == 1 else None
        expiry_idx = expiry_indexes[0] if len(expiry_indexes) == 1 else None
        indexes_complete = (
            status_idx is not None
            and expiry_idx is not None
            and len({number_idx, status_idx, expiry_idx}) == 3
        )

        for row in table_rows[1:]:
            recognized_row_count += 1
            cells = row.find_all("td", recursive=False)
            if not cells:
                incomplete_rows += 1
                continue
            flat = len(cells) == len(header_cells) and all(
                _span_is_one(cell, "rowspan") and _span_is_one(cell, "colspan")
                for cell in cells
            )
            if not flat or not indexes_complete:
                incomplete_rows += 1
                continue
            number = cells[number_idx].get_text(" ", strip=True)
            status = cells[status_idx].get_text(" ", strip=True)
            expiry = cells[expiry_idx].get_text(" ", strip=True)
            if not number:
                incomplete_rows += 1
                continue
            candidates.append({"number": number, "status": status, "expiry": expiry})

    matched = [
        candidate
        for candidate in candidates
        if canonical_cert_number(candidate["number"]) == canonical_cert_number(norm)
    ]
    fully_numbered = bool(candidates) and incomplete_rows == 0
    raw: Dict[str, Any] = {
        "tables_count": len(tables),
        "result_tables_count": result_table_count,
        "rows_count": result_row_count,
        "recognized_rows_count": recognized_row_count,
        "incomplete_rows_count": incomplete_rows,
        "identity_match": True if matched else (False if fully_numbered else None),
    }
    if candidates:
        raw["candidate_numbers"] = [
            normalize_number(candidate["number"]) for candidate in candidates[:10]
        ]
    if matched:
        statuses = [candidate["status"] for candidate in matched]
        expiries = [candidate["expiry"] for candidate in matched]
        verify_statuses = [
            (
                _registry_status_to_verify(candidate["status"], candidate["expiry"])
                if _parse_registry_date(candidate["expiry"])
                else (
                    "NOT_FOUND"
                    if _registry_status_to_verify(candidate["status"], "") == "NOT_FOUND"
                    else "UNKNOWN"
                )
            )
            for candidate in matched
        ]
        if "NOT_FOUND" in verify_statuses:
            verify_status = "NOT_FOUND"
        elif (
            incomplete_rows == 0
            and verify_statuses
            and all(status == "VALID" for status in verify_statuses)
        ):
            verify_status = "VALID"
        else:
            verify_status = "UNKNOWN"
        raw["matched_count"] = len(matched)
        raw["registry_status"] = statuses[0] or None
        raw["registry_valid_to"] = expiries[0] or None
        if len(matched) > 1:
            raw["registry_statuses"] = [status or None for status in statuses]
            raw["registry_valid_to_values"] = [expiry or None for expiry in expiries]
        return {
            "type": doc_type,
            "status": verify_status,
            "number": norm,
            "holder": None,
            "valid_from": None,
            "valid_to": expiries[0] if len(expiries) == 1 and expiries[0] else None,
            "registry_link": registry_link,
            "raw": raw,
        }
    if result_table_count:
        if fully_numbered:
            status = "NOT_FOUND"
        elif recognized_row_count == 0 and not_found_text:
            status = "NOT_FOUND"
        else:
            status = "UNKNOWN"
        return {
            "type": doc_type,
            "status": status,
            "number": norm,
            "holder": None,
            "valid_from": None,
            "valid_to": None,
            "registry_link": registry_link,
            "raw": raw,
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

    if not_found_text:
        return {
            "type": doc_type,
            "status": "NOT_FOUND",
            "number": norm,
            "holder": None,
            "valid_from": None,
            "valid_to": None,
            "registry_link": registry_link,
            "raw": raw if tables else None,
        }

    return {
        "type": doc_type,
        "status": "UNKNOWN",
        "number": norm,
        "holder": None,
        "valid_from": None,
        "valid_to": None,
        "registry_link": f"{FSA_CERT_URL if doc_type == 'СС' else FSA_DECL_URL}?q={quote(norm)}",
        "raw": raw if tables else None,
    }


def _enrich_verification_record(data: Dict[str, Any], item_hs_code: str) -> Dict[str, Any]:
    """Метаданные проверки Росаккредитации и сверка ТН ВЭД."""
    out = dict(data)
    out["verified_at"] = datetime.now(timezone.utc).isoformat()
    if out.get("type") == "СГР":
        out["registry_source"] = "fp.crc.ru (Роспотребнадзор, реестр СГР)"
    elif out.get("source_kind") == "opendata_local":
        from .opendata_registry import OPENDATA_FSA_SOURCE

        out["registry_source"] = OPENDATA_FSA_SOURCE
        if out.get("data_as_of"):
            out["freshness_label"] = f"Проверка по реестру ФСА (данные на {out['data_as_of']})"
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
    """Общая логика запроса к ФСА: пауза, сессия, внешний API → API (filter) → HTML."""
    manual_link = build_fsa_manual_link(doc_type, norm)
    base = {
        "type": doc_type,
        "status": "UNKNOWN",
        "number": norm,
        "holder": None,
        "valid_from": None,
        "valid_to": None,
        "registry_link": manual_link,
        "manual_check_url": manual_link,
        "disclaimer": PERMITS_DISCLAIMER_RU,
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
                api_params = {"page": 1, "size": 1, "filter": norm, "number": norm}
                r = await client.get(api_url, params=api_params, headers=api_headers)
                if r.status_code == 200 and "application/json" in r.headers.get("content-type", ""):
                    parsed = _extract_fsa_from_json(r.json(), doc_type, norm)
                    if parsed:
                        parsed["manual_check_url"] = manual_link
                        parsed["disclaimer"] = PERMITS_DISCLAIMER_RU
                        return parsed
                r2 = await client.get(f"{url}?page=1&size=10&filter={quote(norm)}", headers=BROWSER_HEADERS)
                r2.raise_for_status()
                parsed_html = _extract_fsa_from_html(r2.text, doc_type, norm)
                parsed_html["manual_check_url"] = manual_link
                parsed_html["disclaimer"] = PERMITS_DISCLAIMER_RU
                return parsed_html
        except Exception as e:
            last_err = e
            logger.warning(f"ФСА {doc_type} {norm} попытка {attempt + 1}/{FSA_RETRIES}: {e}")
            await asyncio.sleep(1.2 * (attempt + 1))

    if last_err:
        logger.warning(f"ФСА {doc_type} {norm}: исчерпаны попытки: {last_err}")
    base["fallback_note"] = (
        "Реестр ФСА недоступен для автоматической проверки. "
        "Откройте manual_check_url в браузере для ручной проверки."
    )
    return base


async def check_certificate(number: str) -> Dict[str, Any]:
    """Проверка сертификата соответствия (СС): локальный opendata → реестр ФСА."""
    norm = normalize_number(number)
    if not norm:
        return {"type": "СС", "status": "UNKNOWN", "number": number, "error": "Пустой номер"}

    cache_key = f"СС:{norm}"
    mem = await cache_get(PERMITS_PREFIX, cache_key)
    if mem is not None:
        return mem

    from .opendata_registry import lookup_fsa_certificate

    local = lookup_fsa_certificate(norm, "СС")
    if local is not None:
        logger.info(f"СС {norm}: {local['status']} (opendata local)")
        await cache_set(PERMITS_PREFIX, cache_key, local, _PERMITS_TTL)
        return local

    data = await _fetch_fsa("СС", norm, FSA_CERT_URL, FSA_API_CERT)
    logger.info(f"СС {norm}: {data['status']}")
    await cache_set(PERMITS_PREFIX, cache_key, data, _PERMITS_TTL)
    return data


async def check_declaration(number: str) -> Dict[str, Any]:
    """Проверка декларации о соответствии (ДС): локальный opendata → реестр ФСА."""
    norm = normalize_number(number)
    if not norm:
        return {"type": "ДС", "status": "UNKNOWN", "number": number, "error": "Пустой номер"}

    cache_key = f"ДС:{norm}"
    mem = await cache_get(PERMITS_PREFIX, cache_key)
    if mem is not None:
        return mem

    from .opendata_registry import lookup_fsa_certificate

    local = lookup_fsa_certificate(norm, "ДС")
    if local is not None:
        logger.info(f"ДС {norm}: {local['status']} (opendata local)")
        await cache_set(PERMITS_PREFIX, cache_key, local, _PERMITS_TTL)
        return local

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
