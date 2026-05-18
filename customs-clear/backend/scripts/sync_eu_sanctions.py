#!/usr/bin/env python3
"""
Синхронизация санкций ЕС / dual-use -> eu_sanctions_list.

Поддерживаемые входы:
- XML (консолидированный список ЕС)
- CSV/JSON (внешние выгрузки)
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
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.core import EuSanctionsList
from app.services.normative_store import append_sync_log, init_db
from app.services.preview_cache_revision import bump_preview_cache_revision

EU_DEFAULT_URL = "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content"
EU_CORRELATION_XLSX_URL = (
    "https://finance.ec.europa.eu/document/download/"
    "e5a807d3-6ca0-4bfb-8c6c-2f56f55e0b2e_en"
    "?filename=faqs-sanctions-russia-correlation-table-goods-regulation-833_en.xlsx"
)
UA = "customs-clear-eu-sanctions-sync/1.0"


def _local_name(tag: Any) -> str:
    t = str(tag or "")
    return t.split("}", 1)[-1] if "}" in t else t


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
                ctype = str(r.headers.get("content-type") or "").lower()
                return r.text, ctype
            except Exception as e:
                err = e
                if i >= retries:
                    break
                time.sleep(min(1.2 * i, 8.0))
    raise RuntimeError(f"EU sanctions download failed: {err!r}")


def _http_get_with_fallback(urls: list[str], *, timeout_sec: float, retries: int) -> tuple[str, str, str]:
    last_err: Exception | None = None
    for raw in urls:
        url = (raw or "").strip()
        if not url:
            continue
        try:
            text, ctype = _http_get(url, timeout_sec=timeout_sec, retries=retries)
            if text.strip():
                return text, ctype, url
            last_err = RuntimeError(f"Empty response body from {url}")
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"EU sanctions download failed for all URLs: {last_err!r}")


def _http_get_bytes(url: str, *, timeout_sec: float = 45.0, retries: int = 4) -> tuple[bytes, str]:
    err: Exception | None = None
    with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
        for i in range(1, max(1, retries) + 1):
            try:
                r = client.get(url, headers={"User-Agent": UA, "Accept": "*/*"})
                if r.status_code in (403, 429, 500, 502, 503, 504) and i < retries:
                    time.sleep(min(1.5 * i, 8.0))
                    continue
                r.raise_for_status()
                return r.content or b"", str(r.headers.get("content-type") or "").lower()
            except Exception as e:
                err = e
                if i >= retries:
                    break
                time.sleep(min(1.5 * i, 8.0))
    raise RuntimeError(f"EU binary download failed: {err!r}")


def _clean(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _norm_hs(raw: Any) -> str:
    return re.sub(r"\D", "", str(raw or "").strip())[:10]


def _extract_hs_codes(text: str) -> list[str]:
    vals: list[str] = []
    for m in re.finditer(r"\b\d{4,10}\b", text or ""):
        hs = _norm_hs(m.group(0))
        if len(hs) >= 4 and hs not in vals:
            vals.append(hs)
    return vals[:20]


def _rows_from_xml(text: str) -> list[dict[str, str]]:
    root = ET.fromstring(text)
    rows: list[dict[str, str]] = []
    entities = [e for e in root.iter() if _local_name(e.tag) == "sanctionEntity"]
    for ent in entities:
        name = ""
        for na in ent.iter():
            if _local_name(na.tag) != "nameAlias":
                continue
            whole = _clean(na.attrib.get("wholeName") or na.attrib.get("name"))
            if whole:
                name = whole
                break
        if not name:
            name = _clean(ent.attrib.get("logicalId") or ent.attrib.get("euReferenceNumber"))
        remarks = _clean(" ".join(_clean(r.text) for r in ent.iter() if _local_name(r.tag) == "remark" and _clean(r.text)))
        regs = _clean(" ".join(_clean(r.text) for r in ent.iter() if _local_name(r.tag) == "numberTitle" and _clean(r.text)))
        blob = _clean(f"{remarks} {regs}")
        hs_codes = _extract_hs_codes(blob)
        if not hs_codes:
            rows.append(
                {
                    "hs_code": "",
                    "description": (blob or "EU sanctions consolidated entity")[:4000],
                    "entity_name": name[:1024],
                }
            )
            continue
        for hs in hs_codes:
            rows.append(
                {
                    "hs_code": hs,
                    "description": (blob or "EU sanctions consolidated record")[:4000],
                    "entity_name": name[:1024],
                }
            )
    return rows


def _rows_from_csv(text: str) -> list[dict[str, str]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows: list[dict[str, str]] = []
    for r in reader:
        low = {str(k or "").strip().lower(): str(v or "").strip() for k, v in r.items() if k}
        hs = _norm_hs(low.get("hs_code") or low.get("commodity_code") or low.get("код") or "")
        desc = _clean(low.get("description") or low.get("note") or low.get("описание") or "")
        ent = _clean(low.get("entity_name") or low.get("name") or low.get("entity") or "")
        if not (hs or ent or desc):
            continue
        rows.append({"hs_code": hs, "description": desc[:4000], "entity_name": ent[:1024]})
    return rows


def _rows_from_json(text: str) -> list[dict[str, str]]:
    payload = json.loads(text)
    if isinstance(payload, dict):
        arr = payload.get("items") or payload.get("data") or payload.get("eu_sanctions_list") or []
    elif isinstance(payload, list):
        arr = payload
    else:
        arr = []
    rows: list[dict[str, str]] = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        hs = _norm_hs(it.get("hs_code") or it.get("commodity_code") or "")
        desc = _clean(it.get("description") or it.get("note") or "")
        ent = _clean(it.get("entity_name") or it.get("name") or "")
        if not (hs or ent or desc):
            continue
        rows.append({"hs_code": hs, "description": desc[:4000], "entity_name": ent[:1024]})
    return rows


def _rows_from_eu_correlation_xlsx(blob: bytes) -> list[dict[str, str]]:
    try:
        import pandas as pd
    except Exception as e:
        raise RuntimeError(f"pandas is required for XLSX parsing: {e!r}") from e

    df = pd.read_excel(io.BytesIO(blob), sheet_name=0)
    if df is None or df.empty:
        return []

    cols = list(df.columns)
    cn_col = ""
    for c in cols:
        lc = str(c or "").lower()
        if "cn code" in lc or "hs code" in lc:
            cn_col = str(c)
            break
    if not cn_col:
        return []

    category_col = next((str(c) for c in cols if "category" in str(c).lower()), "")
    eu_code_col = next((str(c) for c in cols if "eu code" in str(c).lower()), "")
    control_col = next((str(c) for c in cols if "control text" in str(c).lower()), "")

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for _, row in df.iterrows():
        raw_code = str(row.get(cn_col) or "").strip()
        hs = _norm_hs(raw_code)
        if len(hs) < 4:
            continue
        category = _clean(row.get(category_col) if category_col else "")
        eu_code = _clean(row.get(eu_code_col) if eu_code_col else "")
        ctrl = _clean(row.get(control_col) if control_col else "")
        desc = _clean(" | ".join(x for x in [category, eu_code, ctrl] if x))
        if not desc:
            desc = "EU Regulation 833/2014 Annex VII correlation table"
        ent = "EU Regulation 833/2014 Annex VII"
        key = (hs, ent, desc)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"hs_code": hs, "description": desc[:4000], "entity_name": ent})
    return rows


def _is_sqlite(db) -> bool:
    return db.bind.dialect.name == "sqlite"


def _upsert_rows(rows: list[dict[str, str]]) -> int:
    n = 0
    with SessionLocal() as db:
        for row in rows:
            payload = {
                "hs_code": row.get("hs_code") or "",
                "description": row.get("description") or "",
                "entity_name": row.get("entity_name") or "",
            }
            if not (payload["hs_code"] or payload["description"] or payload["entity_name"]):
                continue
            if _is_sqlite(db):
                stmt = sqlite_insert(EuSanctionsList.__table__).values(**payload)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["hs_code", "entity_name", "description"],
                    set_={"description": stmt.excluded.description},
                )
                db.execute(stmt)
            else:
                obj = (
                    db.query(EuSanctionsList)
                    .filter(
                        EuSanctionsList.hs_code == payload["hs_code"],
                        EuSanctionsList.entity_name == payload["entity_name"],
                        EuSanctionsList.description == payload["description"],
                    )
                    .first()
                )
                if obj is None:
                    db.add(EuSanctionsList(**payload))
            n += 1
        db.commit()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Синхронизация санкций ЕС -> eu_sanctions_list")
    ap.add_argument("--url", type=str, default=EU_DEFAULT_URL, help="URL XML/CSV/JSON")
    ap.add_argument(
        "--fallback-xlsx-url",
        type=str,
        default=EU_CORRELATION_XLSX_URL,
        help="Официальный XLSX fallback (EU correlation table with CN/HS codes)",
    )
    ap.add_argument(
        "--fallback-url",
        action="append",
        default=[],
        help="Дополнительный fallback URL (можно повторять несколько раз)",
    )
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--retries", type=int, default=4)
    args = ap.parse_args()

    init_db()
    fallback_from_env = [x.strip() for x in str((os.getenv("EU_SANCTIONS_FALLBACK_URLS") or "")).split(",") if x.strip()]
    url_candidates = [args.url, *list(args.fallback_url or []), *fallback_from_env]
    try:
        text, ctype, source_url = _http_get_with_fallback(
            url_candidates,
            timeout_sec=float(args.timeout),
            retries=max(1, int(args.retries)),
        )
    except Exception as e:
        # Fallback: официальный XLSX correlation table с CN/HS кодами (EC Finance).
        xlsx_url = (args.fallback_xlsx_url or "").strip()
        if not xlsx_url:
            note = f"download_failed={e!r}; urls={url_candidates!r}"
            append_sync_log("eu_sanctions_list", "partial", "v1", 0, note[:2000])
            print(f"eu_sanctions_list download skipped: {e}")
            return 0
        try:
            blob, ctype = _http_get_bytes(
                xlsx_url,
                timeout_sec=float(args.timeout),
                retries=max(1, int(args.retries)),
            )
            rows = _rows_from_eu_correlation_xlsx(blob)
            saved = _upsert_rows(rows)
            note = (
                f"url={xlsx_url}; content_type={ctype}; "
                f"parsed={len(rows)}; saved={saved}; source=fallback_xlsx"
            )
            append_sync_log("eu_sanctions_list", "ok" if saved else "partial", "v1", saved, note[:2000])
            try:
                bump_preview_cache_revision("sync_eu_sanctions")
            except Exception:
                pass
            print(f"eu_sanctions_list parsed={len(rows)} saved={saved} (fallback_xlsx)")
            return 0
        except Exception as xerr:
            note = f"download_failed={e!r}; fallback_xlsx_failed={xerr!r}; urls={url_candidates!r}"
            append_sync_log("eu_sanctions_list", "partial", "v1", 0, note[:2000])
            print(f"eu_sanctions_list download skipped: {e}; fallback failed: {xerr}")
            return 0
    rows: list[dict[str, str]]
    try:
        if "json" in ctype:
            rows = _rows_from_json(text)
        elif "csv" in ctype:
            rows = _rows_from_csv(text)
        else:
            rows = _rows_from_xml(text)
    except Exception:
        # fallback-detect by body
        stripped = text.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            rows = _rows_from_json(text)
        elif stripped.startswith("<"):
            rows = _rows_from_xml(text)
        else:
            rows = _rows_from_csv(text)

    saved = _upsert_rows(rows)
    note = f"url={source_url}; content_type={ctype}; parsed={len(rows)}; saved={saved}"
    append_sync_log("eu_sanctions_list", "ok" if saved else "partial", "v1", saved, note[:2000])
    try:
        bump_preview_cache_revision("sync_eu_sanctions")
    except Exception:
        pass
    print(f"eu_sanctions_list parsed={len(rows)} saved={saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
