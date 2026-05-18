#!/usr/bin/env python3
"""
Синхронизация OFAC SDN (США) -> ofac_sdn_list.

По умолчанию использует OFAC XML:
https://www.treasury.gov/ofac/downloads/sdn.xml
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.core import OfacSdnList
from app.services.normative_store import append_sync_log, init_db
from app.services.preview_cache_revision import bump_preview_cache_revision

OFAC_DEFAULT_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"
UA = "customs-clear-ofac-sync/1.0"


def _local_name(tag: Any) -> str:
    t = str(tag or "")
    return t.split("}", 1)[-1] if "}" in t else t


def _child_text(node: ET.Element, name: str) -> str:
    for ch in list(node):
        if _local_name(ch.tag) == name:
            return _clean(ch.text)
    return ""


def _desc_text(node: ET.Element, name: str) -> str:
    for ch in node.iter():
        if _local_name(ch.tag) == name:
            return _clean(ch.text)
    return ""


def _http_get(url: str, *, timeout_sec: float = 45.0, retries: int = 4) -> tuple[str, str]:
    err: Exception | None = None
    with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
        for i in range(1, max(1, retries) + 1):
            try:
                r = client.get(url, headers={"User-Agent": UA, "Accept": "*/*"})
                if r.status_code in (429, 500, 502, 503, 504) and i < retries:
                    time.sleep(min(1.2 * i, 8.0))
                    continue
                r.raise_for_status()
                return r.text, str(r.headers.get("content-type") or "").lower()
            except Exception as e:
                err = e
                if i >= retries:
                    break
                time.sleep(min(1.2 * i, 8.0))
    raise RuntimeError(f"OFAC download failed: {err!r}")


def _clean(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _guess_type(raw: str) -> str:
    t = _clean(raw).lower()
    if "individual" in t:
        return "individual"
    if "entity" in t or "organization" in t:
        return "entity"
    if "vessel" in t:
        return "vessel"
    if "aircraft" in t:
        return "aircraft"
    return "other"


def _extract_rows_from_xml(xml_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    rows: list[dict[str, str]] = []
    entries = [e for e in root.iter() if _local_name(e.tag) == "sdnEntry"]
    for entry in entries:
        first = _child_text(entry, "firstName")
        last = _child_text(entry, "lastName")
        whole = _clean(f"{first} {last}")
        if not whole:
            whole = _child_text(entry, "sdnName") or _desc_text(entry, "sdnName")
        if not whole:
            continue

        sdn_type = _guess_type(_child_text(entry, "sdnType") or _desc_text(entry, "sdnType"))
        countries: set[str] = set()
        for c in entry.iter():
            if _local_name(c.tag) != "country":
                continue
            cc = _clean(c.text).upper()[:8]
            if cc:
                countries.add(cc)
        origin_country = sorted(countries)[0] if countries else ""

        aliases: list[str] = []
        for aka in entry.iter():
            if _local_name(aka.tag) != "aka":
                continue
            af = _desc_text(aka, "firstName")
            al = _desc_text(aka, "lastName")
            nm = _clean(f"{af} {al}")
            if nm and nm not in aliases:
                aliases.append(nm)
        aliases_json = json.dumps(aliases, ensure_ascii=False)

        rows.append(
            {
                "name": whole[:1024],
                "type": sdn_type[:64],
                "origin_country": origin_country[:8],
                "aliases": aliases_json[:12000],
            }
        )
    return rows


def _extract_rows_from_csv(csv_text: str) -> list[dict[str, str]]:
    sample = csv_text[:4096]
    try:
        import csv

        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
    except Exception:
        import csv

        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(csv_text), dialect=dialect)
    rows: list[dict[str, str]] = []
    for r in reader:
        low = {str(k or "").strip().lower(): str(v or "").strip() for k, v in r.items() if k}
        nm = _clean(low.get("name") or low.get("sdn_name") or low.get("full_name") or "")
        if not nm:
            continue
        typ = _guess_type(low.get("type") or low.get("sdn_type") or "other")
        country = _clean(low.get("country") or low.get("origin_country") or "").upper()[:8]
        aliases = _clean(low.get("aliases") or low.get("aka") or "")
        aliases_json = json.dumps([x.strip() for x in re.split(r"[;|,]+", aliases) if x.strip()], ensure_ascii=False)
        rows.append(
            {
                "name": nm[:1024],
                "type": typ[:64],
                "origin_country": country[:8],
                "aliases": aliases_json[:12000],
            }
        )
    return rows


def _is_sqlite(db) -> bool:
    return db.bind.dialect.name == "sqlite"


def _upsert_rows(rows: list[dict[str, str]]) -> int:
    n = 0
    with SessionLocal() as db:
        for row in rows:
            if not row["name"]:
                continue
            payload = {
                "name": row["name"],
                "type": row["type"] or "other",
                "origin_country": row["origin_country"] or "",
                "aliases": row["aliases"] or "",
            }
            if _is_sqlite(db):
                stmt = sqlite_insert(OfacSdnList.__table__).values(**payload)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["name", "type", "origin_country"],
                    set_={"aliases": stmt.excluded.aliases},
                )
                db.execute(stmt)
            else:
                obj = (
                    db.query(OfacSdnList)
                    .filter(
                        OfacSdnList.name == payload["name"],
                        OfacSdnList.type == payload["type"],
                        OfacSdnList.origin_country == payload["origin_country"],
                    )
                    .first()
                )
                if obj is None:
                    db.add(OfacSdnList(**payload))
                else:
                    obj.aliases = payload["aliases"]
            n += 1
        db.commit()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Синхронизация OFAC SDN -> ofac_sdn_list")
    ap.add_argument("--url", type=str, default=OFAC_DEFAULT_URL, help="URL XML/CSV OFAC SDN")
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--retries", type=int, default=4)
    args = ap.parse_args()

    init_db()
    text, ctype = _http_get(args.url, timeout_sec=float(args.timeout), retries=max(1, int(args.retries)))
    stripped = text.lstrip()
    if "csv" in ctype or (stripped and not stripped.startswith("<")):
        rows = _extract_rows_from_csv(text)
    else:
        rows = _extract_rows_from_xml(text)
    saved = _upsert_rows(rows)

    note = f"url={args.url}; content_type={ctype}; parsed={len(rows)}; saved={saved}"
    append_sync_log("ofac_sdn_list", "ok" if saved else "partial", "v1", saved, note[:2000])
    try:
        bump_preview_cache_revision("sync_ofac_sanctions")
    except Exception:
        pass
    print(f"ofac_sdn_list parsed={len(rows)} saved={saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
