"""Парсинг реестра ТРОИС (alta.ru/rois/all/) и upsert в таблицу ``trois_registry``."""

from __future__ import annotations

import random
import os
import re
import time
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from loguru import logger
from ..db import SessionLocal
from ..models.tnved import TroisRegistry

DEFAULT_ALTA_URL = "https://www.alta.ru/rois/all/"
REQUEST_TIMEOUT = float(os.getenv("TROIS_ALTA_TIMEOUT", "90") or "90")
MAX_PAGES = int(os.getenv("TROIS_ALTA_MAX_PAGES", "30") or "30")
HTTP_RETRIES = int(os.getenv("TROIS_ALTA_HTTP_RETRIES", "3") or "3")
HTTP_BACKOFF_BASE_SEC = float(os.getenv("TROIS_ALTA_RETRY_BACKOFF", "1.2") or "1.2")
HTTP_UAS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)

REG_NUMBER_RE = re.compile(r"^\s*\d{5}/")


def normalize_trademark_for_registry(raw: str) -> str:
    """UPPERCASE, сжатие пробелов, снятие лишних кавычек."""
    s = (raw or "").strip()
    for ch in ('"', "'", "«", "»", "“", "”"):
        s = s.replace(ch, "")
    s = re.sub(r"\s+", " ", s).strip()
    return s.upper()


