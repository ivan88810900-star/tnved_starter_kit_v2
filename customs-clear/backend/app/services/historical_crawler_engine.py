"""Асинхронный краулер открытых нормативных источников + пайплайн Gemini/UPSERT (как bulk_normative_ai)."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from sqlalchemy.orm import Session

from ..datetime_util import utc_now_naive
from ..db import SessionLocal
from ..models import HistoricalCrawlCheckpoint
from .bulk_normative_ai import (
    apply_structured_rows,
    call_gemini_with_throttle,
    extract_text_from_bytes,
    parse_llm_json_array,
)

DEFAULT_SEED_URLS = [
    "https://eec.eaeunion.org/comission/department/catr/ett/",
    "https://customs.gov.ru/",
]

# Playwright: ожидание навигации (networkidle часто зависает на метриках).
_PLAYWRIGHT_GOTO_WAIT = "domcontentloaded"
_PLAYWRIGHT_GOTO_TIMEOUT_MS = 120_000
_PLAYWRIGHT_HTTP_ERROR_MAX_ATTEMPTS = 3
_PLAYWRIGHT_HTTP_ERROR_BACKOFF_SEC = 2.5

# Реалистичный Chrome под Windows + языки — меньше отсеиваний SharePoint, чем у «голого» бота.
_PLAYWRIGHT_CHROME_WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_PLAYWRIGHT_EXTRA_HTTP_HEADERS: dict[str, str] = {
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Временная отладка: последний HTML, который вернул Playwright после page.content() (корень backend).
_DEBUG_PLAYWRIGHT_HTML_FILE = Path(__file__).resolve().parents[2] / "debug_alta.html"

try:
    from playwright_stealth import Stealth as _PlaywrightStealth

    _PLAYWRIGHT_STEALTH_SINGLETON = _PlaywrightStealth()
except ImportError:  # pragma: no cover
    _PLAYWRIGHT_STEALTH_SINGLETON = None


def _debug_save_playwright_html_dump(html: str, url: str) -> None:
    """Сохраняет снимок DOM в UTF-8 (перезапись при каждой успешной выгрузке контента)."""
    try:
        header = f"<!-- historical_crawler Playwright snapshot url={url} -->\n"
        _DEBUG_PLAYWRIGHT_HTML_FILE.write_text(header + html, encoding="utf-8")
    except OSError as e:
        logger.warning(f"historical_crawler: не удалось записать {_DEBUG_PLAYWRIGHT_HTML_FILE}: {e}")

# Страницы реестра SharePoint / ЕЭК — не карточки документов.
_LISTING_PAGE_RE = re.compile(
    r"/pages/alldocuments\.aspx|/pages/allitems\.aspx|/pages/forms/allitems\.aspx",
    re.IGNORECASE,
)

# Расширенная эвристика: PDF/DOC, SharePoint DisplayDocument, /documents/, ID в query, ключевые слова.
_DOC_QUERY_ID_RE = re.compile(r"[?&](documentid|docid|doc_id)\s*=[^&#]+", re.IGNORECASE)
# SharePoint часто передаёт источник через ?s=… (длинная строка).
_DOC_QUERY_S_RE = re.compile(r"[?&]s\s*=[^&#]{4,}", re.IGNORECASE)
_DOC_PATH_RE = re.compile(
    r"/pages/displaydocument\.aspx|/displaydocument\.aspx|/documents(?:/|\?|$)|/_layouts/|/document/|/npa/|/download",
    re.IGNORECASE,
)
_DOC_EXT_RE = re.compile(r"\.(pdf|docx?|html?)(\?|#|$)", re.IGNORECASE)
_DOC_KEYWORDS_RE = re.compile(
    r"приказ|решение|коллегии|письмо|методич|document|npa|download",
    re.IGNORECASE,
)

# Alta tamdoc: пагинация индекса (?page=2), не карточка документа.
_ALTA_TAMDOC_INDEX_PAGINATION_RE = re.compile(r"(?:^|[?&])page\s*=\s*\d+", re.IGNORECASE)
_ALTA_TAMDOC_DOC_PATH_RE = re.compile(r"^/tamdoc/([a-z0-9]{4,})(?:/.*)?$", re.IGNORECASE)
# Первый сегмент пути не должен совпадать с «служебными» словами (не id акта).
_ALTA_TAMDOC_EXCLUDE_FIRST_SEG = frozenset(
    {"page", "search", "index", "list", "rss", "feed", "archive", "category", "tag"},
)


def _is_alta_tamdoc_document_url(url: str) -> bool:
    """
    alta.ru: карточка — /tamdoc/24a0001/, /tamdoc/23pr1234/ (первый сегмент после /tamdoc/ — id ≥4 alnum).
    Не карточка: /tamdoc или /tamdoc/ с ?page=N (пагинация реестра).
    """
    u = urldefrag((url or "").strip())[0]
    if not u:
        return False
    p = urlparse(u)
    host = (p.netloc or "").lower().split(":")[0]
    if host != "alta.ru" and host != "www.alta.ru":
        return False

    raw_path = (p.path or "").lower()
    query = p.query or ""

    if raw_path in ("/tamdoc", "/tamdoc/"):
        if _ALTA_TAMDOC_INDEX_PAGINATION_RE.search(query):
            return False
        return False

    m = _ALTA_TAMDOC_DOC_PATH_RE.match(raw_path.rstrip("/"))
    if not m:
        return False
    if m.group(1).lower() in _ALTA_TAMDOC_EXCLUDE_FIRST_SEG:
        return False
    return True


_TKS_LAW_NEWS_PATH_RE = re.compile(
    r"^/news/law/\d{4}/\d{2}/\d{2}/\d+$",
    re.IGNORECASE,
)


def _is_tks_law_news_article_url(url: str) -> bool:
    """Карточка новости/статьи раздела «Законодательство» на tks.ru (не листинг /news/law)."""
    u = urldefrag((url or "").strip())[0]
    if not u:
        return False
    p = urlparse(u)
    host = (p.netloc or "").lower().split(":")[0]
    if host not in ("tks.ru", "www.tks.ru"):
        return False
    path = (p.path or "").rstrip("/")
    return bool(_TKS_LAW_NEWS_PATH_RE.match(path))


def url_looks_like_document_link(url: str, link_text: str = "") -> bool:
    """
    Ссылка на документ или карточку документа (HTML), в т.ч. без расширения .pdf в URL.
    Не считает страницами документов общие списки вроде AllDocuments.aspx.
    """
    u = urldefrag((url or "").strip())[0]
    if not u:
        return False
    low = u.lower()
    lt = (link_text or "").strip().lower()
    combined = low + " " + lt

    if _LISTING_PAGE_RE.search(low):
        return False

    if _is_tks_law_news_article_url(u):
        return True

    if _is_alta_tamdoc_document_url(u):
        return True

    if _DOC_PATH_RE.search(low):
        return True
    if _DOC_QUERY_ID_RE.search(low) or _DOC_QUERY_S_RE.search(low):
        return True
    if _DOC_EXT_RE.search(low):
        return True
    if _DOC_KEYWORDS_RE.search(combined):
        return True
    return False


YEAR_RE = re.compile(r"\b(20[0-2][0-9]|201[0-9])\b")


def _url_hash(url: str) -> str:
    norm = urldefrag(url.strip())[0]
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _years_in_text(text: str) -> set[int]:
    out: set[int] = set()
    for m in YEAR_RE.finditer(text or ""):
        try:
            y = int(m.group(1))
            if 1990 <= y <= 2100:
                out.add(y)
        except ValueError:
            continue
    return out


def _passes_year_filter(text: str, year_from: int, year_to: int, strict: bool) -> bool:
    ys = _years_in_text(text)
    if not ys:
        return not strict
    return any(year_from <= y <= year_to for y in ys)


@dataclass
class CrawlerSettings:
    year_from: int = 2015
    year_to: int = 2026
    http_delay_sec: float = 2.0
    llm_delay_sec: float = 4.0
    max_pages: int = 40
    max_documents: int = 500
    crawl_depth: int = 2
    strict_years: bool = False
    use_playwright: bool = False
    user_agent: str = (
        "CustomsClearHistoricalCrawler/1.0 (+https://example.local; contact: admin) "
        "httpx; respectful delay between requests"
    )
    seed_urls: list[str] | None = None
    allowed_hosts: set[str] | None = None
    # Если задано (например "/ru-ru/"), в обход и в выдачу документов попадают только URL, где path содержит подстроку.
    require_path: str | None = None


class HistoricalCrawler:
    def __init__(self, settings: CrawlerSettings) -> None:
        self.s = settings
        self._client: httpx.AsyncClient | None = None
        # Одна сессия Playwright на весь жизненный цикл краулера (куки SharePoint / docs.eaeunion.org).
        self._pw: Any = None
        self._pw_browser: Any = None
        self._pw_context: Any = None
        self._pw_page: Any = None

    async def __aenter__(self) -> HistoricalCrawler:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.s.user_agent},
            follow_redirects=True,
            timeout=httpx.Timeout(90.0),
            limits=httpx.Limits(max_connections=5),
        )
        if self.s.use_playwright:
            await self._playwright_ensure_started()
        return self

    async def __aexit__(self, *args: object) -> None:
        if self.s.use_playwright:
            await self._playwright_shutdown()
        if self._client:
            await self._client.aclose()
            self._client = None

    def _checkpoint_row(self, db: Session, digest: str) -> HistoricalCrawlCheckpoint | None:
        return db.query(HistoricalCrawlCheckpoint).filter(HistoricalCrawlCheckpoint.url_hash == digest).first()

    def _checkpoint_ok(self, db: Session, digest: str) -> bool:
        row = self._checkpoint_row(db, digest)
        return row is not None and (row.status or "") == "ok"

    def _save_checkpoint(
        self,
        db: Session,
        *,
        digest: str,
        url: str,
        status: str,
        measures: int,
        err: str,
    ) -> None:
        row = self._checkpoint_row(db, digest)
        now = utc_now_naive()
        if row is None:
            db.add(
                HistoricalCrawlCheckpoint(
                    url_hash=digest,
                    canonical_url=url[:8000],
                    status=status,
                    measures_applied=measures,
                    error_note=err[:4000],
                    processed_at=now,
                )
            )
        else:
            row.canonical_url = url[:8000]
            row.status = status
            row.measures_applied = measures
            row.error_note = err[:4000]
            row.processed_at = now

    async def _sleep_http(self) -> None:
        await asyncio.sleep(self.s.http_delay_sec)

    async def _fetch_httpx(self, url: str) -> tuple[int, bytes]:
        assert self._client is not None
        await self._sleep_http()
        r = await self._client.get(url)
        return r.status_code, r.content

    async def _playwright_ensure_started(self) -> None:
        if self._pw_context is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError("Установите playwright и выполните: playwright install chromium") from e

        self._pw = await async_playwright().start()
        self._pw_browser = await self._pw.chromium.launch(headless=False)
        self._pw_context = await self._pw_browser.new_context(**self._playwright_new_context_kwargs())
        self._pw_page = await self._pw_context.new_page()
        if _PLAYWRIGHT_STEALTH_SINGLETON is not None:
            await _PLAYWRIGHT_STEALTH_SINGLETON.apply_stealth_async(self._pw_page)
        else:
            logger.warning("historical_crawler: пакет playwright-stealth не найден — без маскировки отпечатков")
        logger.info(
            "historical_crawler: Playwright — headed Chromium, stealth, общий context/page для сохранения куков"
        )

    async def _playwright_shutdown(self) -> None:
        self._pw_page = None
        if self._pw_context is not None:
            try:
                await self._pw_context.close()
            except Exception as e:
                logger.debug(f"historical_crawler: context.close: {e}")
            self._pw_context = None
        if self._pw_browser is not None:
            try:
                await self._pw_browser.close()
            except Exception as e:
                logger.debug(f"historical_crawler: browser.close: {e}")
            self._pw_browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception as e:
                logger.debug(f"historical_crawler: playwright.stop: {e}")
            self._pw = None

    def _playwright_new_context_kwargs(self) -> dict[str, Any]:
        return {
            "user_agent": _PLAYWRIGHT_CHROME_WINDOWS_UA,
            "extra_http_headers": dict(_PLAYWRIGHT_EXTRA_HTTP_HEADERS),
            "viewport": {"width": 1920, "height": 1080},
        }

    async def _recover_pw_page(self) -> None:
        """Новая вкладка в том же context после сбоя навигации."""
        if self._pw_context is None:
            return
        try:
            if self._pw_page is not None:
                await self._pw_page.close()
        except Exception:
            pass
        self._pw_page = await self._pw_context.new_page()
        if _PLAYWRIGHT_STEALTH_SINGLETON is not None:
            await _PLAYWRIGHT_STEALTH_SINGLETON.apply_stealth_async(self._pw_page)

    async def _playwright_goto_with_retries(self, page: Any, url: str, *, use_shared_recovery: bool) -> tuple[int, bytes]:
        """
        До 3 попыток page.goto с wait_until=domcontentloaded.
        При HTTP 500–599 — пауза и повтор; при исключении навигации — пауза и (для shared) новая page.
        """
        last_status = 200
        for attempt in range(1, _PLAYWRIGHT_HTTP_ERROR_MAX_ATTEMPTS + 1):
            try:
                resp = await page.goto(
                    url,
                    wait_until=_PLAYWRIGHT_GOTO_WAIT,
                    timeout=_PLAYWRIGHT_GOTO_TIMEOUT_MS,
                )
                last_status = int(resp.status) if resp is not None else 200
            except Exception as e:
                logger.warning(
                    f"historical_crawler: Playwright goto попытка {attempt}/{_PLAYWRIGHT_HTTP_ERROR_MAX_ATTEMPTS} "
                    f"{url}: {e}"
                )
                if attempt >= _PLAYWRIGHT_HTTP_ERROR_MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(_PLAYWRIGHT_HTTP_ERROR_BACKOFF_SEC)
                if use_shared_recovery:
                    await self._recover_pw_page()
                    page = self._pw_page
                continue

            if 500 <= last_status <= 599:
                logger.warning(
                    f"historical_crawler: HTTP {last_status}, попытка {attempt}/{_PLAYWRIGHT_HTTP_ERROR_MAX_ATTEMPTS} "
                    f"— {url}"
                )
                if attempt >= _PLAYWRIGHT_HTTP_ERROR_MAX_ATTEMPTS:
                    html = await page.content()
                    _debug_save_playwright_html_dump(html, url)
                    return last_status, html.encode("utf-8", errors="replace")
                await asyncio.sleep(_PLAYWRIGHT_HTTP_ERROR_BACKOFF_SEC)
                continue

            html = await page.content()
            _debug_save_playwright_html_dump(html, url)
            return last_status, html.encode("utf-8", errors="replace")

        raise RuntimeError("historical_crawler: Playwright — исчерпаны попытки goto без возврата")

    async def _fetch_playwright_shared(self, url: str) -> tuple[int, bytes]:
        """Тот же BrowserContext и Page — куки с главной/списков передаются на карточки документов."""
        await self._playwright_ensure_started()
        if self._pw_page is None:
            raise RuntimeError("Playwright: page не инициализирована")
        await self._sleep_http()
        return await self._playwright_goto_with_retries(self._pw_page, url, use_shared_recovery=True)

    async def _fetch_playwright_ephemeral(self, url: str) -> tuple[int, bytes]:
        """Разовый браузер только для fallback, когда режим Playwright выключен (старый httpx-путь)."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError("Установите playwright и выполните: playwright install chromium") from e

        await self._sleep_http()
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            try:
                context = await browser.new_context(**self._playwright_new_context_kwargs())
                page = await context.new_page()
                if _PLAYWRIGHT_STEALTH_SINGLETON is not None:
                    await _PLAYWRIGHT_STEALTH_SINGLETON.apply_stealth_async(page)
                return await self._playwright_goto_with_retries(page, url, use_shared_recovery=False)
            finally:
                await browser.close()

    async def fetch_document(self, url: str) -> tuple[int, bytes]:
        if self.s.use_playwright:
            return await self._fetch_playwright_shared(url)
        status, body = await self._fetch_httpx(url)
        if status == 200 and len(body) < 500 and b"<html" in body[:2000].lower():
            # вероятно JS-заглушка — пробуем Playwright при доступности (отдельная сессия: куки не из httpx)
            try:
                return await self._fetch_playwright_ephemeral(url)
            except Exception:
                return status, body
        return status, body

    def _parse_links(self, base_url: str, html: bytes) -> list[tuple[str, str]]:
        """Возвращает пары (абсолютный URL, текст ссылки)."""
        try:
            text = html.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        soup = BeautifulSoup(text, "lxml")
        out: list[tuple[str, str]] = []
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#") or href.lower().startswith("javascript:"):
                continue
            abs_url = urljoin(base_url, href)
            abs_url = urldefrag(abs_url)[0]
            title = (a.get_text() or "").strip()
            out.append((abs_url, title))
        return out

    def _allowed_host(self, netloc: str, effective_hosts: set[str]) -> bool:
        host = netloc.lower().split(":")[0]
        if not effective_hosts:
            return True
        if host in effective_hosts:
            return True
        return any(host.endswith("." + h) for h in effective_hosts)

    def _is_document_url(self, url: str, link_text: str) -> bool:
        if not url_looks_like_document_link(url, link_text):
            return False
        return _passes_year_filter(url + " " + link_text, self.s.year_from, self.s.year_to, self.s.strict_years)

    def _is_listing_url(self, url: str) -> bool:
        low = url.lower()
        if any(low.endswith(ext) for ext in (".pdf", ".doc", ".docx", ".zip", ".rar")):
            return False
        return True

    def _url_matches_require_path(self, url: str) -> bool:
        rp = (self.s.require_path or "").strip()
        if not rp:
            return True
        path = urlparse(urldefrag(url.strip())[0]).path
        return rp in path

    def _restore_require_path_prefix(self, base_url: str, abs_url: str) -> str:
        """
        SharePoint даёт ссылки с корня веб-приложения (/Pages/..., /_layouts/...),
        а urljoin с базой .../ru-ru/Pages/AllDocuments.aspx превращает их в .../Pages/...
        без префикса локали — тогда --require-path отсекает всё. Восстанавливаем префикс.
        """
        rp = (self.s.require_path or "").strip()
        if not rp:
            return abs_url
        locale = rp.strip("/")
        if not locale:
            return abs_url
        base_l, abs_l = base_url.lower(), abs_url.lower()
        if f"/{locale}/" not in base_l and not base_l.rstrip("/").endswith(f"/{locale}"):
            return abs_url
        p = urlparse(abs_url)
        b = urlparse(base_url)
        if p.scheme not in ("http", "https") or p.netloc.lower() != b.netloc.lower():
            return abs_url
        pl = (p.path or "").lower()
        if pl == f"/{locale}" or pl.startswith(f"/{locale}/"):
            return abs_url
        # Не трогаем явные пути других локалей (например /hy/, /kk-kz/).
        if len(pl) > 1 and pl[0] == "/":
            second = pl.split("/")[1] if "/" in pl[1:] else ""
            if second and second != locale.lower() and "-" in second and second[0:2].isalpha():
                return abs_url
        rootish = (
            pl.startswith("/pages/")
            or pl.startswith("/_layouts/")
            or pl.startswith("/documents")
            or pl.startswith("/sitepages/")
        )
        if not rootish:
            return abs_url
        new_path = f"/{locale}{p.path}"
        return urlunparse((p.scheme, p.netloc, new_path, p.params, p.query, p.fragment))

    async def iter_document_urls(self) -> AsyncIterator[str]:
        """Обход в ширину от seed_urls: страницы списков + ссылки на документы.

        Если seed сам выглядит как URL документа (эвристика _is_document_url), он сразу
        отдаётся в выдачу — можно точечно запускать с --seeds «URL статьи» --depth 0.
        """
        seeds = self.s.seed_urls or list(DEFAULT_SEED_URLS)
        effective_hosts = self.s.allowed_hosts
        if not effective_hosts:
            effective_hosts = {urlparse(s).netloc.lower().split(":")[0] for s in seeds}
        seen_pages: set[str] = set()
        seen_docs: set[str] = set()
        q: deque[tuple[str, int]] = deque()
        for s in seeds:
            seed_norm = urldefrag((s or "").strip())[0]
            if not seed_norm:
                continue
            p0 = urlparse(seed_norm)
            if p0.scheme not in ("http", "https"):
                continue
            if not self._allowed_host(p0.netloc, effective_hosts):
                continue
            if not self._url_matches_require_path(seed_norm):
                continue
            if self._is_document_url(seed_norm, ""):
                if seed_norm not in seen_docs:
                    seen_docs.add(seed_norm)
                    yield seed_norm
                    if len(seen_docs) >= self.s.max_documents:
                        return
                # При depth=0 дальше обходить нечего — не качаем ту же страницу второй раз как листинг.
                if self.s.crawl_depth > 0:
                    q.append((seed_norm, 0))
            else:
                q.append((seed_norm, 0))

        pages_fetched = 0
        while q and pages_fetched < self.s.max_pages:
            page_url, depth = q.popleft()
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            parsed = urlparse(page_url)
            if parsed.scheme not in ("http", "https"):
                continue
            if not self._allowed_host(parsed.netloc, effective_hosts):
                continue
            pages_fetched += 1
            logger.info(f"historical_crawler: страница {pages_fetched}/{self.s.max_pages} — {page_url}")

            try:
                status, body = await self.fetch_document(page_url)
            except Exception as e:
                logger.warning(f"historical_crawler: fetch страницы {page_url}: {e}")
                continue

            if status >= 400 or not body:
                continue

            for abs_url, title in self._parse_links(page_url, body):
                abs_url = self._restore_require_path_prefix(page_url, abs_url)
                p2 = urlparse(abs_url)
                if p2.scheme not in ("http", "https"):
                    continue
                if not self._allowed_host(p2.netloc, effective_hosts):
                    continue
                if not self._url_matches_require_path(abs_url):
                    continue

                if self._is_document_url(abs_url, title):
                    if abs_url not in seen_docs:
                        seen_docs.add(abs_url)
                        yield abs_url
                        if len(seen_docs) >= self.s.max_documents:
                            return
                    continue

                if depth < self.s.crawl_depth and self._is_listing_url(abs_url):
                    if abs_url not in seen_pages:
                        q.append((abs_url, depth + 1))

    async def process_url_pipeline(self, url: str, *, skip_checkpoint: bool = False) -> dict[str, int | str]:
        """Скачать документ → Gemini → UPSERT. Возвращает {measures, status, error}."""
        digest = _url_hash(url)
        with SessionLocal() as db:
            if not skip_checkpoint and self._checkpoint_ok(db, digest):
                return {"measures": 0, "status": "skipped", "error": ""}

        try:
            status, body = await self.fetch_document(url)
        except Exception as e:
            with SessionLocal() as db:
                self._save_checkpoint(db, digest=digest, url=url, status="error", measures=0, err=str(e))
                db.commit()
            return {"measures": 0, "status": "error", "error": str(e)}

        if status >= 400:
            err = f"HTTP {status}"
            with SessionLocal() as db:
                self._save_checkpoint(db, digest=digest, url=url, status="error", measures=0, err=err)
                db.commit()
            return {"measures": 0, "status": "error", "error": err}

        text = extract_text_from_bytes(body, source_hint=url)
        if not text.strip():
            err = "Пустой текст после извлечения"
            with SessionLocal() as db:
                self._save_checkpoint(db, digest=digest, url=url, status="error", measures=0, err=err)
                db.commit()
            return {"measures": 0, "status": "error", "error": err}

        try:
            raw = await call_gemini_with_throttle(text, min_interval_sec=self.s.llm_delay_sec)
            rows = parse_llm_json_array(raw)
        except Exception as e:
            logger.exception(f"historical_crawler LLM {url}: {e}")
            with SessionLocal() as db:
                self._save_checkpoint(db, digest=digest, url=url, status="error", measures=0, err=str(e))
                db.commit()
            return {"measures": 0, "status": "error", "error": str(e)}

        with SessionLocal() as db:
            try:
                n = apply_structured_rows(db, rows, source_tag=f"crawler:{url[:200]}")
                db.commit()
            except Exception as e:
                db.rollback()
                logger.exception(f"historical_crawler DB {url}: {e}")
                self._save_checkpoint(db, digest=digest, url=url, status="error", measures=0, err=str(e))
                db.commit()
                return {"measures": 0, "status": "error", "error": str(e)}

            self._save_checkpoint(db, digest=digest, url=url, status="ok", measures=n, err="")
            db.commit()
        return {"measures": int(n), "status": "ok", "error": ""}


