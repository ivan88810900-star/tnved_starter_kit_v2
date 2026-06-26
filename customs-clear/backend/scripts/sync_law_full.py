#!/usr/bin/env python3
"""
Полный краулер портала **law.tks.ru** и связанных разделов TKS (новости законодательства и др.).

**Разделы по топикам** (флаг ``--portal-topics``): последовательный обход
``https://law.tks.ru/?topics=1`` … ``?topics=20`` с пагинацией ``&page=``; со страницы списка
извлекаются заголовок, дата (из строки заголовка при наличии), ссылка ``/document/…``;
в колонку ``ingested_documents.category`` пишется ``topics:{id}``. Между HTTP-запросами
пауза 1.5–3 с. Для каждого нового документа — отдельный запрос к Gemini и запись в
``regulatory_ai_extracts`` (плюс догоняющий батч для документов без ``law_ai_done``).

1. **Discovery** (режим без ``--portal-topics``): главная https://law.tks.ru/ — сбор ссылок меню (абсолютные URL на law.tks.ru / www.tks.ru / tks.ru),
   плюс встроенный список типовых разделов (в т.ч. ``/news/law/``).
2. **Обход**: для лент вида ``/news/law/`` — страницы ``/news/law/``, ``/news/law/2/``, …;
   для прочих URL — обход ссылок на документы в пределах того же хоста.
3. **Сохранение**: ``ingested_documents`` (колонка ``category``, ``raw_text``, ``structured_payload`` с title, url,
   document_date, ``law_portal``); дедуп по ``sha256(url)``.
4. **LLM**: батчи по 10 документов → Gemini → ``regulatory_ai_extracts`` через ``sync_engine``.
5. **Пауза** ``random.uniform(2, 4)`` между запросами к страницам документов.
6. **Чекпоинт**: файл ``.checkpoints/law_full_sync.json`` (обработанные URL + прогресс пагинации).

**Режим «пылесос»** (без ``--category``): по очереди обрабатываются разделы из ``FULL_VACUUM_SECTIONS``,
затем уникальные пункты меню с law.tks.ru (как «Остальные разделы»), в конце — полный проход по ленте
``/news/law/`` (если не задан ``--no-full-law-sweep``). У путей вида ``/list/XXXX`` на **law.tks.ru** часто 404;
рабочие витрины — на **www.tks.ru**.

Базовые URL по темам (порядок совпадает с проходом краулера):

- Классификация (ТН ВЭД, предрешения): ``https://www.tks.ru/db/tnved/predecision/`` + фильтр по ключевым словам в ``/news/law/``.
- Таможенные платежи и налоги: ключевые слова в ``https://www.tks.ru/news/law/``.
- Таможенная стоимость: ключевые слова в ``/news/law/`` + ``https://www.tks.ru/tambook/``.
- Запреты и ограничения: ключевые слова в ``/news/law/``.
- Валютный контроль: ``https://www.tks.ru/currency/``.
- Интеллектуальная собственность (ТРОИС): ключевые слова в ``/news/law/``.
- Страна происхождения: ключевые слова в ``/news/law/``.
- Остальные: ссылки с главной law.tks.ru (кроме уже покрытых стартов).
- Полная лента: ``https://www.tks.ru/news/law/`` без фильтра по заголовку.

Запуск (из ``customs-clear/backend``)::

  python3 scripts/sync_law_full.py --portal-topics
  python3 scripts/sync_law_full.py --portal-topics --topics 1,3,5
  GEMINI_API_KEY=... python3 scripts/sync_law_full.py --portal-topics --topics 1,2,3
  python3 scripts/sync_law_full.py
  python3 scripts/sync_law_full.py --category "Законодательство"
  python3 scripts/sync_law_full.py --max-pages 2 --max-documents 30 --skip-ai
  GEMINI_API_KEY=... python3 scripts/sync_law_full.py --ai-batch-size 10

Требуется: ``pip install httpx beautifulsoup4 google-generativeai`` (для ИИ).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import uuid
from pathlib import Path
from typing import TypedDict
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from app.datetime_util import utc_now_naive  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import HistoricalCrawlCheckpoint, IngestedDocument  # noqa: E402

LAW_HOME = "https://law.tks.ru/"
NEWS_LAW_URL = "https://www.tks.ru/news/law/"
DEFAULT_SECTIONS: list[tuple[str, str]] = [
    ("Законодательство (новости)", NEWS_LAW_URL),
    ("Валютный контроль", "https://www.tks.ru/currency/"),
    ("Портал law.tks.ru", "https://law.tks.ru/"),
]

# Стартовые URL, которые не дублируем как «Остальные разделы» из меню law.tks.ru.
_CANONICAL_SECTION_ROOTS = frozenset(
    {
        "https://www.tks.ru/news/law",
        "https://www.tks.ru/currency",
        "https://www.tks.ru/db/tnved/predecision",
        "https://www.tks.ru/tambook",
    }
)


class VacuumSectionSpec(TypedDict, total=False):
    category: str
    start_url: str
    crawl: str  # "news_law" | "generic"
    title_keywords: tuple[str, ...] | None
    listing_ckpt_key: str


# Упорядоченный полный индекс: тематические проходы по /news/law/ не делят один чекпоинт пагинации (разные listing_ckpt_key).
FULL_VACUUM_SECTIONS: list[VacuumSectionSpec] = [
    {
        "category": "Классификация товаров (ТН ВЭД, предварительные решения)",
        "start_url": "https://www.tks.ru/db/tnved/predecision/",
        "crawl": "generic",
    },
    {
        "category": "Классификация товаров (разъяснения по кодам, новости)",
        "start_url": NEWS_LAW_URL,
        "crawl": "news_law",
        "listing_ckpt_key": "https://www.tks.ru/news/law|tnved-classify",
        "title_keywords": (
            "классифик",
            "тн вэд",
            "тнвэд",
            "код тн",
            "разъяснен",
            "предварительн",
            "подбор кода",
            "прецедент",
            "определен код",
        ),
    },
    {
        "category": "Таможенные платежи и налоги (НДС, акцизы, льготы)",
        "start_url": NEWS_LAW_URL,
        "crawl": "news_law",
        "listing_ckpt_key": "https://www.tks.ru/news/law|payments-taxes",
        "title_keywords": (
            "ндс",
            "акциз",
            "пошлин",
            "льгот",
            "платеж",
            "ставк",
            "налог",
            "возврат",
            "ту ",
            "таможенн платеж",
        ),
    },
    {
        "category": "Таможенная стоимость (КТС, риски, методы цены)",
        "start_url": NEWS_LAW_URL,
        "crawl": "news_law",
        "listing_ckpt_key": "https://www.tks.ru/news/law|customs-value",
        "title_keywords": (
            "стоимост",
            "ктс",
            "таможенн стоимост",
            "демпинг",
            "метод цен",
            "трансферт",
            "риск",
            "профил",
            "корректиров",
        ),
    },
    {
        "category": "Таможенная стоимость (справочник Tambook)",
        "start_url": "https://www.tks.ru/tambook/",
        "crawl": "generic",
    },
    {
        "category": "Запреты и ограничения (нетарифка, лицензии, сертификаты)",
        "start_url": NEWS_LAW_URL,
        "crawl": "news_law",
        "listing_ckpt_key": "https://www.tks.ru/news/law|bans-restrictions",
        "title_keywords": (
            "запрет",
            "огранич",
            "эмбарго",
            "санкц",
            "антидемпинг",
            "спецпошлин",
            "нетариф",
            "лиценз",
            "сертификат",
            "карантин",
            "ветеринар",
            "фитосанит",
        ),
    },
    {
        "category": "Валютный контроль",
        "start_url": "https://www.tks.ru/currency/",
        "crawl": "generic",
    },
    {
        "category": "Интеллектуальная собственность (ТРОИС)",
        "start_url": NEWS_LAW_URL,
        "crawl": "news_law",
        "listing_ckpt_key": "https://www.tks.ru/news/law|ip-trois",
        "title_keywords": (
            "троис",
            "интеллектуальн",
            "товарн знак",
            "патент",
            "авторск",
            "контрафакт",
            "охран",
            "объект ис",
        ),
    },
    {
        "category": "Страна происхождения (СТ-1, преференции)",
        "start_url": NEWS_LAW_URL,
        "crawl": "news_law",
        "listing_ckpt_key": "https://www.tks.ru/news/law|origin-preferential",
        "title_keywords": (
            "ст-1",
            "ст 1",
            "происхожден",
            "преференц",
            "сертификат происхожд",
            "треть стран",
            "гсп",
            "свободн торгов",
        ),
    },
]
# Если в меню нет точного названия раздела: URL ленты + ключевые слова в заголовке карточки (до скачивания страницы).
KEYWORD_CATEGORY_FALLBACK: dict[str, tuple[str, tuple[str, ...]]] = {
    "запреты и ограничения": (
        "https://www.tks.ru/news/law/",
        ("запрет", "огранич", "эмбарго", "санкц", "антидемпинг", "спецпошлин"),
    ),
}
ALLOWED_HOSTS = frozenset({"law.tks.ru", "www.tks.ru", "tks.ru"})
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _checkpoint_path() -> Path:
    d = _ROOT / ".checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return d / "law_full_sync.json"


def _load_ckpt() -> dict:
    p = _checkpoint_path()
    if not p.is_file():
        return {"version": 1, "done_urls": [], "listing": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # дедуп списка URL для быстрой проверки «уже было»
        data["done_urls"] = list(dict.fromkeys(data.get("done_urls") or []))
        return data
    except Exception:
        return {"version": 1, "done_urls": [], "listing": {}}


def _save_ckpt(data: dict) -> None:
    _checkpoint_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _url_key(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


def _abs_url(base: str, href: str) -> str | None:
    if not href or href.startswith("#") or href.startswith("javascript:"):
        return None
    u = urljoin(base, href.strip())
    p = urlparse(u)
    if p.scheme not in ("http", "https"):
        return None
    host = (p.netloc or "").lower().split(":")[0]
    if host not in ALLOWED_HOSTS and not host.endswith(".tks.ru"):
        return None
    # нормализуем на https
    if p.scheme == "http":
        u = "https://" + p.netloc + (p.path or "/") + (("?" + p.query) if p.query else "")
    return u.split("#")[0].rstrip("/") or u


def _vacuum_section_from_menu(name: str, url: str) -> VacuumSectionSpec | None:
    root = (url or "").strip().rstrip("/")
    if not root:
        return None
    low = root.lower()
    if any(x in low for x in ("/static/", ".css", ".js", ".png", ".jpg")):
        return None
    for c in _CANONICAL_SECTION_ROOTS:
        if root.lower() == c or root.lower().startswith(c + "/"):
            return None
    if "tks.ru" in urlparse(url).netloc.lower() and "/news/law" in urlparse(url).path.lower():
        return None
    return {
        "category": f"Остальные разделы: {name}",
        "start_url": url,
        "crawl": "generic",
    }


def build_vacuum_run_sections(
    client: httpx.Client,
    *,
    include_full_law_sweep: bool,
) -> list[VacuumSectionSpec]:
    """Полный упорядоченный список секций для режима без --category."""
    specs: list[VacuumSectionSpec] = list(FULL_VACUUM_SECTIONS)
    seen_menu_urls: set[str] = set()
    for name, url in discover_sections(client):
        spec = _vacuum_section_from_menu(name, url)
        if not spec:
            continue
        u = spec["start_url"].strip().rstrip("/")
        if u in seen_menu_urls:
            continue
        seen_menu_urls.add(u)
        specs.append(spec)
    if include_full_law_sweep:
        specs.append(
            {
                "category": "Законодательство (полный обход news/law)",
                "start_url": NEWS_LAW_URL,
                "crawl": "news_law",
                "listing_ckpt_key": "https://www.tks.ru/news/law|full-sweep",
                "title_keywords": None,
            }
        )
    return specs


def discover_sections(client: httpx.Client) -> list[tuple[str, str]]:
    """(название раздела, стартовый URL)."""
    seen: dict[str, str] = {}
    for name, url in DEFAULT_SECTIONS:
        seen[url] = name
    try:
        r = client.get(LAW_HOME, timeout=60.0)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return [(v, k) for k, v in seen.items()]

    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))[:120]
        u = _abs_url(LAW_HOME, href)
        if not u or not label or len(label) < 3:
            continue
        low = u.lower()
        if any(x in low for x in ("/static/", "/styles/", "/bootstrap/", "favicon", ".css", ".js", ".png")):
            continue
        if u not in seen:
            seen[u] = label
    return [(name, url) for url, name in seen.items()]


def _is_news_law_listing(url: str) -> bool:
    p = urlparse(url)
    return "tks.ru" in (p.netloc or "").lower() and "/news/law" in (p.path or "")


def _listing_page_url(base: str, page: int) -> str:
    base = base.rstrip("/")
    if page <= 1:
        return base + "/" if not base.endswith("/") else base
    return f"{base}/{page}/"


def _harvest_doc_links(html: str, base_url: str, *, max_n: int = 50) -> list[str]:
    """Ссылки на материалы с одной страницы-витрины (валюта, разделы без /news/law/)."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        u = _abs_url(base_url, a.get("href") or "")
        if not u or u in seen:
            continue
        low = u.lower()
        if any(x in low for x in ("/static/", ".css", ".js", ".png", ".jpg", "tel:", "mailto:")):
            continue
        parts = [x for x in urlparse(u).path.split("/") if x]
        if len(parts) < 2:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= max_n:
            break
    return out


