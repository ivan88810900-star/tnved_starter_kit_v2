#!/usr/bin/env python3
"""
Сбор фрагментов «Справки по товару» (в духе alta.ru/tnved/code/…) в geo_special_duties.

  cd customs-clear/backend
  alembic upgrade head
  python3 scripts/sync_geo_regulations.py [--codes 3304,8457,01] [--dry-run] [--no-llm]

Требуется сеть. Для разбора списков стран — GEMINI_API_KEY / GOOGLE_API_KEY и пакет google-generativeai.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import httpx
from bs4 import BeautifulSoup

from app.db import SessionLocal
from app.models.core import TnvedEntry
from app.models.tnved import Commodity
from app.services.invoice_analyzer import _parse_countries_with_llm
from app.services.normative_store import upsert_geo_special_duty

ALTA_CODE_URL = "https://www.alta.ru/tnved/code/{code}/"
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/125.0 Safari/537.36",
]

BLOCK_MARKERS: tuple[tuple[str, str], ...] = (
    ("специальные экономические меры", "mixed"),
    ("запрет на ввоз", "embargo"),
    (
        "ставки ввозных таможенных пошлин в отношении товаров из недружественных стран",
        "increased_duty",
    ),
    ("ставки ввозных таможенных пошлин", "increased_duty"),
)

_DECREE_RE = re.compile(
    r"ПП\s*РФ\s*от\s*(\d{2}\.\d{2}\.\d{4})\s*№\s*(\d+)",
    re.IGNORECASE,
)
_RATE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_PREFIX_IN_TEXT_RE = re.compile(r"\b(\d{4,10})\b")


def _default_codes() -> list[str]:
    """
    Боевой default: берем валидные HS10 из локальной БД (по 2 кода на главу),
    а не коды глав вида `85`, которые на Alta часто дают 404.
    """
    codes = _codes_from_db(limit_per_chapter=2)
    return codes or _all_chapter_codes()


def _all_chapter_codes() -> list[str]:
    return [f"{i:02d}" for i in range(1, 98)]


def _is_terminal_hs10(raw: str) -> bool:
    code = re.sub(r"\D", "", str(raw or ""))[:10]
    return len(code) == 10 and not code.endswith("000000")


def _codes_from_db(limit_per_chapter: int = 2) -> list[str]:
    grouped: dict[str, list[str]] = defaultdict(list)
    with SessionLocal() as db:
        for hs_code, chapter in db.query(TnvedEntry.hs_code, TnvedEntry.chapter).all():
            code = re.sub(r"\D", "", str(hs_code or ""))[:10]
            if not _is_terminal_hs10(code):
                continue
            ch = (str(chapter or "")[:2] or code[:2]).zfill(2)
            if code not in grouped[ch]:
                grouped[ch].append(code)
        if not grouped:
            for (code_raw,) in db.query(Commodity.code).all():
                code = re.sub(r"\D", "", str(code_raw or ""))[:10]
                if not _is_terminal_hs10(code):
                    continue
                ch = code[:2]
                if code not in grouped[ch]:
                    grouped[ch].append(code)
    out: list[str] = []
    for ch in sorted(grouped):
        out.extend(sorted(grouped[ch])[: max(1, limit_per_chapter)])
    return out


def _fetch(url: str, *, timeout: float, retries: int = 3) -> tuple[str | None, int]:
    last_status = 0
    err: Exception | None = None
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for i in range(1, max(1, retries) + 1):
            try:
                r = client.get(
                    url,
                    headers={
                        "User-Agent": random.choice(USER_AGENTS),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                    },
                )
                last_status = int(r.status_code or 0)
                if r.status_code == 200:
                    return r.text, last_status
                if r.status_code in (403, 429, 500, 502, 503, 504) and i < retries:
                    time.sleep(min(1.0 * i, 5.0))
                    continue
                return None, last_status
            except Exception as e:
                err = e
                if i >= retries:
                    break
                time.sleep(min(1.0 * i, 5.0))
    if err is not None:
        print(f"WARN fetch error {url}: {err}", flush=True)
    return None, last_status


def _infer_measure_type(section_hint: str, body: str) -> str:
    t = (section_hint + " " + body[:4000]).lower()
    if "запрет" in t and "ввоз" in t:
        return "embargo"
    if "антидемпинг" in t:
        return "anti_dumping"
    if "преференц" in t or "льготн" in t:
        return "preference"
    if "недружествен" in t or "ставки" in t or "пошлин" in t:
        return "increased_duty"
    if section_hint == "mixed":
        if "запрет" in t:
            return "embargo"
        return "increased_duty"
    return "increased_duty"


def _split_blocks(full_text: str) -> list[tuple[str, str, str]]:
    """Возвращает (нижний ключ секции, фрагмент текста, подсказка типа из маркера)."""
    lower = full_text.lower()
    hits: list[tuple[int, str, str]] = []
    for needle, hint in BLOCK_MARKERS:
        pos = 0
        while True:
            i = lower.find(needle, pos)
            if i == -1:
                break
            hits.append((i, needle, hint))
            pos = i + len(needle)
    hits.sort(key=lambda x: x[0])
    blocks: list[tuple[str, str, str]] = []
    for j, (start, needle, hint) in enumerate(hits):
        end = hits[j + 1][0] if j + 1 < len(hits) else min(len(full_text), start + 6000)
        blocks.append((needle, full_text[start:end], hint))
    return blocks


def _extract_decrees(text: str) -> list[str]:
    out: list[str] = []
    for m in _DECREE_RE.finditer(text):
        out.append(f"ПП РФ от {m.group(1)} № {m.group(2)}")
    return sorted(set(out)) or ["(основание не распознано — проверьте вручную)"]


def _extract_rate(text: str) -> float:
    m = _RATE_RE.search(text)
    if not m:
        return 0.0
    return float(m.group(1).replace(",", "."))


def _prefixes_for_page(page_code: str, body: str) -> list[str]:
    p = re.sub(r"\D", "", page_code)[:10]
    found = sorted(
        {re.sub(r"\D", "", x)[:10] for x in _PREFIX_IN_TEXT_RE.findall(body)},
        key=len,
        reverse=True,
    )
    if p:
        acc = [p]
        for x in found:
            if x.startswith(p) or p.startswith(x[: min(len(p), len(x))]):
                if x not in acc:
                    acc.append(x)
        for x in found:
            if len(x) >= 4 and x not in acc:
                acc.append(x)
        return acc[:12]
    return [x for x in found if len(x) >= 4][:8] or ["0000"]


def _countries_for_block(body: str, *, use_llm: bool) -> list[str]:
    if use_llm:
        return _parse_countries_with_llm(body[:6000])
    if "недружествен" in body.lower() or "сша" in body.lower() or "ес" in body.lower():
        return ["ALL_UNFRIENDLY"]
    return []


def sync_code(
    code: str,
    *,
    dry_run: bool,
    use_llm: bool,
    sleep_s: float,
) -> int:
    url = ALTA_CODE_URL.format(code=re.sub(r"\D", "", code))
    html, status = _fetch(url, timeout=40.0)
    time.sleep(sleep_s)
    if not html:
        print(f"SKIP fetch: status={status} url={url}", flush=True)
        return 0
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    if len(text) < 80:
        return 0
    n = 0
    for _needle, body, hint in _split_blocks(text):
        if hint == "embargo":
            mt = "embargo"
        elif hint == "increased_duty":
            mt = "increased_duty"
        else:
            mt = _infer_measure_type("mixed", body)
        decs = _extract_decrees(body)
        rate = _extract_rate(body)
        if mt == "embargo":
            rate = 0.0
        elif rate <= 0.0 and mt in ("increased_duty", "anti_dumping"):
            rate = 35.0
        prefs = _prefixes_for_page(code, body)
        countries = _countries_for_block(body, use_llm=use_llm)
        if not countries:
            countries = ["ALL_UNFRIENDLY"] if mt != "preference" else []
        if not countries:
            continue
        doc_link = url
        for basis in decs:
            for pref in prefs:
                for ciso in countries:
                    if dry_run:
                        print(
                            f"DRY {mt} pref={pref} {ciso} rate={rate} {basis[:80]}",
                            flush=True,
                        )
                    else:
                        upsert_geo_special_duty(
                            hs_code_prefix=pref,
                            country_iso=ciso,
                            duty_rate=rate,
                            document_basis=basis[:512],
                            measure_type=mt,
                            document_link=doc_link[:2000],
                        )
                    n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Синхронизация geo_special_duties из публичных справок по коду ТН ВЭД.")
    ap.add_argument(
        "--codes",
        type=str,
        default="",
        help="Список кодов через запятую (если не указан, обход глав 01–97).",
    )
    ap.add_argument(
        "--all-chapters",
        action="store_true",
        help="Явно включить fallback-обход глав ТН ВЭД 01–97 (если нет кодов в БД).",
    )
    ap.add_argument(
        "--all-hs10",
        action="store_true",
        help="Обойти все терминальные HS10 из БД (долго).",
    )
    ap.add_argument(
        "--quick",
        action="store_true",
        help="Быстрый сокращенный прогон (несколько типовых кодов) для отладки.",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="Не вызывать Gemini; для стран использовать ALL_UNFRIENDLY.")
    ap.add_argument("--sleep", type=float, default=0.35, help="Пауза между HTTP-запросами, с.")
    args = ap.parse_args(argv)
    if args.codes.strip():
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        if args.quick:
            codes = ["3304990000", "8471300000", "8517110000", "8517620009", "9504500001"]
        else:
            if args.all_hs10:
                codes = _codes_from_db(limit_per_chapter=10_000)
            else:
                codes = list(_default_codes())
            if args.all_chapters:
                seen = set(codes)
                for c in _all_chapter_codes():
                    if c not in seen:
                        codes.append(c)
                        seen.add(c)
    total = 0
    for c in codes:
        total += sync_code(
            c,
            dry_run=bool(args.dry_run),
            use_llm=not bool(args.no_llm),
            sleep_s=float(args.sleep),
        )
    print(f"OK: обработано вставок/обновлений (счётчик попыток upsert): {total}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
