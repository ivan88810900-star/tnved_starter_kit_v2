#!/usr/bin/env python3
"""
Попытка загрузить официальные ставки РОП с publication.pravo.gov.ru;
при недоступности — генерация из встроенных таблиц ПП №1041.

Запуск из customs-clear/backend::

  PYTHONPATH=. python3 scripts/fetch_rop_rates.py
  PYTHONPATH=. python3 scripts/fetch_rop_rates.py --force-build
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

OUTPUT = _ROOT / "data" / "rop_rates_2024.json"
PRAVO_API = "http://publication.pravo.gov.ru/api/Documents?numberDoc=1041&yearDoc=2024"
PRAVO_DOC = "http://publication.pravo.gov.ru/Document/View/0001202408010030"
TIMEOUT = 25


def _fetch_url(url: str) -> str | None:
    try:
        req = Request(url, headers={"User-Agent": "tnved-rop-fetch/1.0"})
        with urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as exc:
        print(f"WARN: fetch failed {url}: {exc}")
        return None


def _probe_pravo() -> dict[str, Any]:
    meta: dict[str, Any] = {"api_ok": False, "doc_ok": False, "matched_groups": 0}
    api_body = _fetch_url(PRAVO_API)
    if api_body:
        try:
            data = json.loads(api_body)
            items = data if isinstance(data, list) else data.get("items") or data.get("documents") or []
            meta["api_ok"] = bool(items)
            meta["api_items"] = len(items) if isinstance(items, list) else 0
        except json.JSONDecodeError:
            meta["api_ok"] = False

    doc_body = _fetch_url(PRAVO_DOC)
    if doc_body:
        meta["doc_ok"] = "1041" in doc_body or "экологическ" in doc_body.lower()
        meta["matched_groups"] = len(re.findall(r"Группа\s+N\s+\d+", doc_body, flags=re.IGNORECASE))

    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch / build ROP rates JSON")
    ap.add_argument("--force-build", action="store_true", help="Skip fetch, rebuild from PP 1041 tables")
    args = ap.parse_args()

    if not args.force_build:
        print("Probing publication.pravo.gov.ru …")
        probe = _probe_pravo()
        print(json.dumps(probe, ensure_ascii=False, indent=2))
        if probe.get("doc_ok") or probe.get("api_ok"):
            print("NOTE: pravo.gov.ru reachable; structured parse not implemented — using embedded PP 1041 tables.")

    from scripts.build_rop_rates_json import main as build_main  # noqa: WPS433

    build_main()
    print(f"OK: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