async def run_historical_crawl(
    settings: CrawlerSettings,
    *,
    skip_checkpoint: bool = False,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, int]:
    """Полный прогон: обход + обработка каждого URL."""
    docs = 0
    measures_total = 0
    errors = 0
    async with HistoricalCrawler(settings) as crawler:
        async for doc_url in crawler.iter_document_urls():
            docs += 1
            res = await crawler.process_url_pipeline(doc_url, skip_checkpoint=skip_checkpoint)
            measures_total += int(res.get("measures") or 0)
            if res.get("status") == "error":
                errors += 1
            if progress_cb:
                progress_cb(
                    {
                        "document_index": docs,
                        "url": doc_url,
                        "measures": measures_total,
                        "last_status": res.get("status"),
                        "last_error": res.get("error"),
                    }
                )
            await asyncio.sleep(settings.http_delay_sec)

    if measures_total > 0:
        try:
            from .preview_cache_revision import bump_preview_cache_revision

            bump_preview_cache_revision("historical_crawler")
        except Exception as e:
            logger.warning(f"bump_preview_cache_revision: {e}")

    return {"documents_tried": docs, "measures_applied": measures_total, "errors": errors}


def settings_from_env(
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    http_delay: float | None = None,
    llm_delay: float | None = None,
    max_pages: int | None = None,
    max_documents: int | None = None,
    depth: int | None = None,
    strict_years: bool | None = None,
    use_playwright: bool | None = None,
    seeds: list[str] | None = None,
    require_path: str | None = None,
) -> CrawlerSettings:
    yf = year_from if year_from is not None else int(os.getenv("HISTORICAL_CRAWLER_YEAR_FROM", "2015"))
    yt = year_to if year_to is not None else int(os.getenv("HISTORICAL_CRAWLER_YEAR_TO", "2026"))
    seeds_final = list(seeds or [])
    if not seeds_final:
        raw = os.getenv("HISTORICAL_CRAWLER_SEEDS", "").strip()
        if raw:
            seeds_final = [s.strip() for s in raw.split(",") if s.strip()]
    hosts_raw = os.getenv("HISTORICAL_CRAWLER_ALLOWED_HOSTS", "").strip()
    hosts: set[str] = set()
    if hosts_raw:
        hosts = {h.strip().lower() for h in hosts_raw.split(",") if h.strip()}
    rp = require_path if require_path is not None else os.getenv("HISTORICAL_CRAWLER_REQUIRE_PATH", "").strip()
    require_path_val = rp if rp else None
    return CrawlerSettings(
        year_from=yf,
        year_to=yt,
        http_delay_sec=http_delay if http_delay is not None else float(os.getenv("HISTORICAL_CRAWLER_HTTP_DELAY", "2")),
        llm_delay_sec=llm_delay if llm_delay is not None else float(os.getenv("HISTORICAL_CRAWLER_LLM_DELAY", "4")),
        max_pages=max_pages if max_pages is not None else int(os.getenv("HISTORICAL_CRAWLER_MAX_PAGES", "40")),
        max_documents=max_documents
        if max_documents is not None
        else int(os.getenv("HISTORICAL_CRAWLER_MAX_DOCUMENTS", "500")),
        crawl_depth=depth if depth is not None else int(os.getenv("HISTORICAL_CRAWLER_DEPTH", "2")),
        strict_years=strict_years
        if strict_years is not None
        else os.getenv("HISTORICAL_CRAWLER_STRICT_YEARS", "").lower() in ("1", "true", "yes"),
        use_playwright=use_playwright
        if use_playwright is not None
        else os.getenv("HISTORICAL_CRAWLER_USE_PLAYWRIGHT", "").lower() in ("1", "true", "yes"),
        seed_urls=seeds_final if seeds_final else None,
        allowed_hosts=hosts if hosts else None,
        require_path=require_path_val,
    )