def _parse_news_law_listing(html: str, base_url: str) -> list[tuple[str, str, str]]:
    """Список (url, заголовок, дата_если_есть)."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        u = _abs_url(base_url, a.get("href") or "")
        if not u or "/news/law/" not in u:
            continue
        parts = [x for x in u.split("/") if x]
        if len(parts) < 5:
            continue
        try:
            int(parts[-1])
        except ValueError:
            continue
        if u in seen:
            continue
        seen.add(u)
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))[:500]
        if len(title) < 8:
            continue
        m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", u)
        dt = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
        out.append((u, title, dt))
    return out


def _extract_article_body(html: str) -> tuple[str, str]:
    """(title, plain_text)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    h1 = soup.find("h1")
    title = re.sub(r"\s+", " ", h1.get_text(" ", strip=True)) if h1 else ""
    root = soup.select_one("article") or soup.select_one("main") or soup.body
    text = root.get_text("\n", strip=True) if root else ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    return title[:500], text[:500_000]


def _topics_portal_sleep() -> None:
    time.sleep(random.uniform(1.5, 3.0))


def _law_topics_listing_url(topic_id: int, page: int) -> str:
    if page <= 1:
        return f"https://law.tks.ru/?topics={topic_id}"
    return f"https://law.tks.ru/?topics={topic_id}&page={page}"


