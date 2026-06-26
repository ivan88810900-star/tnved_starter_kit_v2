"""Загрузка открытых данных ТРОИС с customs.gov.ru/folder/14344 (#151)."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from .trois_registry_sync import normalize_trademark_for_registry, upsert_trois_registry_rows

FTS_TROIS_FOLDER_URL = "https://customs.gov.ru/folder/14344"
USER_AGENT = "CustomsClear-TROIS-Fetch/1.0 (+https://github.com/ivan88810900-star/tnved_starter_kit_v2)"

# Колонки xlsx/csv (эвристика)
_TM_COLS = ("trademark", "товарный знак", "наименование", "brand", "бренд", "марка")
_HOLDER_COLS = ("right_holder", "правообладатель", "владелец", "holder")
_REG_COLS = ("reg_number", "номер", "регистрационный номер", "номер регистрации")


def _synthetic_reg_number(trademark: str) -> str:
    """Формат для upsert: 5 цифр / … (см. REG_NUMBER_RE в trois_registry_sync)."""
    h = hashlib.sha1(trademark.encode("utf-8")).hexdigest()
    digits = str(int(h[:8], 16) % 100000).zfill(5)
    slug = re.sub(r"[^A-ZА-ЯЁ0-9]+", "-", trademark.upper()).strip("-")[:60] or "TM"
    return f"{digits}/{slug}"


def _fetch_html(url: str, *, timeout: float = 45.0) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def _discover_document_links(folder_html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(folder_html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if any(ext in low for ext in (".xlsx", ".xls", ".csv", ".zip")):
            links.append(urljoin(base_url, href))
    return list(dict.fromkeys(links))


def _download_bytes(url: str) -> bytes:
    with httpx.Client(timeout=90.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.content


def _col_match(cols: list[str], candidates: tuple[str, ...]) -> int | None:
    norm = [re.sub(r"\s+", " ", c.strip().lower()) for c in cols]
    for i, c in enumerate(norm):
        for cand in candidates:
            if cand in c or c in cand:
                return i
    return None


def _parse_tabular_rows(cols: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    if not cols or not rows:
        return []
    tm_i = _col_match(cols, _TM_COLS)
    rh_i = _col_match(cols, _HOLDER_COLS)
    reg_i = _col_match(cols, _REG_COLS)
    out: list[dict[str, str]] = []
    for row in rows:
        if not row or all(not str(c).strip() for c in row):
            continue
        tm = str(row[tm_i]).strip() if tm_i is not None and tm_i < len(row) else ""
        if not tm:
            continue
        reg = str(row[reg_i]).strip() if reg_i is not None and reg_i < len(row) else ""
        tm_norm = normalize_trademark_for_registry(tm)
        if not reg or not re.match(r"^\d{5}/", reg):
            reg = _synthetic_reg_number(tm_norm)
        rh = str(row[rh_i]).strip() if rh_i is not None and rh_i < len(row) else ""
        out.append(
            {
                "trademark": tm_norm,
                "brand": tm_norm,
                "right_holder": rh,
                "reg_number": reg,
                "status": "FTS_OPEN_DATA",
                "valid_until": "",
                "representatives": "",
            }
        )
    return out


def _parse_xlsx_bytes(data: bytes) -> list[dict[str, str]]:
    import pandas as pd

    df = pd.read_excel(io.BytesIO(data), engine="openpyxl", dtype=str, keep_default_na=False)
    if df.empty:
        return []
    cols = [str(c) for c in df.columns]
    rows = [[str(v) for v in r] for r in df.values.tolist()]
    return _parse_tabular_rows(cols, rows)


def _parse_csv_bytes(data: bytes) -> list[dict[str, str]]:
    import pandas as pd

    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, sep=None, engine="python", encoding=enc)
            break
        except Exception:
            df = None
    if df is None or df.empty:
        return []
    cols = [str(c) for c in df.columns]
    rows = [[str(v) for v in r] for r in df.values.tolist()]
    return _parse_tabular_rows(cols, rows)


def fetch_fts_trois_open_data(*, folder_url: str = FTS_TROIS_FOLDER_URL) -> dict[str, Any]:
    """
    Обходит folder 14344, скачивает первый xlsx/csv и upsert в ``trois_registry``.
    При недоступности ФТС возвращает status=skipped без исключения.
    """
    result: dict[str, Any] = {"source": folder_url, "status": "OK", "parsed_rows": 0, "links_found": []}
    try:
        html = _fetch_html(folder_url)
    except Exception as exc:
        logger.warning("FTS TROIS folder fetch failed: {}", exc)
        result["status"] = "skipped"
        result["error"] = str(exc)
        return result

    links = _discover_document_links(html, folder_url)
    result["links_found"] = links[:10]
    if not links:
        result["status"] = "no_files"
        result["note"] = "На странице folder/14344 не найдены xlsx/csv ссылки"
        return result

    all_rows: list[dict[str, str]] = []
    for link in links[:3]:
        try:
            raw = _download_bytes(link)
            low = link.lower()
            if low.endswith((".xlsx", ".xls", ".xlsm")):
                rows = _parse_xlsx_bytes(raw)
            elif low.endswith(".csv"):
                rows = _parse_csv_bytes(raw)
            else:
                continue
            all_rows.extend(rows)
            result["downloaded_from"] = link
            if rows:
                break
        except Exception as exc:
            logger.warning("FTS TROIS parse {}: {}", link, exc)
            continue

    result["parsed_rows"] = len(all_rows)
    if not all_rows:
        result["status"] = "parse_empty"
        return result

    stats = upsert_trois_registry_rows(all_rows)
    result.update(stats)
    return result