def _clean_cell(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _retry_sleep(attempt: int) -> None:
    base = HTTP_BACKOFF_BASE_SEC * (2 ** max(0, attempt - 1))
    jitter = random.uniform(0.1, 0.7)
    time.sleep(min(8.0, base + jitter))


def _http_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(HTTP_UAS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.alta.ru/",
        "Connection": "keep-alive",
    }


def _parse_playwright_proxy(proxy: str) -> dict[str, str] | None:
    p = (proxy or "").strip()
    if not p:
        return None
    parsed = urlparse(p)
    if not parsed.scheme or not parsed.hostname:
        return None
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    out: dict[str, str] = {"server": server}
    if parsed.username:
        out["username"] = parsed.username
    if parsed.password:
        out["password"] = parsed.password
    return out


def _parse_one_rois_table(table: Tag, default_trademark: str) -> list[dict[str, str]]:
    """Разбор одной таблицы блока ТРОИС на странице списка."""
    out: list[dict[str, str]] = []
    header_cells = table.find_all("th")
    if not header_cells:
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 2:
                maybe_header = " ".join(_clean_cell(td.get_text(" ", strip=True)).lower() for td in tds)
                if "регистрацион" in maybe_header:
                    header_cells = tds
                    break
    header_joined = " ".join(_clean_cell(th.get_text(" ", strip=True)).lower() for th in header_cells)
    if "регистрацион" not in header_joined:
        return out

    idx_holder: int | None = None
    idx_name: int | None = None
    idx_valid_until: int | None = None
    idx_representatives: int | None = None
    for i, th in enumerate(header_cells):
        h = _clean_cell(th.get_text(" ", strip=True)).lower()
        if "правооблад" in h:
            idx_holder = i
        if "наименование" in h and "оис" in h.replace(" ", "").lower():
            idx_name = i
        if "срок" in h or "действ" in h or "принимаются до" in h:
            idx_valid_until = i
        if "представител" in h:
            idx_representatives = i

    pending: dict[str, str] | None = None
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        cells = [_clean_cell(td.get_text(" ", strip=True)) for td in tds]
        joined = " ".join(cells).lower()

        if len(cells) >= 2 and REG_NUMBER_RE.match(cells[0] or ""):
            if pending:
                out.append(pending)
            tm = default_trademark
            if idx_name is not None and len(cells) > idx_name:
                alt = normalize_trademark_for_registry(cells[idx_name])
                if alt:
                    tm = alt
            rh = ""
            if idx_holder is not None and len(cells) > idx_holder:
                rh = cells[idx_holder]
            valid_until = ""
            if idx_valid_until is not None and len(cells) > idx_valid_until:
                valid_until = cells[idx_valid_until]
            elif len(cells) >= 3:
                valid_until = cells[2]
            representatives = ""
            if idx_representatives is not None and len(cells) > idx_representatives:
                representatives = cells[idx_representatives]
            pending = {
                "brand": tm,
                "trademark": tm,
                "reg_number": cells[0],
                "right_holder": rh,
                "status": "",
                "valid_until": valid_until,
                "representatives": representatives,
            }
            continue

        if len(cells) == 1 and pending:
            low = cells[0].lower()
            if "товар" in low and "принимаются" in low:
                continue
            if "класс товаров" in low or "код товаров" in low:
                continue
            if any(x in low for x in ("исключен", "истек", "действующ")):
                pending["status"] = cells[0]
            if "срок" in low or "действует до" in low:
                pending["valid_until"] = cells[0]
            if "представител" in low:
                pending["representatives"] = cells[0]

    if pending:
        out.append(pending)
    return out


def parse_alta_registry_html(html: str) -> list[dict[str, str]]:
    """Извлекает строки реестра: brand, trademark, right_holder, reg_number, status, valid_until, representatives."""
    soup = BeautifulSoup(html, "lxml")
    base_host = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(DEFAULT_ALTA_URL))
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, str]] = []

    href_pat = re.compile(r"/rois/\d", re.I)
    for a in soup.find_all("a", href=href_pat):
        if "подробнее" in (a.get_text() or "").lower():
            continue
        href = (a.get("href") or "").strip()
        if not href or "/rois/all" in href:
            continue
        abs_h = urljoin(base_host + "/", href)
        if "/rois/all" in abs_h:
            continue
        tm_raw = a.get_text(" ", strip=True)
        if not tm_raw:
            img = a.find("img")
            if img is not None:
                tm_raw = _clean_cell(str(img.get("alt") or ""))
        tm = normalize_trademark_for_registry(tm_raw)
        if not tm or len(tm) < 2:
            continue
        tbl = a.find_next("table")
        if tbl is None:
            continue
        for block in _parse_one_rois_table(tbl, default_trademark=tm):
            reg = _clean_cell(block.get("reg_number", ""))
            if not reg:
                continue
            key = (reg, block.get("trademark", tm))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "brand": normalize_trademark_for_registry(block.get("brand") or tm),
                    "trademark": normalize_trademark_for_registry(block.get("trademark") or tm),
                    "right_holder": _clean_cell(block.get("right_holder", "")),
                    "reg_number": reg,
                    "status": _clean_cell(block.get("status", "")),
                    "valid_until": _clean_cell(block.get("valid_until", "")),
                    "representatives": _clean_cell(block.get("representatives", "")),
                }
            )
    return rows


