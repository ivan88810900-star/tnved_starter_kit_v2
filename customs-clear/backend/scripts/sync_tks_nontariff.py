#!/usr/bin/env python3
"""
Сбор **справки по товару** с портала **TKS.ru** (дерево ТН ВЭД).

Основной URL: ``https://www.tks.ru/db/tnved/tree/c{10_значный_код}``.
Если ответ не 200, делается запасной запрос ``https://www.tks.ru/db/tnved/tree/?c={код}``
(на стороне TKS путь ``/tree/c…`` может отдавать 404).

Актуальная вёрстка (2026): данные приходят AJAX-модалкой ``/db/tnved/tree/info/``
(POST + CSRF). Внутри — ``section.product-info`` → ``table.product-info__table``:
структурированная таблица ключ→значение («Пошлина:», «НДС:», «Лицензирование:»,
«Сертификация:», «Квотирование:» …) со значениями ``нет`` / ``да`` / ``есть``.

Валидация: 10-значный код страницы должен совпадать с кодом каталога.

- Блок **«Импорт»** (Пошлина / Антидемп. пошлина / Акциз / НДС) → текст в
  ``tnved_commodities.import_duty`` (не в ``non_tariff_measures``).
- Нетарифные флаги таблицы → ``non_tariff_measures`` **только при положительном
  значении (да/есть)**. Раньше парсер искал слова-метки по всей странице и эмитил
  меру даже при значении ``нет`` → массовый шум; теперь учитывается реальное значение.

  cd customs-clear/backend
  pip3 install playwright && playwright install chromium
  python3 scripts/sync_tks_nontariff.py --chapters 64,84,85 --workers 4
  python3 scripts/sync_tks_nontariff.py --chapters 64 --headful
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import threading
import time
from datetime import datetime
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from sqlalchemy import text

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from app.db import SessionLocal, engine  # noqa: E402
from app.models.tnved import Commodity, NonTariffMeasure  # noqa: E402

# Запрошенный пользователем шаблон + запасной (?c=) при 404/пустом ответе
TKS_TREE_URL_PRIMARY = "https://www.tks.ru/db/tnved/tree/c{code}"
TKS_TREE_URL_FALLBACK = "https://www.tks.ru/db/tnved/tree/?c={code}"
TKS_TREE_ROOT_URL = "https://www.tks.ru/db/tnved/tree/"
TKS_TREE_INFO_URL = "https://www.tks.ru/db/tnved/tree/info/"
EXPECTED_CHAPTERS = [f"{i:02d}" for i in range(1, 98)]

# Ротация UA (антибот): похоже на реальные браузеры.
TKS_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
)

ALLOWED_MEASURE_TYPES = frozenset(
    {
        "ban",
        "license",
        "certificate",
        "vet_control",
        "phyto_control",
        "tr_ts",
        "marking",
        "sgr",
        "fsetc",
        "fsb",
        "other",
    }
)

# Жёсткие пределы сетевой части.
HTTP_TIMEOUT_SEC: float = 15.0
HTTP_CONNECT_TIMEOUT_SEC: float = 8.0
HTTP_RETRIES_PER_URL: int = 3
RETRY_BACKOFF_BASE_SEC: float = 1.3
MAX_HTTP_CONCURRENCY: int = 2
PREFLIGHT_TIMEOUT_SEC: float = 10.0

# Ограничитель параллелизма запросов к tks.ru, чтобы снижать шанс антибот-блокировки.
_HTTP_FETCH_SEMAPHORE = threading.Semaphore(MAX_HTTP_CONCURRENCY)


def _dbg(msg: str) -> None:
    """Подробный вывод в консоль (и nohup.out при фоновом запуске)."""
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def _digits10(code: str) -> str | None:
    d = re.sub(r"\D", "", code)[:10]
    return d if len(d) == 10 else None


def _is_aggregate_hs10(d: str) -> bool:
    """
    У TKS путь /tree/c{код} — для реальных 10-значных позиций.
    Коды вида …000000 (последние 6 нулей) — укрупнённые группы каталога, не конечные страницы.
    """
    return len(d) == 10 and d.endswith("000000")


def _tks_http_headers() -> dict[str, str]:
    """Заголовки как у настоящего браузера (httpx)."""
    return {
        "User-Agent": random.choice(TKS_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://www.tks.ru/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "DNT": "1",
    }


def _html_looks_like_tks_not_found(html: str) -> bool:
    low = (html or "").lower()
    return "страница не найдена" in low or "страницу не найти" in low


def _html_looks_like_antibot(html: str) -> bool:
    low = (html or "").lower()
    needles = (
        "captcha",
        "доступ запрещ",
        "access denied",
        "cf-browser-verification",
        "cloudflare",
        "ddos",
        "bot protection",
    )
    return any(n in low for n in needles)


def _extract_csrf_token(html: str) -> str:
    soup = _soup_from_tks_html(html or "")
    node = soup.select_one("input[name=csrfmiddlewaretoken]")
    if not node:
        return ""
    return (node.get("value") or "").strip()


def _retry_sleep(attempt: int) -> None:
    """Экспоненциальный backoff + jitter между повторами."""
    base = RETRY_BACKOFF_BASE_SEC * (2 ** max(0, attempt - 1))
    jitter = random.uniform(0.15, 0.9)
    time.sleep(min(8.0, base + jitter))


def _make_http_client(*, timeout_sec: float, proxy: str = "") -> httpx.Client:
    timeout_cap = min(float(timeout_sec), HTTP_TIMEOUT_SEC)
    timeout_cfg = httpx.Timeout(
        connect=min(timeout_cap, HTTP_CONNECT_TIMEOUT_SEC),
        read=timeout_cap,
        write=timeout_cap,
        pool=min(timeout_cap, 10.0),
    )
    kwargs: dict[str, Any] = {
        "timeout": timeout_cfg,
        "follow_redirects": True,
        "limits": httpx.Limits(max_keepalive_connections=4, max_connections=8),
    }
    p = (proxy or "").strip()
    if p:
        kwargs["proxy"] = p
    return httpx.Client(**kwargs)


def _preflight_tks(client: httpx.Client) -> tuple[bool, str]:
    """Быстрая проверка доступности TKS перед длинным прогоном."""
    probe_urls = ("https://www.tks.ru/", "https://www.tks.ru/db/tnved/")
    for url in probe_urls:
        try:
            headers = _tks_http_headers()
            _dbg(f"Preflight: проверяю доступность {url}")
            r = client.get(url, headers=headers)
            body = r.text or ""
            if r.status_code >= 500:
                continue
            if r.status_code in (403, 429) or _html_looks_like_antibot(body):
                return False, f"anti-bot блок ({url}, status={r.status_code})"
            if r.status_code == 404:
                continue
            return True, f"ok ({url}, status={r.status_code})"
        except Exception as e:
            _dbg(f"Preflight: ошибка {type(e).__name__} для {url}: {e!r}")
            continue
    return False, "нет сетевого доступа к tks.ru (timeout/блокировка сети)"


def _missing_chapters() -> list[str]:
    q_loaded = text(
        """
        SELECT DISTINCT substr(commodity_code, 1, 2) AS ch
        FROM non_tariff_measures
        WHERE length(commodity_code) = 10
          AND substr(commodity_code, 1, 2) BETWEEN '01' AND '97'
        """
    )
    q_catalog = text(
        """
        SELECT DISTINCT substr(code, 1, 2) AS ch
        FROM tnved_commodities
        WHERE length(code) = 10
          AND substr(code, 1, 2) BETWEEN '01' AND '97'
        """
    )
    with engine.connect() as conn:
        loaded = {str(r[0]) for r in conn.execute(q_loaded) if r[0]}
        in_catalog = {str(r[0]) for r in conn.execute(q_catalog) if r[0]}
    return [c for c in EXPECTED_CHAPTERS if c not in loaded and c in in_catalog]


def _soup_from_tks_html(raw: bytes | str) -> BeautifulSoup:
    if isinstance(raw, str):
        return BeautifulSoup(raw, "html.parser")
    for enc in ("utf-8", "windows-1251", "cp1251"):
        try:
            return BeautifulSoup(raw.decode(enc), "html.parser")
        except UnicodeDecodeError:
            continue
    return BeautifulSoup(raw.decode("utf-8", errors="replace"), "html.parser")


def _first_hs10(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"(?<!\d)(\d{10})(?!\d)", text.replace("\xa0", " "))
    return m.group(1) if m else None


def _norm_compact_digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _page_code_tree(soup: BeautifulSoup, expected: str) -> str | None:
    """Код со страницы: ``div.tree_code`` (как в ТЗ) и варианты вёрстки TKS (``tree-list__code``), иначе ``h1``."""
    exp = _digits10(expected)
    if not exp:
        return None
    for sel in (
        "div.tree_code",
        ".tree_code",
        "[class*='tree_code']",
        "div.tree-list__code",
        ".tree-list__code",
        "[class*='tree-list__code']",
    ):
        node = soup.select_one(sel)
        if node:
            raw = node.get_text(" ", strip=True)
            if exp == _first_hs10(raw):
                return exp
            if exp in _norm_compact_digits(raw):
                return exp
    h1 = soup.find("h1")
    if h1:
        raw = h1.get_text(" ", strip=True)
        if exp == _first_hs10(raw):
            return exp
        if exp in _norm_compact_digits(raw):
            return exp
    # Для modal HTML (AJAX info) код может быть без tree_code/h1 — ищем по всему тексту.
    if exp in _norm_compact_digits(soup.get_text(" ", strip=True)):
        return exp
    return None


def _find_heading_tag(soup: BeautifulSoup, *needles: str) -> Tag | None:
    """Первый заголовок/плашка, в тексте которого есть все подстроки needles (без учёта регистра)."""
    nlow = tuple(n.lower() for n in needles)
    for tag in soup.find_all(["h2", "h3", "h4", "div", "span", "p", "td", "th", "strong", "b"]):
        if not isinstance(tag, Tag):
            continue
        t = tag.get_text(" ", strip=True).lower()
        if all(n in t for n in nlow):
            return tag
    return None


def _block_around_heading(hit: Tag | None, soup: BeautifulSoup, *, fallback_needle: str) -> str:
    if hit:
        root = hit.find_parent("section")
        if root is None:
            p = hit.find_parent("div")
            while p is not None:
                cl = " ".join(p.get("class") or []).lower()
                if "panel" in cl or "tab-pane" in cl or "content" in cl:
                    root = p
                    break
                p = p.find_parent("div")
        if root is not None:
            return root.get_text("\n", strip=True)
        return hit.get_text("\n", strip=True)
    blob = soup.get_text("\n", strip=True)
    i = blob.lower().find(fallback_needle.lower())
    if i < 0:
        return ""
    return blob[i : i + 20000]


def _import_block_text(soup: BeautifulSoup) -> str:
    hit = _find_heading_tag(soup, "импорт")
    if hit is None:
        hit = _find_heading_tag(soup, "ввоз")
    return _block_around_heading(hit, soup, fallback_needle="импорт")


def _nontariff_block_text(soup: BeautifulSoup) -> str:
    hit = _find_heading_tag(soup, "нетарифн", "регулирован")
    return _block_around_heading(hit, soup, fallback_needle="нетарифн")


def _extra_info_block_text(soup: BeautifulSoup) -> str:
    hit = _find_heading_tag(soup, "дополнительн", "информац")
    return _block_around_heading(hit, soup, fallback_needle="дополнительн")


def _format_import_for_commodity(block: str) -> str:
    """Текст для поля import_duty: пошлина + НДС из блока Импорт."""
    if not block or len(block) < 5:
        return ""
    low = block.lower()
    chunks: list[str] = []
    for pat, label in (
        (r"ввозн\w*\s+пошлин[^\n.]{0,120}", "Пошлина"),
        (r"импортн\w*\s+пошлин[^\n.]{0,120}", "Пошлина"),
        (r"ставк\w*\s+пошлин[^\n.]{0,160}", "Пошлина"),
        (r"пошлин[^\n]{0,200}", "Пошлина"),
        (r"ндс[^\n]{0,200}", "НДС"),
        (r"налог\w*\s+на\s+добавленн\w*\s+стоимост[^\n]{0,120}", "НДС"),
    ):
        m = re.search(pat, low, flags=re.IGNORECASE)
        if m:
            a, b = m.span()
            snippet = re.sub(r"\s+", " ", block[a:b])[:400]
            if snippet and snippet not in chunks:
                chunks.append(f"{label}: {snippet}")
    if not chunks:
        snip = re.sub(r"\s+", " ", block[:1200])
        return f"Импорт (TKS.ru, фрагмент): {snip}"
    return " | ".join(chunks)[:8000]


def _add_spec(
    out: list[dict[str, str]],
    seen: set[tuple[str, str]],
    mt: str,
    desc: str,
    doc: str,
    act: str,
) -> None:
    mt = (mt or "other").strip().lower()
    if mt not in ALLOWED_MEASURE_TYPES:
        mt = "other"
    act = (act or "TKS.ru")[:255]
    doc = (doc or "")[:255]
    desc = (desc or "")[:2000]
    key = (mt, act[:200])
    if key in seen:
        return
    seen.add(key)
    out.append(
        {
            "measure_type": mt,
            "description": desc,
            "document_required": doc,
            "regulatory_act": act,
        }
    )


def _snippet(text: str, pos: int, radius: int = 220) -> str:
    lo = max(0, pos - radius)
    hi = min(len(text), pos + radius)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()


def parse_nontariff_regulation_block(block: str) -> list[dict[str, str]]:
    """Нетарифное регулирование: Лицензия, сертификат/декларация, вет/фито, СГР, ТР."""
    if not block or len(block) < 4:
        return []
    t, low = block, block.lower()
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    if re.search(r"\bлиценз", low):
        m = re.search(r"\bлиценз", t, flags=re.I)
        _add_spec(
            out,
            seen,
            "license",
            _snippet(t, m.start() if m else 0),
            "Лицензия при необходимости",
            "TKS.ru | Нетарифное регулирование: лицензия",
        )
    if re.search(r"сертификат", low) or re.search(r"декларац", low):
        m = re.search(r"сертификат|декларац", t, flags=re.I)
        _add_spec(
            out,
            seen,
            "certificate",
            _snippet(t, m.start() if m else 0),
            "Сертификат / декларация при необходимости",
            "TKS.ru | Нетарифное регулирование: сертификат / декларация",
        )
    if re.search(r"ветеринарн", low):
        _add_spec(
            out,
            seen,
            "vet_control",
            "По тексту блока: ветеринарный контроль.",
            "Ветеринарные документы при необходимости",
            "TKS.ru | Нетарифное регулирование: ветеринарный контроль",
        )
    if re.search(r"фитосанитар", low) or re.search(r"подкарантин", low):
        _add_spec(
            out,
            seen,
            "phyto_control",
            "По тексту блока: фитосанитарный контроль.",
            "Фитосанитарный сертификат при необходимости",
            "TKS.ru | Нетарифное регулирование: фитосанитарный контроль",
        )
    if re.search(r"\bсгр\b", low) or re.search(r"государственн\w*\s+регистрац", low):
        _add_spec(
            out,
            seen,
            "sgr",
            "По тексту блока: СГР / государственная регистрация.",
            "СГР при необходимости",
            "TKS.ru | Нетарифное регулирование: СГР",
        )
    if re.search(r"техническ\w*\s+регламент", low) or re.search(r"\bтр\s*тс\b", low) or re.search(
        r"\bтр\s*еаэс\b", low
    ):
        _add_spec(
            out,
            seen,
            "tr_ts",
            "По тексту блока: технический регламент / ТР ТС / ТР ЕАЭС.",
            "Документы по ТР при необходимости",
            "TKS.ru | Нетарифное регулирование: технический регламент",
        )
    return out


def parse_additional_info_block(block: str) -> list[dict[str, str]]:
    """Дополнительная информация: маркировка, Честный знак, нотификация ФСБ, ФСТЭК."""
    if not block or len(block) < 4:
        return []
    t, low = block, block.lower()
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    if re.search(r"маркировк", low) or re.search(r"честный\s*знак", low):
        m = re.search(r"маркировк|честный\s*знак", t, flags=re.I)
        _add_spec(
            out,
            seen,
            "marking",
            _snippet(t, m.start() if m else 0),
            "Маркировка при необходимости",
            "TKS.ru | Дополнительная информация: маркировка / Честный знак",
        )
    if re.search(r"нотификац\w*\s*фсб", low) or re.search(r"нотификац[^\n]{0,40}фсб", low):
        _add_spec(
            out,
            seen,
            "fsb",
            "По тексту блока: нотификация ФСБ.",
            "Нотификация ФСБ при необходимости",
            "TKS.ru | Дополнительная информация: нотификация ФСБ",
        )
    if re.search(r"фстэк", low, flags=re.I):
        m = re.search(r"фстэк", t, flags=re.I)
        _add_spec(
            out,
            seen,
            "fsetc",
            _snippet(t, m.start() if m else 0),
            "Требования ФСТЭК при необходимости",
            "TKS.ru | Дополнительная информация: ФСТЭК",
        )
    return out


def _fetch_tks_urls(code: str, *, timeout: float, client: httpx.Client) -> tuple[str | None, str, str]:
    """
    Возвращает (html | None, последний_url, note).

    note:
      - ""           -> успех
      - "not_found"  -> код не является конечной страницей / 404
      - "blocked"    -> похоже на anti-bot блок
      - "network"    -> сетевые ошибки / таймауты
      - "http_error" -> некорректные HTTP-ответы
    """
    exp = _digits10(code)
    if not exp:
        return None, "", "http_error"
    timeout_cap = min(float(timeout), HTTP_TIMEOUT_SEC)
    urls = [TKS_TREE_URL_PRIMARY.format(code=exp), TKS_TREE_URL_FALLBACK.format(code=exp)]
    saw_not_found = False
    saw_blocked = False
    saw_network_issue = False
    last_url = urls[-1]

    for url in urls:
        last_url = url
        for attempt in range(1, HTTP_RETRIES_PER_URL + 1):
            headers = _tks_http_headers()
            try:
                _dbg(
                    "HTTP GET "
                    f"hs_code={exp} url={url} attempt={attempt}/{HTTP_RETRIES_PER_URL} "
                    f"timeout={timeout_cap:.1f}s UA={headers.get('User-Agent', '')[:50]}…"
                )
                r = client.get(url, headers=headers)
                _dbg(
                    "HTTP ответ "
                    f"hs_code={exp} url={url} status={r.status_code} bytes={len(r.content)} attempt={attempt}"
                )
                if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
                    r.encoding = r.apparent_encoding or "utf-8"
                body = r.text or ""
                final_url = str(r.url)
                if r.status_code == 404 or _html_looks_like_tks_not_found(body):
                    saw_not_found = True
                    _dbg(
                        f"Код {exp}: страница не найдена "
                        f"(status={r.status_code}, url={final_url})"
                    )
                    break
                if r.status_code in (403, 429) or _html_looks_like_antibot(body):
                    saw_blocked = True
                    _dbg(
                        f"Код {exp}: похоже на anti-bot блок "
                        f"(status={r.status_code}, url={final_url})"
                    )
                    if attempt < HTTP_RETRIES_PER_URL:
                        _retry_sleep(attempt)
                        continue
                    break
                if r.status_code >= 500:
                    _dbg(f"Код {exp}: серверная ошибка status={r.status_code}, повторяем запрос.")
                    if attempt < HTTP_RETRIES_PER_URL:
                        _retry_sleep(attempt)
                        continue
                    break
                if r.status_code != 200:
                    _dbg(f"Код {exp}: неожиданный status={r.status_code}, пробую следующий URL.")
                    break
                if len(r.content) < 500:
                    _dbg(f"Код {exp}: слишком короткий ответ ({len(r.content)} байт), повторяем.")
                    if attempt < HTTP_RETRIES_PER_URL:
                        _retry_sleep(attempt)
                        continue
                    break
                return body, final_url, ""
            except httpx.TimeoutException as e:
                saw_network_issue = True
                _dbg(f"Ошибка доступа к коду {exp}: TIMEOUT url={url} attempt={attempt}: {e!r}")
                if attempt < HTTP_RETRIES_PER_URL:
                    _retry_sleep(attempt)
            except httpx.HTTPError as e:
                saw_network_issue = True
                _dbg(f"Ошибка доступа к коду {exp}: HTTPError url={url} attempt={attempt}: {e!r}")
                if attempt < HTTP_RETRIES_PER_URL:
                    _retry_sleep(attempt)
            except Exception as e:
                saw_network_issue = True
                _dbg(f"Ошибка доступа к коду {exp}: {type(e).__name__} url={url} attempt={attempt}: {e!r}")
                if attempt < HTTP_RETRIES_PER_URL:
                    _retry_sleep(attempt)
    if saw_not_found:
        return None, last_url, "not_found"
    if saw_blocked:
        return None, last_url, "blocked"
    if saw_network_issue:
        return None, last_url, "network"
    return None, last_url, "http_error"


def _fetch_tks_info_ajax(code: str, *, timeout: float, client: httpx.Client) -> tuple[str | None, str, str]:
    """
    Получение карточки кода через JS endpoint TKS: /db/tnved/tree/info/ (POST + CSRF).
    Это основной рабочий путь для актуальной версии сайта.
    """
    exp = _digits10(code)
    if not exp:
        return None, "", "http_error"
    timeout_cap = min(float(timeout), HTTP_TIMEOUT_SEC)
    saw_network_issue = False
    saw_blocked = False
    saw_not_found = False
    saw_server_500 = False

    for attempt in range(1, HTTP_RETRIES_PER_URL + 1):
        base_headers = _tks_http_headers()
        base_headers["Referer"] = TKS_TREE_ROOT_URL
        try:
            _dbg(
                "AJAX PREP GET "
                f"hs_code={exp} url={TKS_TREE_ROOT_URL} attempt={attempt}/{HTTP_RETRIES_PER_URL} "
                f"timeout={timeout_cap:.1f}s UA={base_headers.get('User-Agent', '')[:50]}…"
            )
            prep = client.get(TKS_TREE_ROOT_URL, headers=base_headers)
            prep_body = prep.text or ""
            if prep.status_code in (403, 429) or _html_looks_like_antibot(prep_body):
                saw_blocked = True
                _dbg(f"Код {exp}: anti-bot блок на preflight tree (status={prep.status_code})")
                if attempt < HTTP_RETRIES_PER_URL:
                    _retry_sleep(attempt)
                    continue
                break
            if prep.status_code >= 500:
                saw_network_issue = True
                _dbg(f"Код {exp}: preflight tree status={prep.status_code}, повтор.")
                if attempt < HTTP_RETRIES_PER_URL:
                    _retry_sleep(attempt)
                    continue
                break
            csrf = _extract_csrf_token(prep_body)
            if not csrf:
                saw_network_issue = True
                _dbg(f"Код {exp}: не найден csrfmiddlewaretoken на странице tree.")
                if attempt < HTTP_RETRIES_PER_URL:
                    _retry_sleep(attempt)
                    continue
                break

            ajax_headers = {
                "User-Agent": base_headers["User-Agent"],
                "Accept": "*/*",
                "Accept-Language": base_headers["Accept-Language"],
                "Referer": TKS_TREE_ROOT_URL,
                "Origin": "https://www.tks.ru",
                "X-CSRFToken": csrf,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }
            _dbg(
                "AJAX INFO POST "
                f"hs_code={exp} url={TKS_TREE_INFO_URL} attempt={attempt}/{HTTP_RETRIES_PER_URL}"
            )
            info = client.post(
                TKS_TREE_INFO_URL,
                headers=ajax_headers,
                data={"code": exp, "csrfmiddlewaretoken": csrf},
            )
            body = info.text or ""
            _dbg(f"AJAX INFO ответ hs_code={exp} status={info.status_code} bytes={len(info.content)}")
            if info.status_code == 200 and len(info.content) >= 500 and "modal__dialog" in body.lower():
                return body, TKS_TREE_INFO_URL, ""
            if info.status_code in (404,):
                saw_not_found = True
                break
            if info.status_code in (500,):
                # Для несуществующих/неконечных кодов endpoint часто отдаёт 500.
                saw_server_500 = True
                if attempt < HTTP_RETRIES_PER_URL:
                    _retry_sleep(attempt)
                    continue
                break
            if info.status_code in (403, 429) or _html_looks_like_antibot(body):
                saw_blocked = True
                if attempt < HTTP_RETRIES_PER_URL:
                    _retry_sleep(attempt)
                    continue
                break
            if _html_looks_like_tks_not_found(body):
                saw_not_found = True
                break
            saw_network_issue = True
            if attempt < HTTP_RETRIES_PER_URL:
                _retry_sleep(attempt)
        except httpx.TimeoutException as e:
            saw_network_issue = True
            _dbg(f"Ошибка доступа к коду {exp}: AJAX TIMEOUT attempt={attempt}: {e!r}")
            if attempt < HTTP_RETRIES_PER_URL:
                _retry_sleep(attempt)
        except httpx.HTTPError as e:
            saw_network_issue = True
            _dbg(f"Ошибка доступа к коду {exp}: AJAX HTTPError attempt={attempt}: {e!r}")
            if attempt < HTTP_RETRIES_PER_URL:
                _retry_sleep(attempt)
        except Exception as e:
            saw_network_issue = True
            _dbg(f"Ошибка доступа к коду {exp}: AJAX {type(e).__name__} attempt={attempt}: {e!r}")
            if attempt < HTTP_RETRIES_PER_URL:
                _retry_sleep(attempt)

    if saw_not_found or saw_server_500:
        return None, TKS_TREE_INFO_URL, "not_found"
    if saw_blocked:
        return None, TKS_TREE_INFO_URL, "blocked"
    if saw_network_issue:
        return None, TKS_TREE_INFO_URL, "network"
    return None, TKS_TREE_INFO_URL, "http_error"


def _fetch_tks_playwright(page: Any, code: str, *, timeout_ms: int) -> tuple[str | None, str, str]:
    exp = _digits10(code)
    if not exp:
        return None, "", "http_error"
    urls = [TKS_TREE_URL_PRIMARY.format(code=exp), TKS_TREE_URL_FALLBACK.format(code=exp)]
    last = urls[0]
    saw_not_found_pw = False
    saw_blocked_pw = False
    goto_to = max(3000, min(int(timeout_ms), 60000))
    networkidle_to = 15000
    for url in urls:
        last = url
        for attempt in range(1, HTTP_RETRIES_PER_URL + 1):
            try:
                _dbg(
                    f"Playwright goto hs_code={exp} url={url} "
                    f"attempt={attempt}/{HTTP_RETRIES_PER_URL} timeout_ms={goto_to}"
                )
                page.goto(url, wait_until="domcontentloaded", timeout=goto_to)
                try:
                    page.wait_for_load_state("networkidle", timeout=networkidle_to)
                except Exception as e:
                    _dbg(f"Playwright networkidle пропуск hs_code={exp}: {type(e).__name__}: {e!r}")
                page.wait_for_timeout(random.randint(900, 1700))
                raw = page.content() or ""
                low = raw.lower()
                if _html_looks_like_tks_not_found(raw):
                    saw_not_found_pw = True
                    _dbg(f"Playwright: страница «не найдена» hs_code={exp} url={url}")
                    break
                if _html_looks_like_antibot(raw):
                    saw_blocked_pw = True
                    _dbg(f"Playwright: anti-bot блок hs_code={exp} url={url}")
                    print(
                        "\n[!!!] Возможна защита TKS.ru — пройдите проверку в окне браузера. Ожидание 30 с...\n",
                        flush=True,
                    )
                    try:
                        page.wait_for_timeout(30000)
                    except Exception:
                        pass
                    if attempt < HTTP_RETRIES_PER_URL:
                        _retry_sleep(attempt)
                        continue
                    break
                if len(low) < 800:
                    _dbg(f"Playwright: короткий ответ hs_code={exp} len={len(low)}")
                    if attempt < HTTP_RETRIES_PER_URL:
                        _retry_sleep(attempt)
                        continue
                    break
                _dbg(f"Playwright OK hs_code={exp} url={url} len={len(raw)}")
                return raw, url, ""
            except Exception as e:
                _dbg(f"Playwright ERROR hs_code={exp} url={url} attempt={attempt}: {type(e).__name__}: {e!r}")
                if attempt < HTTP_RETRIES_PER_URL:
                    _retry_sleep(attempt)
    if saw_not_found_pw:
        return None, last, "not_found"
    if saw_blocked_pw:
        return None, last, "blocked"
    return None, last, "network"


def _merge_measure(db, commodity_code: str, spec: dict[str, str]) -> None:
    existing = (
        db.query(NonTariffMeasure)
        .filter(
            NonTariffMeasure.commodity_code == commodity_code,
            NonTariffMeasure.measure_type == spec["measure_type"],
            NonTariffMeasure.regulatory_act == spec["regulatory_act"],
        )
        .first()
    )
    row = NonTariffMeasure(
        id=existing.id if existing else None,
        commodity_code=commodity_code,
        measure_type=spec["measure_type"],
        description=spec["description"],
        document_required=spec["document_required"],
        regulatory_act=spec["regulatory_act"],
    )
    db.merge(row)


def _update_commodity_import(db, code: str, import_text: str) -> None:
    if not (import_text or "").strip():
        return
    row = db.query(Commodity).filter(Commodity.code == code).first()
    if row is not None:
        row.import_duty = import_text.strip()


# ──────────────────────────────────────────────────────────────────────
# Структурный парсер актуальной вёрстки TKS (modal AJAX):
#   section.product-info → table.product-info__table — таблица ключ→значение
#   («Пошлина:», «НДС:», «Лицензирование:», «Сертификация:» …).
# Раньше парсер искал ключевые слова по ВСЕЙ странице и эмитил меру при
# любом упоминании слова-метки (например «сертификат»), игнорируя реальное
# значение «нет» → массовые ложные меры (СГР/сертификат для ноутбука).
# Теперь меры эмитируются ТОЛЬКО для положительных флагов (да/есть).
# ──────────────────────────────────────────────────────────────────────

# Метка таблицы TKS → (measure_type, document_required, описание-основание)
_TKS_FLAG_MAP: dict[str, tuple[str, str, str]] = {
    "лицензирование": ("license", "Лицензия", "TKS.ru: по таблице — требуется лицензирование"),
    "квотирование": ("other", "Квота / разрешение", "TKS.ru: по таблице — применяется квотирование"),
    "сертификация": ("certificate", "Сертификат / декларация", "TKS.ru: по таблице — требуется сертификация"),
    "разреш. прочие": ("other", "Разрешительный документ", "TKS.ru: по таблице — иные разрешительные документы"),
}

# Метки блока «Импорт» (пошлина/НДС) для поля import_duty.
_TKS_IMPORT_LABELS: tuple[tuple[str, str], ...] = (
    ("пошлина", "Пошлина"),
    ("антидемп. пошлина", "Антидемп. пошлина"),
    ("акциз", "Акциз"),
    ("ндс", "НДС"),
)


def _tks_flag_is_positive(value: str) -> bool:
    """Флаг таблицы TKS считается положительным, если значение начинается с «да»/«есть»."""
    low = re.sub(r"\s+", " ", (value or "")).strip().lower()
    if not low or low.startswith("нет"):
        return False
    return low.startswith("да") or low.startswith("есть")


def parse_product_info_table(soup: BeautifulSoup) -> dict[str, str]:
    """Главная таблица TKS ``table.product-info__table`` → dict ключ→значение (ключ в lower)."""
    table = soup.select_one("table.product-info__table")
    if table is None:
        return {}
    out: dict[str, str] = {}
    for tr in table.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            key = cells[0].rstrip(":").strip().lower()
            if key and key not in out:
                out[key] = cells[1].strip()
    return out


def _format_import_from_table(table: dict[str, str]) -> str:
    """Текст import_duty из таблицы TKS: пошлина / антидемпинг / акциз / НДС."""
    chunks: list[str] = []
    for key, label in _TKS_IMPORT_LABELS:
        val = table.get(key, "").strip()
        if val:
            chunks.append(f"{label}: {val}")
    return " | ".join(chunks)[:8000]


def parse_nontariff_from_table(table: dict[str, str]) -> list[dict[str, str]]:
    """Нетарифные меры из таблицы TKS — только для положительных флагов (да/есть)."""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for label, (mtype, doc, desc) in _TKS_FLAG_MAP.items():
        if label in table and _tks_flag_is_positive(table[label]):
            act = f"TKS.ru | {label.capitalize()}: {table[label]}"
            _add_spec(out, seen, mtype, desc, doc, act)
    return out


def _process_code_worker(
    code: str,
    *,
    timeout: float,
    playwright_page: Any | None,
    playwright_timeout_ms: int,
    http_client: httpx.Client | None = None,
) -> tuple[str, str, list[dict[str, str]], str, str]:
    """
    (code, status, specs, detail, import_text)
    status: ok | fail_http | skip_validate | skip_empty | skip_aggregate | skip_not_found
    """
    exp = _digits10(code)
    if not exp:
        return code, "skip_validate", [], "некорректный код", ""
    if _is_aggregate_hs10(exp):
        _dbg(f"Код {exp} — агрегат уровня группы (...000000), не конечная позиция TKS, пропускаем.")
        return code, "skip_aggregate", [], "агрегат …000000, не /tree/c…", ""
    with _HTTP_FETCH_SEMAPHORE:
        _dbg(f"Запрос к TKS запланирован hs_code={exp}: входим в сетевой слот.")
        time.sleep(random.uniform(0.8, 1.8))
        if playwright_page is not None:
            html, used_url, fetch_note = _fetch_tks_playwright(
                playwright_page, code, timeout_ms=playwright_timeout_ms
            )
        else:
            if http_client is None:
                return code, "fail_http", [], "внутренняя ошибка: нет HTTP client", ""
            html, used_url, fetch_note = _fetch_tks_info_ajax(code, timeout=timeout, client=http_client)
            if not html and fetch_note in ("network", "http_error"):
                _dbg(f"hs_code={exp}: AJAX путь не дал результата ({fetch_note}), пробую legacy URL.")
                html, used_url, fetch_note = _fetch_tks_urls(code, timeout=timeout, client=http_client)
    if fetch_note == "not_found":
        print(f"Код {exp} не является конечным, пропускаем...", flush=True)
        return code, "skip_not_found", [], used_url or "", ""
    if fetch_note == "blocked":
        return code, "fail_http", [], f"anti-bot блок ({used_url})", ""
    if not html:
        return code, "fail_http", [], f"ошибка доступа к коду {exp} ({fetch_note or 'no_html'}) url={used_url}", ""
    try:
        soup = _soup_from_tks_html(html)
        page_code = _page_code_tree(soup, exp)
        if page_code != exp:
            return (
                code,
                "skip_validate",
                [],
                f"код на странице={page_code!r}, ожидали={exp!r} url={used_url}",
                "",
            )
        # Приоритет — структурная таблица актуальной вёрстки TKS.
        table = parse_product_info_table(soup)
        if table:
            import_text = _format_import_from_table(table)
            specs = parse_nontariff_from_table(table)
        else:
            # Legacy-эвристика по блокам (на случай старой/иной вёрстки).
            imp_block = _import_block_text(soup)
            nt_block = _nontariff_block_text(soup)
            ex_block = _extra_info_block_text(soup)
            import_text = _format_import_for_commodity(imp_block)
            specs = parse_nontariff_regulation_block(nt_block) + parse_additional_info_block(ex_block)
        if not specs and not import_text.strip():
            return code, "skip_empty", [], "нет данных в блоках Импорт / Нетарифное / Дополнительная информация", ""
        return code, "ok", specs, "", import_text
    except Exception as e:
        return code, "skip_validate", [], f"ошибка парсинга {type(e).__name__}: {e!r}", ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Справка по товару TKS.ru → import_duty + non_tariff_measures.",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--missing-only", action="store_true", help="Главы без строк в non_tariff_measures")
    g.add_argument("--chapters", type=str, default="", metavar="NN,...", help="Список глав через запятую")
    g.add_argument("--all-chapters", action="store_true", help="Главы 01–97")
    ap.add_argument("--limit-per-chapter", type=int, default=0, metavar="N", help="Макс. кодов на главу (0 = все)")
    ap.add_argument("--max-total-codes", type=int, default=0, metavar="N", help="Остановка после N кодов")
    ap.add_argument(
        "--timeout",
        type=float,
        default=HTTP_TIMEOUT_SEC,
        help=f"Таймаут HTTP (httpx), с. По умолчанию {HTTP_TIMEOUT_SEC:g} (не больше жёсткого лимита).",
    )
    ap.add_argument(
        "--playwright-timeout",
        type=int,
        default=90000,
        metavar="MS",
        help="Таймаут навигации Playwright (--headful), мс",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=4,
        metavar="N",
        help=f"Потоков обработки. Сетевой параллелизм ограничен до {MAX_HTTP_CONCURRENCY}. При --headful принудительно 1.",
    )
    ap.add_argument(
        "--proxy",
        type=str,
        default="",
        metavar="URL",
        help="Прокси для доступа к TKS (пример: http://user:pass@host:port).",
    )
    ap.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Не проверять доступность TKS перед запуском.",
    )
    ap.add_argument("--headful", action="store_true", help="Chromium с окном, Playwright")
    ap.add_argument("--dry-run", action="store_true", help="Не писать в БД")
    args = ap.parse_args(argv)

    if args.missing_only:
        chapters = _missing_chapters()
        if not chapters:
            _dbg("Нет глав для докачки: по всем главам с кодами в каталоге уже есть non_tariff_measures.")
            return 0
    elif args.all_chapters:
        chapters = list(EXPECTED_CHAPTERS)
    else:
        chapters = []
        for c in (args.chapters or "").split(","):
            s = re.sub(r"\D", "", c.strip())[:2]
            if len(s) == 2:
                chapters.append(s)

    if not chapters:
        print("Нет глав для обработки.", file=sys.stderr)
        return 2

    limit_ch = int(args.limit_per_chapter or 0)
    max_total = int(args.max_total_codes or 0)
    workers = 1 if args.headful else max(1, int(args.workers))

    pw = None
    browser = None
    page = None
    http_client = _make_http_client(timeout_sec=min(float(args.timeout), HTTP_TIMEOUT_SEC), proxy=args.proxy)
    if args.headful:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("Установите: pip3 install playwright && playwright install chromium", file=sys.stderr)
            try:
                http_client.close()
            except Exception:
                pass
            return 2
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False)
        pw_headers = _tks_http_headers()
        ctx = browser.new_context(
            user_agent=pw_headers["User-Agent"],
            locale="ru-RU",
            extra_http_headers={k: v for k, v in pw_headers.items() if k != "User-Agent"},
        )
        page = ctx.new_page()
    elif not args.skip_preflight:
        ok, reason = _preflight_tks(http_client)
        if not ok:
            print(
                "TKS недоступен до старта основного цикла: "
                f"{reason}. Попробуйте VPN/прокси (--proxy) или повторите позже.",
                file=sys.stderr,
                flush=True,
            )
            try:
                http_client.close()
            except Exception:
                pass
            return 3

    processed = 0
    inserted_like = 0
    http_ok = 0
    http_fail = 0
    skipped_validate = 0
    skipped_empty = 0
    skipped_aggregate = 0
    skipped_not_found = 0
    import_updates = 0

    print("Установлены заголовки реального браузера (Anti-Bot: ON)", flush=True)

    _dbg(
        "СТАРТ sync_tks_nontariff: главы="
        + ", ".join(chapters)
        + (f" | лимит/глава: {limit_ch}" if limit_ch else "")
        + (f" | max кодов: {max_total}" if max_total else "")
        + f" | workers={workers}"
        + (" | Playwright headful" if args.headful else " | HTTP (httpx)")
        + f" | HTTP timeout={float(args.timeout):g}s (cap {HTTP_TIMEOUT_SEC:g}s)"
        + f" | retries/url={HTTP_RETRIES_PER_URL}"
        + f" | net_concurrency={MAX_HTTP_CONCURRENCY}"
        + (" | proxy=ON" if (args.proxy or "").strip() else " | proxy=OFF")
    )

    stop_all = False
    try:
        with SessionLocal() as db:
            for ch in chapters:
                if stop_all:
                    break
                if max_total and processed >= max_total:
                    stop_all = True
                    break
                _dbg(f"Начинаю парсинг главы {ch} …")
                q = db.query(Commodity.code).filter(Commodity.code.like(f"{ch}%")).order_by(Commodity.code)
                raw_codes = [r[0] for r in q.all()]
                n_raw = len(raw_codes)
                codes = [c for c in raw_codes if (d := _digits10(str(c))) and not _is_aggregate_hs10(d)]
                if n_raw > len(codes):
                    _dbg(f"Глава {ch}: убраны агрегаты ...000000 из каталога: было {n_raw}, осталось {len(codes)}")
                if limit_ch:
                    codes = codes[:limit_ch]
                _dbg(f"Глава {ch}: в каталоге кодов к обходу: {len(codes)}")

                def handle_result(c: str, st: str, specs: list[dict[str, str]], detail: str, imp_txt: str) -> None:
                    nonlocal http_ok, http_fail, skipped_validate, skipped_empty, skipped_aggregate
                    nonlocal skipped_not_found, inserted_like, import_updates
                    if st == "fail_http":
                        http_fail += 1
                        _dbg(f"fail_http hs_code={c} detail={detail}")
                        return
                    if st == "skip_aggregate":
                        skipped_aggregate += 1
                        _dbg(f"skip_aggregate hs_code={c}")
                        return
                    if st == "skip_not_found":
                        skipped_not_found += 1
                        _dbg(f"skip_not_found hs_code={c} url={detail}")
                        return
                    if st == "skip_validate":
                        skipped_validate += 1
                        _dbg(f"skip_validate hs_code={c}: {detail}")
                        return
                    if st == "skip_empty":
                        skipped_empty += 1
                        _dbg(f"skip_empty hs_code={c}: {detail}")
                        return
                    http_ok += 1
                    _dbg(
                        f"Успешно обработан hs_code={c}: мер={len(specs)}, import_duty={'да' if imp_txt.strip() else 'нет'}"
                    )
                    try:
                        if imp_txt.strip():
                            import_updates += 1
                            if args.dry_run:
                                print(f"DRY import_duty {c}: {imp_txt[:120]}...", flush=True)
                            else:
                                _update_commodity_import(db, c, imp_txt)
                        for spec in specs:
                            inserted_like += 1
                            if args.dry_run:
                                print(
                                    f"DRY {c} [{spec['measure_type']}] {spec['regulatory_act'][:70]}",
                                    flush=True,
                                )
                            else:
                                _merge_measure(db, c, spec)
                        if not args.dry_run:
                            db.commit()
                    except Exception as e:
                        http_fail += 1
                        _dbg(f"Ошибка записи в БД hs_code={c}: {type(e).__name__}: {e!r}")
                        if not args.dry_run:
                            try:
                                db.rollback()
                            except Exception:
                                pass

                if workers == 1:
                    for code in codes:
                        if max_total and processed >= max_total:
                            _dbg("Достигнут --max-total-codes.")
                            if not args.dry_run:
                                db.commit()
                            stop_all = True
                            break
                        _dbg(f"Глава {ch}: обрабатываю hs_code={code} ({processed + 1}/{len(codes) if not max_total else '?'})")
                        c, st, specs, detail, imp_txt = _process_code_worker(
                            code,
                            timeout=min(float(args.timeout), HTTP_TIMEOUT_SEC),
                            playwright_page=page,
                            playwright_timeout_ms=int(args.playwright_timeout),
                            http_client=http_client,
                        )
                        processed += 1
                        handle_result(c, st, specs, detail, imp_txt)
                else:
                    idx = 0
                    pool = ThreadPoolExecutor(max_workers=workers)
                    futures: dict[Any, str] = {}
                    try:
                        while idx < len(codes) or futures:
                            if max_total and processed >= max_total:
                                for f in list(futures.keys()):
                                    f.cancel()
                                futures.clear()
                                stop_all = True
                                break
                            while idx < len(codes) and len(futures) < workers:
                                if max_total and processed + len(futures) >= max_total:
                                    break
                                c0 = codes[idx]
                                idx += 1
                                _dbg(f"Глава {ch}: в очередь worker hs_code={c0}")
                                fut = pool.submit(
                                    _process_code_worker,
                                    c0,
                                    timeout=min(float(args.timeout), HTTP_TIMEOUT_SEC),
                                    playwright_page=None,
                                    playwright_timeout_ms=int(args.playwright_timeout),
                                    http_client=http_client,
                                )
                                futures[fut] = c0
                            if not futures:
                                break
                            done, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)
                            for fut in done:
                                c_pending = futures.pop(fut, None)
                                try:
                                    c, st, specs, detail, imp_txt = fut.result()
                                except Exception as exc:
                                    _dbg(
                                        f"ERROR worker hs_code={c_pending or '?'}: "
                                        f"{type(exc).__name__}: {exc!r}"
                                    )
                                    processed += 1
                                    http_fail += 1
                                    continue
                                processed += 1
                                handle_result(c, st, specs, detail, imp_txt)
                                if max_total and processed >= max_total:
                                    stop_all = True
                                    for f in list(futures.keys()):
                                        f.cancel()
                                    futures.clear()
                                    break
                            if stop_all:
                                break
                    finally:
                        try:
                            pool.shutdown(wait=False, cancel_futures=True)
                        except TypeError:
                            pool.shutdown(wait=False)

                if stop_all:
                    break
                if not args.dry_run:
                    db.commit()
                _dbg(f"Глава {ch}: фиксация в БД выполнена, итого обработано кодов с начала запуска: {processed}")
    finally:
        try:
            http_client.close()
        except Exception:
            pass
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass

    _dbg(
        "ГОТОВО sync_tks_nontariff: "
        f"ok={http_ok}, fail={http_fail}, skip_validate={skipped_validate}, "
        f"skip_empty={skipped_empty}, skip_aggregate={skipped_aggregate}, "
        f"skip_not_found={skipped_not_found}, import_duty_обновлений={import_updates}, "
        f"кодов={processed}, upsert_nt={inserted_like}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