def _max_page_from_topics_html(html: str) -> int:
    mx = 1
    for m in re.finditer(r"[?&]page=(\d+)", html or ""):
        try:
            mx = max(mx, int(m.group(1)))
        except ValueError:
            continue
    return mx


def _date_hint_from_text(s: str) -> str:
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s or "")
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m2 = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", s or "")
    if m2:
        return f"{m2.group(1)}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
    return ""


def _parse_law_topics_listing(html: str) -> list[dict[str, str]]:
    """Строки списка: url, title, document_date (если удалось вытащить из заголовка)."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in soup.select("div.ccs-law-searchresults-ContentItem"):
        link = item.select_one(".ccs-law-document-link a[href^='/document/']")
        if not link:
            continue
        href = (link.get("href") or "").strip()
        if not href.startswith("/document/"):
            continue
        doc_url = urljoin("https://law.tks.ru/", href).split("#")[0].rstrip("/")
        title_el = item.select_one(".ccs-law-document-field-value")
        title = (
            re.sub(r"\s+", " ", title_el.get_text(" ", strip=True))
            if title_el
            else re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "")
        )
        low = title.lower().strip()
        if low in ("текст документа",) or len(title) < 5:
            continue
        if doc_url in seen:
            continue
        seen.add(doc_url)
        out.append(
            {
                "url": doc_url,
                "title": title[:500],
                "document_date": _date_hint_from_text(title),
            }
        )
    return out


def _extract_law_tks_document_body(html: str) -> tuple[str, str]:
    """Страница /document/… на law.tks.ru → (title, plain_text)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    h1 = soup.select_one("h1.ccs-h1") or soup.find("h1")
    title = re.sub(r"\s+", " ", h1.get_text(" ", strip=True)) if h1 else ""
    root = soup.select_one("div.ccs-document-container") or soup.select_one("main") or soup.body
    text = root.get_text("\n", strip=True) if root else ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    return title[:500], text[:500_000]


