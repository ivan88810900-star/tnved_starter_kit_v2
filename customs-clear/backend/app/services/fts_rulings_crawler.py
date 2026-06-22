"""
Системный краулер предварительных решений / документов ФТС (customs.gov.ru).

Обходит пагинацию folder-страниц, извлекает ссылки на документы, парсит каждый
документ универсальным парсером. При отсутствии HS-кода в тексте — опциональный
AI-fallback через classify_hs_code.

Примечание: ``/folder/519`` на момент исследования (2026-06) — раздел таможенной
статистики (xlsx), не реестр ПКР. Краулер работает для любого folder URL и честно
маркирует записи без HS как ``needs_ai`` / пропускает не-классификационные файлы.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

DEFAULT_START_URL = "https://customs.gov.ru/folder/519"
DEFAULT_USER_AGENT = "CustomsClear-FTS-Crawler/1.0 (+https://github.com/ivan88810900-star/tnved_starter_kit_v2)"
REQUEST_TIMEOUT = 30.0

# 10 цифр ТН ВЭД: слитно или с разделителями (пробел, точка, дефис)
HS_CODE_RE = re.compile(
    r"(?<!\d)"
    r"(?:"
    r"\d{10}"
    r"|\d{4}(?:[\s.\-/]+\d+){1,4}"
    r")"
    r"(?!\d)",
)

DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b"), "dmy_slash"),
]

DOC_NUMBER_RE = re.compile(
    r"(?:"
    r"(?:№|N[o\u043e\u0301]?\.?\s*)"
    r"([\w\d./\-–—]+)"
    r"|"
    r"(?:ПКР|предварительн\w*\s+решени\w*)[\s\S]{0,40}?(?:№|N[o\u043e\u0301]?\.?\s*)"
    r"([\w\d./\-–—]+)"
    r")",
    re.IGNORECASE,
)

CLASSIFICATION_KEYWORDS = re.compile(
    r"классификац|предварительн\w*\s+реш|код\s+товара|ТН\s*ВЭД|HS\s*code",
    re.IGNORECASE,
)

SKIP_EXTENSIONS = frozenset({".xlsx", ".xls", ".pdf", ".zip", ".rar", ".doc", ".docx"})


@dataclass
class ParsedFtsRuling:
    ruling_number: str
    ruling_date: str
    goods_description: str
    assigned_hs_code: str
    rationale: str
    source_url: str
    agency: str = "FTS-CRAWL"
    hs_source: str = "regex"  # regex | ai | none
    raw_title: str = ""


@dataclass
class CrawlStats:
    pages_fetched: int = 0
    links_found: int = 0
    documents_parsed: int = 0
    rulings_imported: int = 0
    skipped_non_classification: int = 0
    ai_hs_extractions: int = 0
    errors: list[str] = field(default_factory=list)


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html or "")
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_hs_code(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    return digits[:10] if len(digits) >= 10 else ""


def parse_date_to_iso(text: str) -> str:
    chunk = (text or "")[:2000]
    for pat, kind in DATE_PATTERNS:
        m = pat.search(chunk)
        if not m:
            continue
        try:
            if kind == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def extract_hs_codes(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in HS_CODE_RE.finditer(text or ""):
        hs = normalize_hs_code(m.group(0))
        if len(hs) == 10 and hs not in seen:
            seen.add(hs)
            out.append(hs)
    return out


def extract_document_number(text: str, fallback_url: str) -> str:
    for m in DOC_NUMBER_RE.finditer(text or ""):
        for g in m.groups():
            if g and len(g.strip()) >= 3:
                return g.strip()[:128]
    path = urlparse(fallback_url).path.rstrip("/")
    slug = path.split("/")[-1] if path else ""
    if slug and slug not in ("519", "518", "483"):
        return f"FTS-DOC-{slug}"[:128]
    return f"FTS-CRAWL-{hash(fallback_url) & 0xFFFFFF:06X}"


def extract_links(html: str, base_url: str) -> list[str]:
    """Извлекает абсолютные URL документов и folder-страниц из HTML."""
    hrefs = re.findall(r'''href=["']([^"']+)["']''', html or "", flags=re.IGNORECASE)
    out: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        href = href.strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.netloc and "customs.gov.ru" not in parsed.netloc:
            continue
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in SKIP_EXTENSIONS):
            continue
        is_doc = (
            "/document/" in path_lower
            or "/storage/document/" in path_lower
            or re.search(r"/folder/\d+", path_lower)
        )
        if not is_doc:
            continue
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))
        if clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def discover_pagination_urls(start_url: str, html: str) -> list[str]:
    """Находит все страницы пагинации folder без ручного перечисления."""
    pages: set[int] = {1}
    base = start_url.split("?")[0]
    for m in re.finditer(r"[?&]page=(\d+)", html or "", flags=re.IGNORECASE):
        pages.add(int(m.group(1)))
    for m in re.finditer(rf"{re.escape(base)}\?page=(\d+)", html or "", flags=re.IGNORECASE):
        pages.add(int(m.group(1)))
    max_page = max(pages) if pages else 1
    return [f"{base}?page={p}" if p > 1 else base for p in range(1, max_page + 1)]


def is_classification_relevant(text: str, url: str) -> bool:
    blob = f"{text}\n{url}"
    if CLASSIFICATION_KEYWORDS.search(blob):
        return True
    if "/document/text/" in url or "/document/letter/" in url:
        return True
    return bool(extract_hs_codes(text))


def parse_document_html(html: str, url: str) -> ParsedFtsRuling | None:
    """Универсальный парсер страницы решения."""
    plain = _strip_html(html)
    if len(plain) < 40:
        return None
    if not is_classification_relevant(plain, url):
        return None

    title_m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    title = _strip_html(title_m.group(1)) if title_m else ""

    hs_codes = extract_hs_codes(plain)
    hs = hs_codes[0] if hs_codes else ""
    ruling_number = extract_document_number(plain, url)
    ruling_date = parse_date_to_iso(plain)

    # Описание: первые осмысленные абзацы без навигации
    desc_lines = [ln.strip() for ln in plain.split("\n") if len(ln.strip()) > 20]
    goods_description = "\n".join(desc_lines[:8])[:4000] or title[:4000]

    rationale_parts = []
    for kw in ("обоснован", "классифицир", "отнес", "признан", "считать"):
        for ln in desc_lines:
            if kw in ln.lower():
                rationale_parts.append(ln)
    rationale = "\n".join(rationale_parts[:5])[:4000] or goods_description[:2000]

    return ParsedFtsRuling(
        ruling_number=ruling_number,
        ruling_date=ruling_date,
        goods_description=goods_description,
        assigned_hs_code=hs,
        rationale=rationale,
        source_url=url[:512],
        raw_title=title[:512],
        hs_source="regex" if hs else "none",
    )


async def ai_extract_hs_code(description: str) -> str:
    """AI-fallback: извлечь HS из описания если regex не нашёл."""
    if not description.strip():
        return ""
    try:
        from .claude_service import classify_hs_code

        result = await classify_hs_code(description[:2000], use_journal_hints=False)
        results = result.get("results") or []
        if results and isinstance(results[0], dict):
            code = str(results[0].get("hs_code") or results[0].get("code") or "")
            return normalize_hs_code(code)
    except Exception:
        return ""
    return ""


def fetch_url(url: str, *, client: httpx.Client | None = None) -> tuple[int, str]:
    if httpx is None:
        raise RuntimeError("httpx is required for FTS crawler")
    own = client is None
    cli = client or httpx.Client(
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": DEFAULT_USER_AGENT},
        follow_redirects=True,
    )
    try:
        resp = cli.get(url)
        return resp.status_code, resp.text
    finally:
        if own:
            cli.close()


def crawl_folder_sync(
    start_url: str = DEFAULT_START_URL,
    *,
    max_pages: int = 20,
    max_documents: int = 200,
    client: httpx.Client | None = None,
) -> tuple[list[ParsedFtsRuling], CrawlStats]:
    """
    Синхронный обход folder: пагинация → ссылки → парсинг документов.
    """
    stats = CrawlStats()
    if httpx is None:
        stats.errors.append("httpx not installed")
        return [], stats

    own = client is None
    cli = client or httpx.Client(
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": DEFAULT_USER_AGENT},
        follow_redirects=True,
    )
    rulings: list[ParsedFtsRuling] = []
    seen_urls: set[str] = set()

    try:
        status, first_html = fetch_url(start_url, client=cli)
        stats.pages_fetched += 1
        if status >= 400:
            stats.errors.append(f"HTTP {status} for {start_url}")
            return [], stats

        page_urls = discover_pagination_urls(start_url, first_html)[:max_pages]
        all_doc_urls: list[str] = []

        for page_url in page_urls:
            if page_url == start_url:
                html = first_html
            else:
                status, html = fetch_url(page_url, client=cli)
                stats.pages_fetched += 1
                if status >= 400:
                    stats.errors.append(f"HTTP {status} for {page_url}")
                    continue
            for link in extract_links(html, page_url):
                if link not in seen_urls:
                    seen_urls.add(link)
                    all_doc_urls.append(link)

        stats.links_found = len(all_doc_urls)

        for doc_url in all_doc_urls[:max_documents]:
            if "/folder/" in doc_url:
                continue
            try:
                status, doc_html = fetch_url(doc_url, client=cli)
                if status >= 400:
                    continue
                parsed = parse_document_html(doc_html, doc_url)
                if parsed is None:
                    stats.skipped_non_classification += 1
                    continue
                stats.documents_parsed += 1
                rulings.append(parsed)
            except Exception as exc:
                stats.errors.append(f"{doc_url}: {exc}")
    finally:
        if own:
            cli.close()

    return rulings, stats


def upsert_crawled_rulings(records: list[ParsedFtsRuling], *, dry_run: bool = False) -> int:
    """Идемпотентный UPSERT в classification_rulings."""
    if dry_run or not records:
        return len(records)

    from ..db import SessionLocal
    from ..models.tnved import ClassificationRuling

    imported = 0
    with SessionLocal() as db:
        for rec in records:
            if not rec.assigned_hs_code or len(rec.assigned_hs_code) < 4:
                continue
            rn = rec.ruling_number[:128]
            payload = {
                "ruling_number": rn,
                "ruling_date": rec.ruling_date or "",
                "agency": rec.agency,
                "goods_description": rec.goods_description,
                "assigned_hs_code": rec.assigned_hs_code,
                "rationale": rec.rationale,
                "source_url": rec.source_url,
            }
            existing = db.query(ClassificationRuling).filter(ClassificationRuling.ruling_number == rn).one_or_none()
            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
            else:
                db.add(ClassificationRuling(**payload))
            imported += 1
        db.commit()
    return imported


async def run_fts_crawl(
    *,
    start_url: str = DEFAULT_START_URL,
    max_pages: int = 20,
    max_documents: int = 200,
    use_ai_fallback: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Полный цикл: crawl → AI fallback → import."""
    rulings, stats = crawl_folder_sync(start_url, max_pages=max_pages, max_documents=max_documents)

    if use_ai_fallback:
        enriched: list[ParsedFtsRuling] = []
        for r in rulings:
            if r.assigned_hs_code:
                enriched.append(r)
                continue
            hs = await ai_extract_hs_code(r.goods_description)
            if hs:
                stats.ai_hs_extractions += 1
                enriched.append(
                    ParsedFtsRuling(
                        ruling_number=r.ruling_number,
                        ruling_date=r.ruling_date,
                        goods_description=r.goods_description,
                        assigned_hs_code=hs,
                        rationale=r.rationale,
                        source_url=r.source_url,
                        agency=r.agency,
                        hs_source="ai",
                        raw_title=r.raw_title,
                    )
                )
        rulings = enriched

    stats.rulings_imported = upsert_crawled_rulings(rulings, dry_run=dry_run)
    return {
        "status": "OK" if not stats.errors else "PARTIAL",
        "start_url": start_url,
        "pages_fetched": stats.pages_fetched,
        "links_found": stats.links_found,
        "documents_parsed": stats.documents_parsed,
        "rulings_with_hs": sum(1 for r in rulings if r.assigned_hs_code),
        "rulings_imported": stats.rulings_imported,
        "skipped_non_classification": stats.skipped_non_classification,
        "ai_hs_extractions": stats.ai_hs_extractions,
        "errors": stats.errors[:20],
        "dry_run": dry_run,
    }
