#!/usr/bin/env python3
"""
Загрузка с https://ifcg.ru/kb/tnved/<10-значный-код>/ в ``declaration_examples`` и
``preliminary_decisions`` (один HTTP GET на код: примеры декларирования + блок решений по классификации).

Требует: ``httpx``, ``beautifulsoup4``. Запуск из ``customs-clear/backend``::

  PYTHONPATH=. python3 scripts/sync_ifcg_examples.py --code 6404110000
  PYTHONPATH=. python3 scripts/sync_ifcg_examples.py --chapter 64 --max-codes 50
  PYTHONPATH=. python3 scripts/sync_ifcg_examples.py --chapter 6404 --dry-run
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
from sqlalchemy import func

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models.core import DeclarationExample, PreliminaryDecision  # noqa: E402
from app.models.tnved import Commodity  # noqa: E402

IFCG_BASE = "https://ifcg.ru/kb/tnved"
UA_POOL = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
)


def _norm_hs_10(raw: str) -> str | None:
    d = re.sub(r"\D", "", (raw or "").strip())[:10]
    if len(d) != 10 or not d.isdigit():
        return None
    return d


def _chapter_digits(ch: str) -> str:
    return re.sub(r"\D", "", (ch or "").strip())


def _parse_tnv_sample_row_div(div: Tag) -> tuple[str, str] | None:
    """Строка ``div.row.row-in.tnv-samples``: код в ``span.h4``, текст в колонке описания."""
    classes = div.get("class") or []
    if "tnv-samples" not in classes:
        return None
    hs_el = div.select_one("span.h4")
    if not hs_el:
        return None
    desc_el = div.select_one("div.col-lg-10") or div.select_one("div.col-md-8")
    if not desc_el:
        return None
    hs = re.sub(r"\D", "", hs_el.get_text(" ", strip=True))[:10]
    desc = desc_el.get_text(" ", strip=True)
    if len(hs) != 10 or not hs.isdigit():
        return None
    if len(desc) < 12:
        return None
    return (hs, desc)


def _collect_tnv_rows_after_h2(soup: BeautifulSoup, h2_el: Tag | None) -> list[tuple[str, str]]:
    if not h2_el:
        return []
    out: list[tuple[str, str]] = []
    cur: Tag | NavigableString | None = h2_el.next_sibling
    while cur is not None:
        if isinstance(cur, NavigableString):
            cur = cur.next_sibling
            continue
        if not isinstance(cur, Tag):
            break
        if cur.name == "h2":
            break
        if cur.name == "div":
            row = _parse_tnv_sample_row_div(cur)
            if row:
                out.append(row)
        cur = cur.next_sibling
    return out


def _find_predecisions_h2(soup: BeautifulSoup) -> Tag | None:
    h2 = soup.find("h2", id="predecisions")
    if h2:
        return h2
    for cand in soup.find_all("h2"):
        t = " ".join((cand.get_text() or "").casefold().split())
        if "предварительн" in t and "классификац" in t:
            return cand
        if "решени" in t and "классификац" in t and "товар" in t:
            return cand
    return None


def parse_ifcg_tnved_page(html: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """
    Один проход HTML: примеры декларирования (``h2#stats``) и решения по классификации (``h2#predecisions`` и аналоги).
    Возвращает (примеры, предварительные_решения) — списки (hs_10, описание).
    """
    soup = BeautifulSoup(html, "html.parser")
    stats_h2 = soup.find("h2", id="stats")
    predecisions_h2 = _find_predecisions_h2(soup)
    if stats_h2 is None and predecisions_h2 is None:
        return [], []

    sample_rows = _collect_tnv_rows_after_h2(soup, stats_h2)
    pre_rows = _collect_tnv_rows_after_h2(soup, predecisions_h2)
    return sample_rows, pre_rows


def fetch_commodity_codes_for_chapter(session, chapter: str, *, limit: int) -> list[str]:
    ch = _chapter_digits(chapter)
    if not ch:
        return []
    q = (
        session.query(Commodity.code)
        .filter(Commodity.code.like(f"{ch}%"))
        .filter(func.length(Commodity.code) == 10)
        .distinct()
        .order_by(Commodity.code.asc())
    )
    if limit > 0:
        q = q.limit(limit)
    return [row[0] for row in q.all()]


def sync_one_code(client: httpx.Client, session, hs: str, *, dry_run: bool) -> tuple[int, int]:
    url = f"{IFCG_BASE}/{quote(hs, safe='')}/"
    r = client.get(url, timeout=60.0)
    r.raise_for_status()
    sample_rows, pred_rows = parse_ifcg_tnved_page(r.text)

    ins_samples = 0
    for hs_row, desc in sample_rows:
        desc = desc.strip()[:12_000]
        if not desc:
            continue
        exists = (
            session.query(DeclarationExample.id)
            .filter(
                DeclarationExample.hs_code == hs_row,
                DeclarationExample.description == desc,
                DeclarationExample.source == "ifcg",
            )
            .first()
        )
        if exists:
            continue
        if dry_run:
            ins_samples += 1
            continue
        session.add(DeclarationExample(hs_code=hs_row, description=desc, source="ifcg"))
        ins_samples += 1

    ins_pred = 0
    for hs_row, desc in pred_rows:
        desc = desc.strip()[:12_000]
        if not desc:
            continue
        exists = (
            session.query(PreliminaryDecision.id)
            .filter(
                PreliminaryDecision.hs_code == hs_row,
                PreliminaryDecision.description == desc,
                PreliminaryDecision.source == "ifcg",
            )
            .first()
        )
        if exists:
            continue
        if dry_run:
            ins_pred += 1
            continue
        session.add(PreliminaryDecision(hs_code=hs_row, description=desc, source="ifcg"))
        ins_pred += 1

    if dry_run:
        return ins_samples, ins_pred
    if ins_samples or ins_pred:
        session.commit()
    return ins_samples, ins_pred


def main() -> int:
    ap = argparse.ArgumentParser(description="IFCG.ru → declaration_examples + preliminary_decisions")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--code", type=str, help="10-значный код ТН ВЭД, например 6404110000")
    g.add_argument("--chapter", type=str, help="Префикс главы/группы, например 64 или 6404")
    ap.add_argument("--max-codes", type=int, default=0, help="Макс. кодов при --chapter (0 = все)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    codes: list[str] = []
    if args.code:
        hs = _norm_hs_10(args.code)
        if not hs:
            print("Ошибка: --code должен содержать ровно 10 цифр кода ТН ВЭД.", file=sys.stderr)
            return 2
        codes = [hs]
    else:
        ch = _chapter_digits(args.chapter)
        if not ch:
            print("Ошибка: некорректный --chapter.", file=sys.stderr)
            return 2
        if ch.startswith("77"):
            print(
                f"ПРОПУСК: глава {ch[:2]} в ТН ВЭД зарезервирована и не содержит данных IFCG.",
                flush=True,
            )
            return 0
        with SessionLocal() as s:
            codes = fetch_commodity_codes_for_chapter(s, ch, limit=max(0, int(args.max_codes)))
        if not codes:
            print(f"В tnved_commodities нет 10-значных кодов с префиксом «{ch}».", file=sys.stderr)
            return 3

    total_samples = 0
    total_pred = 0
    ua = random.choice(UA_POOL)
    with httpx.Client(headers={"User-Agent": ua}, follow_redirects=True, timeout=60.0) as client:
        with SessionLocal() as session:
            for i, hs in enumerate(codes, start=1):
                time.sleep(random.uniform(1.0, 3.0))
                try:
                    n_s, n_p = sync_one_code(client, session, hs, dry_run=args.dry_run)
                    total_samples += n_s
                    total_pred += n_p
                    print(
                        f"[{i}/{len(codes)}] {hs}: добавлено {n_s} примеров, {n_p} предв. решений",
                        flush=True,
                    )
                except Exception as e:
                    print(f"[{i}/{len(codes)}] {hs}: ошибка {e}", file=sys.stderr, flush=True)
                    session.rollback()

    print(
        f"Готово. Новых примеров: {total_samples}, предв. решений: {total_pred} (dry_run={args.dry_run})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