def fetch_alta_html(
    url: str,
    *,
    use_playwright: bool,
    proxy: str = "",
    timeout_sec: float = REQUEST_TIMEOUT,
    retries: int = HTTP_RETRIES,
) -> str:
    timeout_cfg = httpx.Timeout(
        connect=min(timeout_sec, 20.0),
        read=timeout_sec,
        write=timeout_sec,
        pool=min(timeout_sec, 10.0),
    )
    client_kwargs: dict[str, Any] = {
        "timeout": timeout_cfg,
        "follow_redirects": True,
    }
    p = (proxy or "").strip()
    if p:
        client_kwargs["proxy"] = p

    if not use_playwright:
        with httpx.Client(**client_kwargs) as client:
            for attempt in range(1, max(1, retries) + 1):
                headers = _http_headers()
                try:
                    logger.info(
                        "trois_registry: GET {} attempt {}/{} proxy={}",
                        url,
                        attempt,
                        retries,
                        "on" if p else "off",
                    )
                    r = client.get(url, headers=headers)
                    if r.status_code == 200 and len(r.text or "") >= 3000:
                        return r.text
                    if r.status_code in (403, 429):
                        logger.warning("trois_registry: anti-bot/limit status={} on {}", r.status_code, url)
                        if attempt < retries:
                            _retry_sleep(attempt)
                            continue
                        use_playwright = True
                        break
                    if r.status_code >= 500:
                        if attempt < retries:
                            _retry_sleep(attempt)
                            continue
                    r.raise_for_status()
                    if len(r.text or "") < 3000:
                        logger.warning("trois_registry: короткий ответ ({} bytes) на {}", len(r.text or ""), url)
                        if attempt < retries:
                            _retry_sleep(attempt)
                            continue
                        use_playwright = True
                        break
                    return r.text
                except Exception as e:
                    logger.warning("trois_registry: httpx error on {} attempt {}: {}", url, attempt, e)
                    if attempt < retries:
                        _retry_sleep(attempt)
                        continue
                    use_playwright = True
                    break

    if not use_playwright:
        raise RuntimeError("alta.ru: не удалось получить HTML через httpx")

    from playwright.sync_api import sync_playwright

    pw_proxy = _parse_playwright_proxy(proxy)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, proxy=pw_proxy) if pw_proxy else p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=random.choice(HTTP_UAS))
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_sec * 1000))
            time.sleep(2)
            return page.content()
        finally:
            browser.close()


def upsert_trois_registry_rows(rows: list[dict[str, str]]) -> dict[str, int]:
    created = updated = skipped = 0
    with SessionLocal() as db:
        for row in rows:
            reg = _clean_cell(row.get("reg_number", ""))
            if not reg or not REG_NUMBER_RE.match(reg):
                skipped += 1
                continue
            tm = normalize_trademark_for_registry(row.get("trademark", ""))
            brand = normalize_trademark_for_registry(row.get("brand", "")) or tm
            if not tm:
                skipped += 1
                continue
            rh = _clean_cell(row.get("right_holder", ""))[:500]
            st = _clean_cell(row.get("status", ""))[:120]
            vu = _clean_cell(row.get("valid_until", ""))[:128]
            reps = _clean_cell(row.get("representatives", ""))[:1200]
            existing = db.query(TroisRegistry).filter(TroisRegistry.reg_number == reg).one_or_none()
            if existing:
                existing.brand = brand[:512]
                existing.trademark = tm[:512]
                existing.right_holder = rh[:512]
                existing.status = st[:128]
                existing.valid_until = vu[:128]
                existing.representatives = reps
                updated += 1
            else:
                db.add(
                    TroisRegistry(
                        brand=brand[:512],
                        trademark=tm[:512],
                        right_holder=rh[:512],
                        reg_number=reg[:256],
                        status=st[:128],
                        valid_until=vu[:128],
                        representatives=reps,
                    )
                )
                created += 1
        db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


