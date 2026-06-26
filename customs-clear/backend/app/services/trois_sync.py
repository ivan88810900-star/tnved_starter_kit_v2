from __future__ import annotations

import os
import re
import random
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from sqlalchemy import text

from ..db import SessionLocal
from ..models.tnved import IntellectualProperty
from .normative_store import append_sync_log, upsert_source_status

ALTA_ROIS_URL = os.getenv("TROIS_ALTA_URL", "https://www.alta.ru/rois/all/").strip()
CUSTOMS_ROIS_URL = os.getenv(
    "TROIS_CUSTOMS_URL",
    "https://customs.gov.ru/registers/objects-intellectual-property",
).strip()
TROIS_TIMEOUT = float(os.getenv("TROIS_SYNC_TIMEOUT", "40") or "40")
TROIS_HTTP_RETRIES = int(os.getenv("TROIS_SYNC_HTTP_RETRIES", "3") or "3")
TROIS_RETRY_BACKOFF = float(os.getenv("TROIS_SYNC_RETRY_BACKOFF", "1.2") or "1.2")
TROIS_PROXY = (os.getenv("TROIS_PROXY") or "").strip()


@dataclass(frozen=True)
class TroisRecord:
    brand_name: str
    hs_code_prefix: str
    reg_number: str
    right_holder: str


def _clean_text(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "")).strip()


def _normalize_prefix(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) >= 6:
        return digits[:6]
    if len(digits) >= 4:
        return digits[:4]
    return ""


def _extract_hs_codes_from_block(block: str) -> list[str]:
    codes: list[str] = []
    # 1) Предпочтительно: строка после "Класс товаров ... / Код товаров по ТН ВЭД".
    lines = block.splitlines()
    for i, ln in enumerate(lines):
        if re.search(r"код\s+товар[^\n]*тн\s*вэд", ln, flags=re.IGNORECASE):
            window = "\n".join(lines[i + 1 : i + 6])
            for m in re.finditer(r"(?<!\d)(\d{4,10})(?!\d)", window):
                pref = _normalize_prefix(m.group(1))
                if pref and pref not in codes:
                    codes.append(pref)
            if codes:
                return codes

    # 2) Fallback: если нет явной секции, берём коды только после слэша (формат "класс / коды").
    candidates: list[str] = []
    for ln in lines:
        if "/" not in ln:
            continue
        rhs = ln.split("/", 1)[1]
        candidates.extend(re.findall(r"(?<!\d)(\d{4,10})(?!\d)", rhs))

    # 3) Последний fallback — ограниченный участок вокруг фразы "Код товаров".
    if not candidates:
        mark = re.search(r"код\s+товар[^\n]*тн\s*вэд[^\n]*", block, flags=re.IGNORECASE)
        if mark:
            code_area = block[mark.start() : mark.start() + 500]
            candidates.extend(re.findall(r"(?<!\d)(\d{4,10})(?!\d)", code_area))

    out: list[str] = []
    for c in candidates:
        # Отсекаем служебные числа и даты.
        if c.startswith("0000"):
            continue
        pref = _normalize_prefix(c)
        if pref and pref not in out:
            out.append(pref)
    return out


def _extract_blocks_from_alta_markdown(text: str) -> list[tuple[str, str]]:
    marker = re.compile(r"^\s*([^\n|]{2,120}?)\s+подробнее\s*$", flags=re.IGNORECASE | re.MULTILINE)
    matches = list(marker.finditer(text or ""))
    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        brand = _clean_text(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text or "")
        block = (text or "")[start:end]
        if brand and block.strip():
            blocks.append((brand, block))
    return blocks