def _parse_topics_id_arg(s: str) -> list[int]:
    """Пустая строка → 1..20. Примеры: «1,3,5», «2-5», «1,4-6»."""
    s = (s or "").strip()
    if not s:
        return list(range(1, 21))
    out: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                lo, hi = int(a.strip()), int(b.strip())
                if lo > hi:
                    lo, hi = hi, lo
                out.extend(range(lo, hi + 1))
            except ValueError:
                continue
        else:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return sorted({x for x in out if 1 <= x <= 99})


def _parse_date_from_title(title: str) -> str:
    m = re.search(
        r"(\d{1,2})[./](\d{1,2})[./](\d{4})|(\d{4})[./-](\d{1,2})[./-](\d{1,2})",
        title or "",
    )
    if not m:
        return ""
    if m.group(1):
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if m.group(4):
        return f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}"
    return ""


def _already_ingested(db, url_hash: str) -> bool:
    return (
        db.query(IngestedDocument.id).filter(IngestedDocument.file_sha256 == url_hash).first() is not None
    )


def _checkpoint_table_done(db, url: str) -> bool:
    h = _url_key(url)
    row = db.query(HistoricalCrawlCheckpoint).filter(HistoricalCrawlCheckpoint.url_hash == h).first()
    return row is not None and (row.status or "") == "ok"


def _mark_checkpoint_table(db, url: str, *, note: str = "") -> None:
    h = _url_key(url)
    row = db.query(HistoricalCrawlCheckpoint).filter(HistoricalCrawlCheckpoint.url_hash == h).first()
    now = utc_now_naive()
    if row is None:
        db.add(
            HistoricalCrawlCheckpoint(
                url_hash=h,
                canonical_url=url[:2000],
                status="ok",
                measures_applied=0,
                error_note=(note or "")[:2000],
                processed_at=now,
            )
        )
    else:
        row.status = "ok"
        row.processed_at = now
        row.error_note = (note or "")[:2000]


def upsert_law_document(
    db,
    *,
    url: str,
    title: str,
    category: str,
    document_date: str,
    content_text: str,
    dry_run: bool,
    topic_id: int | None = None,
) -> str | None:
    fp = hashlib.sha256(url.encode("utf-8")).hexdigest()
    if dry_run:
        return None
    payload = {
        "law_portal": True,
        "title": title,
        "url": url,
        "category": category,
        "document_date": document_date,
        "law_ai_done": False,
    }
    if topic_id is not None:
        payload["law_portal_topics"] = True
        payload["topic_id"] = topic_id
    existing = db.query(IngestedDocument).filter(IngestedDocument.file_sha256 == fp).first()
    if existing:
        existing.original_filename = (title or url)[:512]
        existing.raw_text = content_text
        prev = existing.structured_payload if isinstance(existing.structured_payload, dict) else {}
        merged = {**prev, **payload}
        if prev.get("law_ai_done"):
            merged["law_ai_done"] = True
        existing.structured_payload = merged
        existing.category = (category or "")[:512]
        existing.mime_type = "text/html"
        existing.storage_uri = url[:2000]
        existing.status = "uploaded"
        existing.updated_at = utc_now_naive()
        db.flush()
        return existing.id
    doc_id = str(uuid.uuid4())
    db.add(
        IngestedDocument(
            id=doc_id,
            original_filename=(title or "law.tks.ru")[:512],
            mime_type="text/html",
            storage_uri=url[:2000],
            file_sha256=fp,
            detected_lang="ru",
            status="uploaded",
            error_message="",
            raw_text=content_text,
            structured_payload=payload,
            category=(category or "")[:512],
        )
    )
    db.flush()
    return doc_id


