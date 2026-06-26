#!/usr/bin/env python3
"""
Синхронизация country_specific_rules из CSV/JSON (локально или по URL).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.core import CountrySpecificRule
from app.services.normative_store import append_sync_log, init_db
from app.services.preview_cache_revision import bump_preview_cache_revision


def _http_get(url: str, *, timeout_sec: float = 40.0, retries: int = 4) -> str:
    err: Exception | None = None
    with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
        for i in range(1, max(1, retries) + 1):
            try:
                r = client.get(url, headers={"User-Agent": "customs-clear-country-rules-sync/1.0"})
                if r.status_code in (429, 500, 502, 503, 504) and i < retries:
                    time.sleep(min(1.2 * i, 8.0))
                    continue
                r.raise_for_status()
                return r.text
            except Exception as e:
                err = e
                if i >= retries:
                    break
                time.sleep(min(1.2 * i, 8.0))
    raise RuntimeError(f"Country rules download failed: {err!r}")


def _norm_country(raw: Any) -> str:
    s = re.sub(r"[^A-Za-z]", "", str(raw or "").upper())[:8]
    return s


def _norm_rule_type(raw: Any) -> str:
    t = str(raw or "").strip().lower()
    if t in {"docs_control", "embargo", "enhanced_due_diligence", "licensing", "other"}:
        return t
    if "контрол" in t or "doc" in t:
        return "docs_control"
    if "лиценз" in t:
        return "licensing"
    if "embargo" in t or "запрет" in t:
        return "embargo"
    if "due" in t or "проверк" in t:
        return "enhanced_due_diligence"
    return "other"


def _parse_rows(text: str) -> list[dict[str, str]]:
    stripped = text.lstrip()
    rows: list[dict[str, str]] = []
    if stripped.startswith("{") or stripped.startswith("["):
        payload = json.loads(text)
        if isinstance(payload, dict):
            arr = payload.get("items") or payload.get("data") or payload.get("country_specific_rules") or []
        elif isinstance(payload, list):
            arr = payload
        else:
            arr = []
        for it in arr:
            if isinstance(it, dict):
                rows.append({str(k).lower(): str(v or "").strip() for k, v in it.items()})
    else:
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        for r in reader:
            rows.append({str(k or "").strip().lower(): str(v or "").strip() for k, v in r.items() if k})
    out: list[dict[str, str]] = []
    for r in rows:
        cc = _norm_country(r.get("country_code") or r.get("country") or r.get("iso") or r.get("код"))
        rt = _norm_rule_type(r.get("rule_type") or r.get("type") or r.get("тип"))
        desc = str(r.get("description") or r.get("note") or r.get("описание") or "").strip()
        if not (cc and desc):
            continue
        out.append({"country_code": cc, "rule_type": rt, "description": desc[:4000]})
    return out


def _default_seed_rows() -> list[dict[str, str]]:
    return [
        {
            "country_code": "US",
            "rule_type": "enhanced_due_diligence",
            "description": "Усиленная проверка контрагента и назначения товара; подтверждение non-military end-use.",
        },
        {
            "country_code": "US",
            "rule_type": "docs_control",
            "description": "Требуется расширенный пакет подтверждающих документов происхождения и конечного получателя.",
        },
        {
            "country_code": "EU",
            "rule_type": "docs_control",
            "description": "Требуется углубленная документальная проверка на предмет ограничений dual-use и экспортного контроля.",
        },
        {
            "country_code": "GB",
            "rule_type": "enhanced_due_diligence",
            "description": "Усиленный комплаенс-контроль по санкционным ограничениям UK.",
        },
        {
            "country_code": "JP",
            "rule_type": "docs_control",
            "description": "Дополнительная проверка разрешительной документации и конечного использования товара.",
        },
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="Синхронизация country_specific_rules из CSV/JSON")
    ap.add_argument("--input", type=Path, default=None, help="Локальный .csv/.json")
    ap.add_argument("--url", type=str, default="", help="URL .csv/.json")
    ap.add_argument(
        "--seed-default",
        action="store_true",
        help="Заполнить базовыми встроенными правилами (fallback)",
    )
    args = ap.parse_args()

    init_db()
    url = (args.url or os.getenv("COUNTRY_RULES_SYNC_URL") or "").strip()
    rows: list[dict[str, str]] | None = None
    source_mode = "seed_default"
    if args.input is not None and args.input.exists():
        text = args.input.read_text(encoding="utf-8", errors="replace")
        source_mode = "file"
        rows = _parse_rows(text)
    elif url:
        text = _http_get(url)
        source_mode = "url"
        rows = _parse_rows(text)
    elif args.seed_default:
        rows = _default_seed_rows()
    else:
        # Fallback для first-run, чтобы комплаенс-пайплайн не оставался пустым.
        rows = _default_seed_rows()
    if rows is None:
        rows = []
    with SessionLocal() as db:
        db.execute(delete(CountrySpecificRule))
        for r in rows:
            db.add(
                CountrySpecificRule(
                    country_code=r["country_code"],
                    rule_type=r["rule_type"],
                    description=r["description"],
                )
            )
        db.commit()

    note = f"rows={len(rows)}; source={source_mode}"
    append_sync_log("country_specific_rules", "ok" if rows else "partial", "v1", len(rows), note[:2000])
    try:
        bump_preview_cache_revision("sync_country_rules")
    except Exception:
        pass
    print(f"country_specific_rules rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