def _parse_records_from_alta_markdown(text: str) -> list[TroisRecord]:
    records: list[TroisRecord] = []
    for brand, block in _extract_blocks_from_alta_markdown(text):
        reg_match = re.search(r"\b\d{5}/[0-9A-Za-zА-Яа-я\-\/]+", block)
        reg_number = _clean_text(reg_match.group(0)) if reg_match else ""
        right_holder_match = re.search(
            r"правообладател[ья]\s*[:\-]?\s*([^\n,|]{3,200})",
            block,
            flags=re.IGNORECASE,
        )
        right_holder = _clean_text(right_holder_match.group(1)) if right_holder_match else "Источник: alta.ru"
        hs_codes = _extract_hs_codes_from_block(block)
        for pref in hs_codes:
            records.append(
                TroisRecord(
                    brand_name=brand,
                    hs_code_prefix=pref,
                    reg_number=reg_number,
                    right_holder=right_holder,
                )
            )
    return records


def _extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    root = soup.select_one("main") or soup.select_one("article") or soup.body or soup
    return _clean_text(root.get_text("\n", strip=True))


def _parse_records_from_customs_text(text: str) -> list[TroisRecord]:
    # Универсальный fallback-парсер для неструктурированного текста ФТС.
    records: list[TroisRecord] = []
    chunks = re.split(r"(?:\n|^)([A-ZА-Я0-9][A-ZА-Я0-9&'\"()./\- ]{2,80})(?:\n|$)", text or "")
    if len(chunks) < 3:
        return records
    # chunks: [pre, brand1, body1, brand2, body2, ...]
    for i in range(1, len(chunks), 2):
        brand = _clean_text(chunks[i])
        body = chunks[i + 1] if i + 1 < len(chunks) else ""
        if not brand:
            continue
        reg_match = re.search(r"\b\d{5}/[0-9A-Za-zА-Яа-я\-\/]+", body)
        reg_number = _clean_text(reg_match.group(0)) if reg_match else ""
        hs_codes = _extract_hs_codes_from_block(body)
        for pref in hs_codes:
            records.append(
                TroisRecord(
                    brand_name=brand,
                    hs_code_prefix=pref,
                    reg_number=reg_number,
                    right_holder="Источник: customs.gov.ru",
                )
            )
    return records


def _http_headers() -> dict[str, str]:
    uas = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    )
    return {
        "User-Agent": random.choice(uas),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }


async def _retry_sleep(attempt: int) -> None:
    base = TROIS_RETRY_BACKOFF * (2 ** max(0, attempt - 1))
    await asyncio.sleep(min(8.0, base + random.uniform(0.1, 0.8)))


async def _fetch_url(url: str, *, proxy: str = "") -> str:
    timeout_cfg = httpx.Timeout(
        connect=min(TROIS_TIMEOUT, 20.0),
        read=TROIS_TIMEOUT,
        write=TROIS_TIMEOUT,
        pool=min(TROIS_TIMEOUT, 10.0),
    )
    client_kwargs: dict[str, Any] = {
        "timeout": timeout_cfg,
        "follow_redirects": True,
    }
    p = (proxy or TROIS_PROXY or "").strip()
    if p:
        client_kwargs["proxy"] = p
    async with httpx.AsyncClient(**client_kwargs) as client:
        for attempt in range(1, max(1, TROIS_HTTP_RETRIES) + 1):
            try:
                resp = await client.get(url, headers=_http_headers())
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < TROIS_HTTP_RETRIES:
                    logger.warning(
                        "TROIS sync: retry {} for {} (status={})",
                        attempt,
                        url,
                        resp.status_code,
                    )
                    await _retry_sleep(attempt)
                    continue
                resp.raise_for_status()
                return resp.text
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if attempt >= TROIS_HTTP_RETRIES:
                    raise
                logger.warning("TROIS sync: network retry {} for {} ({})", attempt, url, exc)
                await _retry_sleep(attempt)