async def _run_ai_batches(db, *, batch_size: int, dry_run: bool) -> int:
    from app.services.sync_engine import (
        process_law_portal_documents_batch_with_ai,
        upsert_regulatory_ai_from_law_items,
    )

    total_rows = 0
    while True:
        rows = db.query(IngestedDocument).order_by(IngestedDocument.updated_at.desc()).limit(400).all()
        pending: list[IngestedDocument] = []
        for doc in rows:
            pl = doc.structured_payload if isinstance(doc.structured_payload, dict) else {}
            if not pl.get("law_portal"):
                continue
            if pl.get("law_ai_done"):
                continue
            if not (doc.raw_text or "").strip():
                continue
            pending.append(doc)
            if len(pending) >= batch_size:
                break
        if not pending:
            break
        batch = []
        for i, doc in enumerate(pending):
            pl = doc.structured_payload or {}
            batch.append(
                {
                    "index": i,
                    "title": str(pl.get("title") or doc.original_filename or "")[:400],
                    "url": str(pl.get("url") or doc.storage_uri or "")[:800],
                    "category": str(pl.get("category") or "")[:200],
                    "text": (doc.raw_text or "")[:14_000],
                }
            )
        extracted = await process_law_portal_documents_batch_with_ai(batch)
        if dry_run:
            print(f"DRY AI batch: {len(pending)} docs -> {len(extracted)} извлечений", flush=True)
            total_rows += len(extracted)
            break
        ins, upd = upsert_regulatory_ai_from_law_items(db, extracted)
        total_rows += ins + upd
        for doc in pending:
            pl = dict(doc.structured_payload or {})
            pl["law_ai_done"] = True
            doc.structured_payload = pl
            doc.status = "llm_structured"
        db.commit()
        print(f"  LLM batch: docs={len(pending)}, regulatory_rows +={ins + upd}", flush=True)
    return total_rows


