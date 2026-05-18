#!/usr/bin/env python3
"""
Синхронизация sanction_import_risks (полная загрузка без тестовых лимитов).

Источники:
1) --input FILE (.csv/.json)
2) --url URL
3) SANCTION_RISKS_SYNC_URL (env)

Если источники не указаны, можно собрать базовый слой из geo_special_duties (embargo/anti_dumping):
  --from-geo
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.core import GeoSpecialDuty, SanctionImportRisk
from app.services.normative_store import append_sync_log, init_db
from app.services.preview_cache_revision import bump_preview_cache_revision


def _norm_prefix(raw: Any) -> str:
    return re.sub(r"\D", "", str(raw or "").strip())[:10]


def _norm_level(raw: Any) -> str:
    v = str(raw or "").strip().lower()
    if v in {"forbidden", "ban", "risk", "warn", "safe", "ok"}:
        return v
    if "запрет" in v:
        return "forbidden"
    if "безопас" in v:
        return "safe"
    return "risk"


def _load_rows_from_csv(text: str) -> list[dict[str, str]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    out: list[dict[str, str]] = []
    for row in reader:
        out.append({str(k or "").strip().lower(): str(v or "").strip() for k, v in row.items() if k})
    return out


def _normalize_input_rows(raw_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in raw_rows:
        hs = _norm_prefix(
            r.get("hs_code_prefix")
            or r.get("hs_prefix")
            or r.get("commodity_code")
            or r.get("tnved")
            or r.get("код")
        )
        if len(hs) < 4:
            continue
        jur = (
            str(
                r.get("jurisdiction")
                or r.get("source")
                or r.get("list")
                or r.get("юрисдикция")
                or "GLOBAL"
            )
            .strip()
            .upper()[:8]
        )
        desc = str(
            r.get("description")
            or r.get("note")
            or r.get("details")
            or r.get("описание")
            or ""
        ).strip()
        if not desc:
            desc = f"Ограничения/риски по коду ТН ВЭД {hs}"
        lvl = _norm_level(r.get("risk_level") or r.get("level") or r.get("status"))
        out.append(
            {
                "hs_code_prefix": hs,
                "jurisdiction": jur,
                "risk_level": lvl,
                "description": desc[:4000],
            }
        )
    return out


def _rows_from_geo_special() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    with SessionLocal() as db:
        rows = db.query(GeoSpecialDuty).all()
    for r in rows:
        hs = _norm_prefix(r.hs_code_prefix or "")
        if len(hs) < 4:
            continue
        mt = (r.measure_type or "").strip().lower()
        if mt not in {"embargo", "anti_dumping", "increased_duty"}:
            continue
        if mt == "embargo":
            lvl = "forbidden"
        elif mt == "anti_dumping":
            lvl = "risk"
        else:
            lvl = "warn"
        out.append(
            {
                "hs_code_prefix": hs,
                "jurisdiction": "RU",
                "risk_level": lvl,
                "description": (
                    f"{(r.document_basis or '').strip()} | measure_type={mt} | country={r.country_iso or 'ALL'}"
                )[:4000],
            }
        )
    return out


def _read_external_rows(path: Path | None, url: str | None) -> list[dict[str, str]]:
    text = ""
    if path is not None:
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                rows = payload.get("items") or payload.get("data") or payload.get("sanction_import_risks") or []
            elif isinstance(payload, list):
                rows = payload
            else:
                rows = []
            normalized = []
            for r in rows:
                if isinstance(r, dict):
                    normalized.append({str(k).lower(): str(v) for k, v in r.items()})
            return _normalize_input_rows(normalized)
    if url:
        with httpx.Client(timeout=90.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            text = resp.text
    if not text:
        return []
    return _normalize_input_rows(_load_rows_from_csv(text))


def main() -> int:
    ap = argparse.ArgumentParser(description="Синхронизация sanction_import_risks (полная загрузка)")
    ap.add_argument("--input", type=Path, default=None, help="Локальный .csv/.json файл с рисками")
    ap.add_argument("--url", type=str, default="", help="URL .csv/.json с рисками")
    ap.add_argument("--from-geo", action="store_true", help="Построить слой рисков из geo_special_duties")
    args = ap.parse_args()

    init_db()
    source_url = (args.url or os.getenv("SANCTION_RISKS_SYNC_URL") or "").strip()

    rows: list[dict[str, str]] = []
    if args.input is not None or source_url:
        rows = _read_external_rows(args.input, source_url)
    used_geo = bool(args.from_geo or not rows)
    if used_geo:
        rows.extend(_rows_from_geo_special())

    dedup: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for r in rows:
        key = (
            r["hs_code_prefix"],
            r["jurisdiction"],
            r["risk_level"],
            r["description"].strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)

    with SessionLocal() as db:
        db.execute(delete(SanctionImportRisk))
        for r in dedup:
            db.add(
                SanctionImportRisk(
                    hs_code_prefix=r["hs_code_prefix"],
                    jurisdiction=r["jurisdiction"],
                    risk_level=r["risk_level"],
                    description=r["description"],
                )
            )
        db.commit()

    note = f"rows={len(dedup)}; external={'yes' if (args.input or source_url) else 'no'}; from_geo={used_geo}"
    append_sync_log(
        "sanction_import_risks",
        "ok" if dedup else "partial",
        "v1",
        len(dedup),
        note[:2000],
    )
    try:
        bump_preview_cache_revision("sync_sanction_risks")
    except Exception:
        pass
    print(f"sanction_import_risks rows={len(dedup)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