def _load_fallback_text(path: str | None) -> str:
    if not path:
        return ""
    fp = Path(path).expanduser()
    if not fp.exists():
        return ""
    try:
        return fp.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _upsert_records(records: list[TroisRecord]) -> dict[str, int]:
    created = 0
    updated = 0
    skipped = 0
    with SessionLocal() as db:
        valid_prefixes = {
            p
            for (p,) in db.execute(text("SELECT DISTINCT substr(code,1,4) FROM tnved_commodities")).fetchall()
            if p
        }
        valid_prefixes.update(
            {
                p
                for (p,) in db.execute(text("SELECT DISTINCT substr(code,1,6) FROM tnved_commodities")).fetchall()
                if p
            }
        )
        for r in records:
            brand = _clean_text(r.brand_name)
            pref = _normalize_prefix(r.hs_code_prefix)
            if not brand or not pref or pref not in valid_prefixes:
                skipped += 1
                continue
            row = (
                db.query(IntellectualProperty)
                .filter(
                    IntellectualProperty.brand_name == brand,
                    IntellectualProperty.hs_code_prefix == pref,
                    IntellectualProperty.reg_number == _clean_text(r.reg_number),
                )
                .first()
            )
            if row:
                row.right_holder = _clean_text(r.right_holder)
                updated += 1
            else:
                db.add(
                    IntellectualProperty(
                        brand_name=brand,
                        hs_code_prefix=pref,
                        reg_number=_clean_text(r.reg_number),
                        right_holder=_clean_text(r.right_holder),
                    )
                )
                created += 1
        db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


async def sync_trois_sources(*, proxy: str = "") -> dict[str, Any]:
    total_records: list[TroisRecord] = []
    source_errors: list[str] = []

    # 1) Alta
    alta_text = ""
    try:
        alta_text = await _fetch_url(ALTA_ROIS_URL, proxy=proxy)
        if "<html" in alta_text.lower():
            alta_text = _extract_text_from_html(alta_text)
    except Exception as exc:
        source_errors.append(f"alta: {exc}")
        fallback = _load_fallback_text(os.getenv("TROIS_ALTA_FALLBACK_FILE", "").strip())
        if fallback:
            alta_text = fallback
            logger.warning("TROIS sync: alta fallback file used")
    if alta_text:
        total_records.extend(_parse_records_from_alta_markdown(alta_text))

    # 2) Customs
    customs_text = ""
    try:
        customs_html = await _fetch_url(CUSTOMS_ROIS_URL, proxy=proxy)
        customs_text = _extract_text_from_html(customs_html)
    except Exception as exc:
        source_errors.append(f"customs: {exc}")
        fallback = _load_fallback_text(os.getenv("TROIS_CUSTOMS_FALLBACK_FILE", "").strip())
        if fallback:
            customs_text = fallback
            logger.warning("TROIS sync: customs fallback file used")
    if customs_text:
        total_records.extend(_parse_records_from_customs_text(customs_text))

    # Убираем дубли перед upsert.
    uniq: dict[tuple[str, str, str], TroisRecord] = {}
    for r in total_records:
        key = (_clean_text(r.brand_name), _normalize_prefix(r.hs_code_prefix), _clean_text(r.reg_number))
        if not key[0] or not key[1]:
            continue
        uniq[key] = r
    dedup_records = list(uniq.values())
    stats = _upsert_records(dedup_records)

    status = "OK" if dedup_records else "WARNING"
    note = {
        "parsed_records": len(total_records),
        "dedup_records": len(dedup_records),
        "errors": source_errors,
        **stats,
    }
    upsert_source_status(
        source_code="TROIS_SYNC",
        source_name="ТРОИС (alta + customs)",
        source_url=f"{ALTA_ROIS_URL} | {CUSTOMS_ROIS_URL}",
        revision=f"records:{len(dedup_records)}",
        is_stale=False if dedup_records else True,
        note=str(note),
    )
    append_sync_log(
        source_code="TROIS_SYNC",
        status=status,
        revision=f"records:{len(dedup_records)}",
        rows_affected=stats["created"] + stats["updated"],
        note=str(note),
    )
    return {"status": status, "source": "TROIS_SYNC", **note}