def _crawl_law_portal_topics(
    client: httpx.Client,
    db,
    ckpt: dict,
    *,
    topic_ids: list[int],
    max_pages_per_topic: int,
    max_documents: int,
    dry_run: bool,
    use_json_ckpt: bool,
    skip_ai: bool,
) -> tuple[int, int]:
    """
    Обход https://law.tks.ru/?topics=N&page=P для каждого топика.
    Возвращает (число новых/обновлённых документов в сессии, строк regulatory_ai_extracts).
    """
    import asyncio

    from app.services.sync_engine import (
        process_law_portal_single_document_with_ai,
        upsert_regulatory_ai_from_law_items,
    )

    topics_ck: dict[str, dict] = ckpt.setdefault("topics_listing", {})  # type: ignore[assignment]
    regulatory_rows = 0
    ingested = 0
    has_gemini = bool((os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip())

    for topic_id in topic_ids:
        tkey = str(topic_id)
        state = topics_ck.setdefault(tkey, {"next_page": 1, "max_page": 1})
        page = int(state.get("next_page") or 1)
        max_known = max(1, int(state.get("max_page") or 1))

        print(f"\n== Топик {topic_id} (https://law.tks.ru/?topics={topic_id}) ==", flush=True)

        while page <= min(max_known, max_pages_per_topic):
            list_url = _law_topics_listing_url(topic_id, page)
            _topics_portal_sleep()
            try:
                r = client.get(list_url, timeout=60.0)
                if r.status_code != 200:
                    print(f"  listing HTTP {r.status_code} {list_url}", file=sys.stderr, flush=True)
                    break
                html = r.text
            except Exception as exc:
                print(f"  listing {list_url}: {exc}", file=sys.stderr, flush=True)
                break

            max_known = max(max_known, _max_page_from_topics_html(html))
            state["max_page"] = max_known
            items = _parse_law_topics_listing(html)
            if not items:
                break

            for row in items:
                if max_documents and ingested >= max_documents:
                    state["next_page"] = page
                    if use_json_ckpt:
                        _save_ckpt(ckpt)
                    return ingested, regulatory_rows

                doc_url = row["url"]
                fp = hashlib.sha256(doc_url.encode("utf-8")).hexdigest()
                done_set = set(ckpt.get("done_urls") or [])
                if use_json_ckpt and doc_url in done_set:
                    continue
                if not use_json_ckpt and _checkpoint_table_done(db, doc_url):
                    continue
                if _already_ingested(db, fp):
                    if use_json_ckpt:
                        lst = ckpt.setdefault("done_urls", [])
                        if doc_url not in lst:
                            lst.append(doc_url)
                            _save_ckpt(ckpt)
                    continue

                _topics_portal_sleep()
                try:
                    ar = client.get(doc_url, timeout=60.0)
                    ar.raise_for_status()
                except Exception as exc:
                    print(f"  skip doc {doc_url}: {exc}", file=sys.stderr, flush=True)
                    continue

                title_pg, body = _extract_law_tks_document_body(ar.text)
                title = title_pg or row.get("title") or doc_url
                doc_date = row.get("document_date") or _parse_date_from_title(title)
                cat_label = f"topics:{topic_id}"

                upsert_law_document(
                    db,
                    url=doc_url,
                    title=title,
                    category=cat_label,
                    document_date=doc_date,
                    content_text=body,
                    dry_run=dry_run,
                    topic_id=topic_id,
                )
                if not dry_run:
                    db.commit()
                    _mark_checkpoint_table(db, doc_url, note=f"law_portal_topics:{topic_id}")
                if use_json_ckpt:
                    lst = ckpt.setdefault("done_urls", [])
                    if doc_url not in lst:
                        lst.append(doc_url)
                    _save_ckpt(ckpt)

                ingested += 1
                print(f"  +[{topic_id}] {ingested} {doc_url[:72]}…", flush=True)

                if not skip_ai and not dry_run and has_gemini and body.strip():
                    try:
                        extracted = asyncio.run(
                            process_law_portal_single_document_with_ai(
                                title=title,
                                url=doc_url,
                                body=body,
                                topic_category=cat_label,
                            )
                        )
                        if extracted:
                            ins, upd = upsert_regulatory_ai_from_law_items(db, extracted)
                            regulatory_rows += ins + upd
                            doc_row = db.query(IngestedDocument).filter(IngestedDocument.file_sha256 == fp).first()
                            if doc_row:
                                pl = dict(doc_row.structured_payload or {})
                                pl["law_ai_done"] = True
                                doc_row.structured_payload = pl
                                doc_row.status = "llm_structured"
                            db.commit()
                            print(f"     regulatory_ai_extracts +{ins + upd}", flush=True)
                    except Exception as exc:
                        print(f"     Gemini: {exc}", file=sys.stderr, flush=True)
                        try:
                            db.rollback()
                        except Exception:
                            pass

            page += 1
            state["next_page"] = page
            topics_ck[tkey] = state
            if use_json_ckpt:
                _save_ckpt(ckpt)

        topics_ck[tkey] = state
        if use_json_ckpt:
            _save_ckpt(ckpt)

    return ingested, regulatory_rows


def _crawl_news_law_section(
    client: httpx.Client,
    db,
    category: str,
    start_url: str,
    ckpt: dict,
    *,
    max_pages: int,
    max_documents: int,
    dry_run: bool,
    use_json_ckpt: bool,
    title_keywords: tuple[str, ...] | None = None,
    listing_ckpt_key: str | None = None,
) -> int:
    ingested = 0
    lk = (listing_ckpt_key or "").strip() or start_url.rstrip("/")
    listing_state = ckpt.setdefault("listing", {}).setdefault(lk, {"next_page": 1})
    page = int(listing_state.get("next_page") or 1)
    pages_done = 0
    done_set = set(ckpt.get("done_urls") or [])

    while pages_done < max_pages:
        url = _listing_page_url(start_url.rstrip("/"), page)
        try:
            r = client.get(url, timeout=60.0)
            if r.status_code != 200:
                break
            items = _parse_news_law_listing(r.text, start_url)
        except Exception as exc:
            print(f"  listing error {url}: {exc}", file=sys.stderr, flush=True)
            break
        if not items:
            break
        for doc_url, title_hint, date_hint in items:
            if max_documents and ingested >= max_documents:
                listing_state["next_page"] = page
                if use_json_ckpt:
                    _save_ckpt(ckpt)
                return ingested
            if use_json_ckpt and doc_url in done_set:
                continue
            if not use_json_ckpt and _checkpoint_table_done(db, doc_url):
                continue
            if _already_ingested(db, hashlib.sha256(doc_url.encode()).hexdigest()):
                if use_json_ckpt:
                    lst = ckpt.setdefault("done_urls", [])
                    if doc_url not in lst:
                        lst.append(doc_url)
                        done_set.add(doc_url)
                        _save_ckpt(ckpt)
                continue
            if title_keywords:
                low_hint = (title_hint or "").lower()
                if not any(k in low_hint for k in title_keywords):
                    continue
            time.sleep(random.uniform(2.0, 4.0))
            try:
                ar = client.get(doc_url, timeout=60.0)
                ar.raise_for_status()
            except Exception as exc:
                print(f"  doc fetch skip {doc_url}: {exc}", file=sys.stderr, flush=True)
                continue
            title, body = _extract_article_body(ar.text)
            if not title:
                title = title_hint
            if title_keywords:
                blob = f"{title} {body[:4000]}".lower()
                if not any(k in blob for k in title_keywords):
                    continue
            doc_date = date_hint or _parse_date_from_title(title)
            upsert_law_document(
                db,
                url=doc_url,
                title=title,
                category=category,
                document_date=doc_date,
                content_text=body,
                dry_run=dry_run,
            )
            if not dry_run:
                db.commit()
                _mark_checkpoint_table(db, doc_url, note="law_full_sync")
            if use_json_ckpt:
                ckpt.setdefault("done_urls", []).append(doc_url)
                done_set.add(doc_url)
                _save_ckpt(ckpt)
            ingested += 1
            print(f"  + {ingested} {doc_url[:80]}…", flush=True)
        page += 1
        pages_done += 1
        listing_state["next_page"] = page
        if use_json_ckpt:
            _save_ckpt(ckpt)

    return ingested


def _crawl_generic_section(
    client: httpx.Client,
    db,
    category: str,
    start_url: str,
    ckpt: dict,
    *,
    max_documents: int,
    dry_run: bool,
    use_json_ckpt: bool,
) -> int:
    """Один проход: витрина + ограниченный набор вложенных страниц."""
    ingested = 0
    try:
        r = client.get(start_url, timeout=60.0)
        r.raise_for_status()
    except Exception as exc:
        print(f"  generic listing {start_url}: {exc}", file=sys.stderr, flush=True)
        return 0
    links = _harvest_doc_links(r.text, start_url, max_n=80)
    if start_url not in links:
        links.insert(0, start_url)
    done_set = set(ckpt.get("done_urls") or [])
    for doc_url in links:
        if max_documents and ingested >= max_documents:
            break
        if use_json_ckpt and doc_url in done_set:
            continue
        if not use_json_ckpt and _checkpoint_table_done(db, doc_url):
            continue
        if _already_ingested(db, hashlib.sha256(doc_url.encode()).hexdigest()):
            if use_json_ckpt:
                lst = ckpt.setdefault("done_urls", [])
                if doc_url not in lst:
                    lst.append(doc_url)
                    _save_ckpt(ckpt)
                    done_set.add(doc_url)
            continue
        time.sleep(random.uniform(2.0, 4.0))
        try:
            ar = client.get(doc_url, timeout=60.0)
            ar.raise_for_status()
        except Exception as exc:
            print(f"  skip {doc_url}: {exc}", file=sys.stderr, flush=True)
            continue
        title, body = _extract_article_body(ar.text)
        if len(body) < 200:
            continue
        doc_date = _parse_date_from_title(title)
        upsert_law_document(
            db,
            url=doc_url,
            title=title or doc_url,
            category=category,
            document_date=doc_date,
            content_text=body,
            dry_run=dry_run,
        )
        if not dry_run:
            db.commit()
            _mark_checkpoint_table(db, doc_url, note="law_full_sync generic")
        if use_json_ckpt:
            lst = ckpt.setdefault("done_urls", [])
            if doc_url not in lst:
                lst.append(doc_url)
                done_set.add(doc_url)
                _save_ckpt(ckpt)
        ingested += 1
        print(f"  + {ingested} {doc_url[:80]}…", flush=True)
    return ingested


def _max_docs_for_section(args_max: int, docs_total: int) -> int:
    if not args_max:
        return 10**9
    return max(0, args_max - docs_total)


def main() -> int:
    ap = argparse.ArgumentParser(description="Краулер law.tks.ru → ingested_documents + Gemini → regulatory_ai_extracts.")
    ap.add_argument(
        "--category",
        type=str,
        default="",
        help='Подстрока в названии раздела (например «таможенн» или «валют»). Пусто = полный «пылесос» по FULL_VACUUM_SECTIONS + меню + полный /news/law/.',
    )
    ap.add_argument("--max-pages", type=int, default=500, help="Макс. страниц пагинации на раздел")
    ap.add_argument(
        "--max-documents",
        "--limit-docs",
        type=int,
        default=0,
        dest="max_documents",
        help="Макс. документов всего (0 = без лимита по умолчанию). Укажите число, чтобы ограничить объём.",
    )
    ap.add_argument(
        "--no-full-law-sweep",
        action="store_true",
        help="Не делать финальный полный проход по /news/law/ без фильтра по ключевым словам.",
    )
    ap.add_argument("--skip-ai", action="store_true", help="Не вызывать Gemini")
    ap.add_argument("--ai-batch-size", type=int, default=10, help="Документов в одном запросе к Gemini")
    ap.add_argument("--dry-run", action="store_true", help="Не писать в БД")
    ap.add_argument("--no-file-checkpoint", action="store_true", help="Не использовать JSON-чекпоинт (только таблица)")
    ap.add_argument(
        "--portal-topics",
        action="store_true",
        help="Режим разделов law.tks.ru: обход ?topics=1…20 с пагинацией &page= (без старого «пылесоса» www.tks).",
    )
    ap.add_argument(
        "--topics",
        dest="topics_filter",
        default="",
        metavar="IDS",
        help="Список топиков: «1,3,5» или «2-5» или «1,4-6». Пусто при --portal-topics = все 1..20. "
        "Если указан без --portal-topics, портальный режим включается автоматически.",
    )
    args = ap.parse_args()
    if (args.topics_filter or "").strip() and not args.portal_topics:
        args.portal_topics = True
        print("Включён обход law.tks.ru (?topics=…), т.к. задан --topics.", flush=True)

    cat_filter = (args.category or "").strip().lower()
    use_json_ckpt = not args.no_file_checkpoint
    ckpt = _load_ckpt() if use_json_ckpt else {"done_urls": [], "listing": {}}

    import asyncio

    if args.portal_topics:
        if cat_filter:
            print("Примечание: при --portal-topics флаг --category игнорируется.", flush=True)
        topic_ids = _parse_topics_id_arg(args.topics_filter)
        print(f"Режим law.tks.ru / ?topics= : ID разделов {topic_ids}", flush=True)
        docs_total = 0
        reg_rows = 0
        with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=60.0) as client:
            with SessionLocal() as db:
                docs_total, reg_rows = _crawl_law_portal_topics(
                    client,
                    db,
                    ckpt,
                    topic_ids=topic_ids,
                    max_pages_per_topic=max(1, int(args.max_pages)),
                    max_documents=max(0, int(args.max_documents)),
                    dry_run=args.dry_run,
                    use_json_ckpt=use_json_ckpt,
                    skip_ai=args.skip_ai,
                )
                batch_extra = 0
                if not args.skip_ai and not args.dry_run:
                    batch_extra = asyncio.run(
                        _run_ai_batches(db, batch_size=max(1, int(args.ai_batch_size)), dry_run=False)
                    )
                elif not args.skip_ai and args.dry_run:
                    asyncio.run(_run_ai_batches(db, batch_size=max(1, int(args.ai_batch_size)), dry_run=True))
        if not args.skip_ai and not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip():
            print(
                "Предупреждение: не задан GEMINI_API_KEY/GOOGLE_API_KEY — извлечения в regulatory_ai_extracts пропущены.",
                file=sys.stderr,
                flush=True,
            )
        print(
            f"Готово (portal-topics). Документов за сессию: {docs_total}; "
            f"regulatory_ai_extracts (поштучно): {reg_rows}; догоняющий батч: {batch_extra if not args.skip_ai and not args.dry_run else 0}",
            flush=True,
        )
        return 0

    vacuum_specs: list[VacuumSectionSpec] = []
    legacy_sections: list[tuple[str, str]] = []
    legacy_title_keywords: tuple[str, ...] | None = None

    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=60.0) as client:
        if not cat_filter:
            vacuum_specs = build_vacuum_run_sections(
                client,
                include_full_law_sweep=not args.no_full_law_sweep,
            )
            print("Порядок обхода (категория → стартовый URL → режим):", flush=True)
            for spec in vacuum_specs:
                crawl = spec.get("crawl", "generic")
                lk = spec.get("listing_ckpt_key") or ""
                extra = f" [листинг: {lk}]" if lk else ""
                print(f"  • {spec['category']}\n    {spec['start_url']}  ({crawl}){extra}", flush=True)
        else:
            vacuum_specs = [s for s in FULL_VACUUM_SECTIONS if cat_filter in s["category"].lower()]
            for name, url in discover_sections(client):
                if cat_filter not in name.lower():
                    continue
                sp = _vacuum_section_from_menu(name, url)
                if sp:
                    vacuum_specs.append(sp)
            if not vacuum_specs:
                legacy_sections = [(n, u) for n, u in discover_sections(client) if cat_filter in n.lower()]
                if not legacy_sections and cat_filter in KEYWORD_CATEGORY_FALLBACK:
                    url_fb, kws = KEYWORD_CATEGORY_FALLBACK[cat_filter]
                    legacy_sections = [(args.category.strip() or cat_filter.title(), url_fb)]
                    legacy_title_keywords = kws
            if vacuum_specs:
                print(f"Фильтр --category «{args.category}»: секций: {len(vacuum_specs)}", flush=True)
                for spec in vacuum_specs[:20]:
                    print(f"  • {spec['category']} → {spec['start_url']}", flush=True)
                if len(vacuum_specs) > 20:
                    print(f"  … и ещё {len(vacuum_specs) - 20}", flush=True)

        if not vacuum_specs and not legacy_sections:
            print("Нет разделов для обработки (проверьте --category).", file=sys.stderr)
            return 2

        if not vacuum_specs and legacy_sections:
            print(
                f"Разделов (legacy): {len(legacy_sections)} — "
                + ", ".join(f"{n[:40]}" for n, _ in legacy_sections[:6]),
                flush=True,
            )

        docs_total = 0
        with SessionLocal() as db:
            if vacuum_specs:
                for spec in vacuum_specs:
                    if args.max_documents and docs_total >= args.max_documents:
                        break
                    cap = _max_docs_for_section(args.max_documents, docs_total)
                    name = spec["category"]
                    start = spec["start_url"]
                    crawl = spec.get("crawl", "generic")
                    if crawl == "news_law":
                        n = _crawl_news_law_section(
                            client,
                            db,
                            name,
                            start,
                            ckpt,
                            max_pages=args.max_pages,
                            max_documents=cap,
                            dry_run=args.dry_run,
                            use_json_ckpt=use_json_ckpt,
                            title_keywords=spec.get("title_keywords"),
                            listing_ckpt_key=spec.get("listing_ckpt_key"),
                        )
                        docs_total += n
                    else:
                        n = _crawl_generic_section(
                            client,
                            db,
                            name,
                            start,
                            ckpt,
                            max_documents=cap,
                            dry_run=args.dry_run,
                            use_json_ckpt=use_json_ckpt,
                        )
                        docs_total += n
            else:
                for name, start in legacy_sections:
                    if args.max_documents and docs_total >= args.max_documents:
                        break
                    cap = _max_docs_for_section(args.max_documents, docs_total)
                    if _is_news_law_listing(start):
                        n = _crawl_news_law_section(
                            client,
                            db,
                            name,
                            start,
                            ckpt,
                            max_pages=args.max_pages,
                            max_documents=cap,
                            dry_run=args.dry_run,
                            use_json_ckpt=use_json_ckpt,
                            title_keywords=legacy_title_keywords,
                        )
                        docs_total += n
                    else:
                        n = _crawl_generic_section(
                            client,
                            db,
                            name,
                            start,
                            ckpt,
                            max_documents=cap,
                            dry_run=args.dry_run,
                            use_json_ckpt=use_json_ckpt,
                        )
                        docs_total += n

            if not args.skip_ai and not args.dry_run:
                ai_rows = asyncio.run(
                    _run_ai_batches(db, batch_size=max(1, int(args.ai_batch_size)), dry_run=False)
                )
                print(f"Итого строк regulatory_ai_extracts (новых+обновлённых): {ai_rows}", flush=True)
            elif not args.skip_ai and args.dry_run:
                asyncio.run(_run_ai_batches(db, batch_size=max(1, int(args.ai_batch_size)), dry_run=True))

    print(f"Готово. Сохранено документов (сессия): {docs_total}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