def sync_alta_trois_registry(
    *,
    base_url: str | None = None,
    max_pages: int | None = None,
    prefer_playwright: bool = False,
    proxy: str = "",
    timeout_sec: float = REQUEST_TIMEOUT,
    retries: int = HTTP_RETRIES,
) -> dict[str, Any]:
    """
    Загружает страницы списка ТРОИС, парсит таблицы, upsert в ``trois_registry`` по ``reg_number``.
    Пагинация: ``?page=2`` … до исчерпания новых записей или лимита страниц.
    """
    url0 = (base_url or os.getenv("TROIS_ALTA_LIST_URL", DEFAULT_ALTA_URL)).strip()
    limit = max_pages if max_pages is not None else MAX_PAGES
    base = url0.split("?", 1)[0].rstrip("/") + "/"
    all_rows: list[dict[str, str]] = []
    seen_regs: set[str] = set()
    pages_fetched = 0
    prev_chunk_regs: set[str] | None = None

    for n in range(1, limit + 1):
        page_url = base if n == 1 else f"{base}?page={n}"
        try:
            html = fetch_alta_html(
                page_url,
                use_playwright=prefer_playwright,
                proxy=proxy,
                timeout_sec=timeout_sec,
                retries=retries,
            )
        except Exception as e:
            logger.warning("trois_registry: не удалось загрузить {}: {}", page_url, e)
            break
        chunk = parse_alta_registry_html(html)
        chunk_regs = {r.get("reg_number", "") for r in chunk if r.get("reg_number")}
        if not chunk:
            if n > 1:
                break
        elif n > 1 and prev_chunk_regs is not None and chunk_regs and chunk_regs <= prev_chunk_regs:
            break
        new_count = 0
        for r in chunk:
            reg = r.get("reg_number", "")
            if reg and reg not in seen_regs:
                seen_regs.add(reg)
                all_rows.append(r)
                new_count += 1
        pages_fetched += 1
        prev_chunk_regs = chunk_regs
        if n > 1 and new_count == 0:
            break

    if not all_rows and not prefer_playwright:
        logger.warning("trois_registry: повторная загрузка с Playwright")
        return sync_alta_trois_registry(
            base_url=url0,
            max_pages=limit,
            prefer_playwright=True,
            proxy=proxy,
            timeout_sec=timeout_sec,
            retries=retries,
        )

    stats = upsert_trois_registry_rows(all_rows)
    return {
        "source_url": url0,
        "parsed_rows": len(all_rows),
        "pages_fetched": pages_fetched,
        **stats,
    }


def query_trois_matches_for_trademark(
    db,
    trademark_upper: str,
    *,
    like_min_len: int = 3,
    fuzzy_threshold: float = 0.74,
    max_results: int = 20,
) -> list[TroisRegistry]:
    """
    Надежный поиск ТРОИС:
    1) exact brand/trademark;
    2) LIKE-кандидаты;
    3) fuzzy ранжирование (SequenceMatcher) с порогом.
    """
    from sqlalchemy import func, or_

    def _norm(s: str) -> str:
        x = normalize_trademark_for_registry(s)
        x = re.sub(r"[^A-ZА-ЯЁ0-9]+", " ", x)
        return re.sub(r"\s+", " ", x).strip()

    def _score(a: str, b: str) -> float:
        return SequenceMatcher(None, _norm(a), _norm(b)).ratio()

    tm = normalize_trademark_for_registry(trademark_upper)
    if not tm:
        return []
    exact = (
        db.query(TroisRegistry)
        .filter(or_(func.upper(func.trim(TroisRegistry.trademark)) == tm, func.upper(func.trim(TroisRegistry.brand)) == tm))
        .limit(max_results)
        .all()
    )
    if exact:
        for row in exact:
            setattr(row, "_trois_match_score", 1.0)
        return exact

    candidates: list[TroisRegistry] = []
    if len(tm) >= like_min_len:
        pat = f"%{tm}%"
        candidates.extend(
            db.query(TroisRegistry)
            .filter(or_(TroisRegistry.trademark.like(pat), TroisRegistry.brand.like(pat)))
            .limit(400)
            .all()
        )

    if not candidates:
        first = tm[:1]
        if first:
            candidates.extend(
                db.query(TroisRegistry)
                .filter(or_(TroisRegistry.trademark.like(f"{first}%"), TroisRegistry.brand.like(f"{first}%")))
                .limit(1200)
                .all()
            )

    uniq: dict[str, TroisRegistry] = {}
    for row in candidates:
        key = (row.reg_number or "").strip() or str(row.id)
        uniq[key] = row

    scored: list[tuple[float, TroisRegistry]] = []
    for row in uniq.values():
        s = max(_score(tm, row.trademark or ""), _score(tm, row.brand or ""))
        if s >= fuzzy_threshold:
            scored.append((s, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = [r for _, r in scored[:max_results]]
    for s, row in scored[:max_results]:
        setattr(row, "_trois_match_score", round(float(s), 4))
    return out
