"""Парсер PDF ЕТТ ЕАЭС с сайта ЕЭК.

Источник: https://eec.eaeunion.org/comission/department/catr/ett/
Формат: PDF по группам (ru.01_2022.pdf, ru.02_2022.pdf, ...)
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from .normative_store import normalize_hs_duty_rate_string

try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # type: ignore

EEC_ETT_INDEX = "https://eec.eaeunion.org/comission/department/catr/ett/"
EEC_ETT_BASE = "https://eec.eaeunion.org"


def _normalize_hs(code: str) -> str | None:
    """Нормализация кода ТН ВЭД до 10 цифр."""
    if not code:
        return None
    digits = re.sub(r"[^\d]", "", code)
    if len(digits) == 10 and digits.isdigit():
        return digits
    if len(digits) >= 4:
        return (digits + "000000")[:10]
    return None


def _extract_duty_from_line(line: str) -> str:
    """Извлечь формулировку ставки пошлины из строки PDF (нормализованная строка для БД)."""
    m = re.search(r"(\d+[,.]?\d*)\s*%", line)
    if m:
        return normalize_hs_duty_rate_string(m.group(1).replace(",", ".") + "%")
    numbers = re.findall(r"\b(\d+(?:[.,]\d+)?)\b", line)
    if numbers:
        return normalize_hs_duty_rate_string(numbers[-1].replace(",", "."))
    return "0"


def _extract_vat_from_line(line: str) -> float:
    """Извлечь ставку НДС из строки. По умолчанию 22%."""
    m = re.search(r"НДС[:\s]*(\d+(?:[.,]\d+)?)\s*%?", line, re.I)
    if m:
        return float(m.group(1).replace(",", "."))
    return 22.0


def _parse_pdf_text(text: str) -> list[dict[str, Any]]:
    """Извлечь тарифные записи из текста PDF."""
    records: list[dict[str, Any]] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Код ТН ВЭД: 4 цифры + пробел + 2 цифры + пробел + 3 цифры + пробел + 1 цифра
        m = re.search(r"(\d{4}\s+\d{2}\s+\d{3}\s+\d{1})", line)
        if not m:
            m = re.search(r"(\d{4}\s*\d{2}\s*\d{3}\s*\d{1})", line)
        if not m:
            continue
        hs = _normalize_hs(m.group(1))
        if not hs:
            continue
        duty = _extract_duty_from_line(line)
        vat = _extract_vat_from_line(line)
        records.append({
            "hs_code": hs,
            "hs_prefix": hs[:4],
            "duty_rate": duty,
            "vat_import_rate": vat,
            "vat_rule": "none",
            "vat_rule_basis": "НК РФ ст. 164 п. 3 (общая ставка 22%)" if vat >= 22 else "",
            "excise_type": "none",
            "excise_value": 0.0,
            "has_antidumping": False,
            "source_url": EEC_ETT_INDEX,
            "source_revision": "ett-pdf",
        })
    return records


async def _fetch_pdf_links() -> list[str]:
    """Получить список URL PDF-файлов ЕТТ со страницы ЕЭК."""
    urls: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            r = await client.get(EEC_ETT_INDEX)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "ru." in href and ".pdf" in href.lower():
                full = urljoin(EEC_ETT_BASE, href)
                if full not in urls:
                    urls.append(full)
    except Exception as e:
        logger.warning(f"Fetch ETT index failed: {e}")
    return urls


def _parse_table_to_records(table: list[list[str]]) -> list[dict[str, Any]]:
    """Извлечь записи из таблицы PDF (колонки: код, описание, ставка...)."""
    records: list[dict[str, Any]] = []
    for row in table:
        line = " ".join(str(c or "") for c in row)
        recs = _parse_pdf_text(line)
        records.extend(recs)
    return records


async def parse_ett_pdf_from_url(pdf_url: str) -> list[dict[str, Any]]:
    """Загрузить PDF по URL и извлечь тарифные записи (текст + таблицы)."""
    if not pdfplumber:
        logger.warning("pdfplumber not installed, skipping PDF parse")
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            r = await client.get(pdf_url)
        r.raise_for_status()
        import io
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    for rec in _parse_pdf_text(text):
                        key = rec.get("hs_code", "")
                        if key and key not in seen:
                            seen.add(key)
                            records.append(rec)
                # Дополнительно: таблицы (ЕЭК PDF часто в табличном виде)
                tables = page.extract_tables()
                for table in tables or []:
                    for rec in _parse_table_to_records(table):
                        key = rec.get("hs_code", "")
                        if key and key not in seen:
                            seen.add(key)
                            records.append(rec)
    except Exception as e:
        logger.warning(f"Parse PDF {pdf_url}: {e}")
    return records


async def sync_ett_from_pdfs(max_groups: int = 5) -> dict[str, Any]:
    """Синхронизация ЕТТ из PDF-файлов ЕЭК.

    max_groups: ограничение числа групп для первой загрузки (для теста).
    Установите 0 или большое число для полной загрузки.
    """
    if not pdfplumber:
        return {"status": "SKIPPED", "source": "ETT_PDF", "note": "pdfplumber not installed"}

    links = await _fetch_pdf_links()
    if not links:
        return {"status": "ERROR", "source": "ETT_PDF", "error": "No PDF links found", "rows": 0}

    if max_groups > 0:
        links = links[:max_groups]  # 0 = без ограничения

    from .normative_store import upsert_hs_rate, append_sync_log, upsert_source_status

    total = 0
    seen: set[str] = set()
    for url in links:
        rows = await parse_ett_pdf_from_url(url)
        for r in rows:
            key = r.get("hs_code") or r.get("hs_prefix", "")
            if key and key not in seen:
                seen.add(key)
                upsert_hs_rate(r)
                total += 1

    revision = f"ett-pdf-{len(links)}gr-{total}rows"
    upsert_source_status(
        source_code="EEC_ETT_PDF",
        source_name="ЕТТ ЕАЭС (парсинг PDF)",
        source_url=EEC_ETT_INDEX,
        revision=revision,
        is_stale=False,
        note=f"Загружено из {len(links)} PDF, импортировано {total} записей",
    )
    append_sync_log(
        source_code="EEC_ETT_PDF",
        status="OK",
        revision=revision,
        rows_affected=total,
        note=f"PDF sync: {len(links)} files, {total} rows",
    )
    return {"status": "OK", "source": "ETT_PDF", "rows": total, "files": len(links), "revision": revision}
