#!/usr/bin/env python3
"""Validate EU sanctions and explicitly promote reviewed full snapshots.

The fail-safe default is validation-only.  Replacing ``eu_sanctions_list``
requires ``--apply``.  The correlation workbook is partial evidence and is
never promoted into the blocking table by this command.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.core import EuSanctionsList
from app.services.normative_store import (
    append_sync_log,
    stage_source_status,
    stage_sync_log,
    upsert_source_status,
)
from app.services.preview_cache_revision import bump_preview_cache_revision
from app.services.snapshot_safety import configured_minimum_rows, validate_full_snapshot

EU_DEFAULT_URL = "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content"
EU_XML_NAMESPACE = "http://eu.europa.ec/fpi/fsd/export"
EU_OFFICIAL_MIN_ENTITIES = 500
EU_CORRELATION_XLSX_URL = (
    "https://finance.ec.europa.eu/document/download/"
    "e5a807d3-6ca0-4bfb-8c6c-2f56f55e0b2e_en"
    "?filename=faqs-sanctions-russia-correlation-table-goods-regulation-833_en.xlsx"
)
UA = "customs-clear-eu-sanctions-sync/1.0"


def _local_name(tag: Any) -> str:
    t = str(tag or "")
    return t.split("}", 1)[-1] if "}" in t else t


def _namespace(tag: Any) -> str:
    value = str(tag or "")
    if value.startswith("{") and "}" in value:
        return value[1:].split("}", 1)[0]
    return ""


def _redirect_url_allowed(original_url: str, final_url: str) -> bool:
    """Require the official feed to remain on its pinned EC HTTPS origin."""
    original = urlparse(original_url)
    final = urlparse(final_url)
    original_host = (original.hostname or "").casefold()
    final_host = (final.hostname or "").casefold()
    if not original_host or not final_host:
        return False
    if original_host == "webgate.ec.europa.eu":
        return (
            final.scheme.casefold() == "https"
            and final.port in {None, 443}
            and final_host == original_host
        )
    return (
        original.scheme.casefold() == final.scheme.casefold()
        and original_host == final_host
        and (original.port or None) == (final.port or None)
    )


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
                if not _redirect_url_allowed(url, str(r.url)):
                    raise RuntimeError(f"unexpected EU sanctions redirect target: {r.url}")
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


def _rows_from_xml(
    text: str,
    *,
    require_official_schema: bool = False,
) -> list[dict[str, str]]:
    root = ET.fromstring(text)
    if require_official_schema:
        if _local_name(root.tag) != "export":
            raise ValueError("official EU sanctions XML root must be export")
        if _namespace(root.tag) != EU_XML_NAMESPACE:
            raise ValueError("official EU sanctions XML namespace is unexpected")
        generation_date = _clean(root.attrib.get("generationDate"))
        if not generation_date or not _clean(root.attrib.get("globalFileId")):
            raise ValueError("official EU sanctions XML is missing generation metadata")
        try:
            parsed_generation_date = datetime.fromisoformat(
                generation_date.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError("official EU sanctions generationDate is invalid") from exc
        if not 2000 <= parsed_generation_date.year <= datetime.now().year + 1:
            raise ValueError("official EU sanctions generationDate is implausible")

    rows: list[dict[str, str]] = []
    entities = [e for e in root.iter() if _local_name(e.tag) == "sanctionEntity"]
    if require_official_schema:
        expected_entity_tag = f"{{{EU_XML_NAMESPACE}}}sanctionEntity"
        if not entities or any(str(entity.tag) != expected_entity_tag for entity in entities):
            raise ValueError("official EU sanctions XML has no namespaced sanctionEntity rows")
    for ent in entities:
        name = ""
        for na in ent.iter():
            if _local_name(na.tag) != "nameAlias":
                continue
            if require_official_schema and _namespace(na.tag) != EU_XML_NAMESPACE:
                continue
            whole = _clean(na.attrib.get("wholeName") or na.attrib.get("name"))
            if whole:
                name = whole
                break
        if require_official_schema and not _clean(ent.attrib.get("euReferenceNumber")):
            raise ValueError("official EU sanctionEntity is missing euReferenceNumber")
        if not name:
            # Identifiers alone are not sanctioned entity names. Accepting them
            # makes schema-drift/error payloads look like a complete blocking list.
            if require_official_schema:
                raise ValueError("official EU sanctionEntity is missing a named nameAlias")
            continue
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
    if require_official_schema and len(entities) < EU_OFFICIAL_MIN_ENTITIES:
        raise ValueError(
            "official EU sanctions XML contains too few sanctionEntity rows: "
            f"{len(entities)} < {EU_OFFICIAL_MIN_ENTITIES}"
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


def _snapshot_candidates(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str, str], dict[str, str]]:
    candidates: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        payload = {
            "hs_code": str(row.get("hs_code") or ""),
            "description": str(row.get("description") or ""),
            "entity_name": str(row.get("entity_name") or ""),
        }
        if not (payload["hs_code"] or payload["description"] or payload["entity_name"]):
            continue
        candidates[
            (payload["hs_code"], payload["entity_name"], payload["description"])
        ] = payload
    return candidates


def _validate_rows(
    rows: list[dict[str, str]],
    *,
    minimum_rows: int = 1,
) -> int:
    """Validate a complete candidate snapshot without changing enforcement data."""
    candidates = _snapshot_candidates(rows)
    with SessionLocal() as db:
        existing_count = db.query(EuSanctionsList).count()
        validate_full_snapshot(
            source_id="eu_sanctions_list",
            candidate_count=len(candidates),
            existing_count=existing_count,
            minimum_rows=minimum_rows,
        )
    return len(candidates)


def _upsert_rows_partial(rows: list[dict[str, str]]) -> int:
    """Add a partial goods-correlation artifact without deleting entity data."""
    n = 0
    with SessionLocal() as db:
        try:
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
                    existing = (
                        db.query(EuSanctionsList.id)
                        .filter(
                            EuSanctionsList.hs_code == payload["hs_code"],
                            EuSanctionsList.entity_name == payload["entity_name"],
                            EuSanctionsList.description == payload["description"],
                        )
                        .first()
                    )
                    if existing is None:
                        db.add(EuSanctionsList(**payload))
                n += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
    return n


def _replace_rows(
    rows: list[dict[str, str]],
    *,
    source_url: str,
    revision: str,
    note: str,
    minimum_rows: int = 1,
) -> int:
    """Atomically replace a reviewed full snapshot and its success provenance."""
    candidates = _snapshot_candidates(rows)
    if not candidates:
        return 0
    if not revision.strip():
        raise ValueError("EU sanctions replacement requires a non-empty evidence revision")
    n = 0
    with SessionLocal() as db:
        try:
            existing_count = db.query(EuSanctionsList).count()
            validate_full_snapshot(
                source_id="eu_sanctions_list",
                candidate_count=len(candidates),
                existing_count=existing_count,
                minimum_rows=minimum_rows,
            )
            db.query(EuSanctionsList).delete(synchronize_session=False)
            for payload in candidates.values():
                if _is_sqlite(db):
                    stmt = sqlite_insert(EuSanctionsList.__table__).values(**payload)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["hs_code", "entity_name", "description"],
                        set_={"description": stmt.excluded.description},
                    )
                    db.execute(stmt)
                else:
                    db.add(EuSanctionsList(**payload))
                n += 1
            stage_source_status(
                db,
                source_code="EU_SANCTIONS",
                source_name="EU consolidated sanctions",
                source_url=source_url,
                revision=revision,
                is_stale=False,
                note=note[:2000],
            )
            stage_sync_log(
                db,
                source_code="EU_SANCTIONS",
                status="OK",
                revision=revision,
                rows_affected=n,
                note=note[:2000],
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
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
    ap.add_argument("--strict", action="store_true", help="Fail on download errors or an empty snapshot")
    ap.add_argument("--json", action="store_true", help="Emit the adapter result contract")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Explicitly replace the blocking table with this reviewed full snapshot",
    )
    mode.add_argument(
        "--validate-only",
        action="store_true",
        help="Fetch, parse and validate without changing the blocking table (default)",
    )
    ap.add_argument(
        "--official-only",
        action="store_true",
        help="Ignore operator-provided fallback URLs and use only pinned EC artifacts",
    )
    args = ap.parse_args()

    apply_changes = bool(args.apply)
    operation = "apply" if apply_changes else "validation_only"
    source_code = "EU_SANCTIONS" if apply_changes else "EU_SANCTIONS_VALIDATION"
    fallback_from_env = [x.strip() for x in str((os.getenv("EU_SANCTIONS_FALLBACK_URLS") or "")).split(",") if x.strip()]
    url_candidates = (
        [EU_DEFAULT_URL]
        if args.official_only
        else [args.url, *list(args.fallback_url or []), *fallback_from_env]
    )
    try:
        text, ctype, source_url = _http_get_with_fallback(
            url_candidates,
            timeout_sec=float(args.timeout),
            retries=max(1, int(args.retries)),
        )
    except Exception as e:
        # Fallback: официальный XLSX correlation table с CN/HS кодами (EC Finance).
        xlsx_url = (
            EU_CORRELATION_XLSX_URL
            if args.official_only
            else (args.fallback_xlsx_url or "").strip()
        )
        if not xlsx_url:
            note = f"download_failed={e!r}; urls={url_candidates!r}"
            upsert_source_status(
                source_code=source_code,
                source_name="EU consolidated sanctions",
                source_url=EU_DEFAULT_URL if args.official_only else args.url,
                revision="unavailable",
                is_stale=True,
                note=note[:2000],
            )
            append_sync_log(source_code, "ERROR", "unavailable", 0, note[:2000])
            print(f"eu_sanctions_list download skipped: {e}")
            if args.json:
                print("REGULATORY_SYNC_RESULT=" + json.dumps({
                    "status": "error",
                    "source_ids": ["eu_sanctions_list"],
                    "official_source": bool(args.official_only),
                    "operation": operation,
                    "enforcement_changed": False,
                    "rows_applied": 0,
                    "error": str(e),
                }, ensure_ascii=False, separators=(",", ":")))
            return 1
        try:
            blob, ctype = _http_get_bytes(
                xlsx_url,
                timeout_sec=float(args.timeout),
                retries=max(1, int(args.retries)),
            )
            rows = _rows_from_eu_correlation_xlsx(blob)
            # This workbook is a partial goods-correlation contour, not the
            # consolidated entity list. It can be reported as evidence but must
            # never mutate or certify the blocking snapshot.
            saved = 0
            digest = hashlib.sha256(blob).hexdigest()
            sync_ok = False
            note = (
                f"url={xlsx_url}; content_type={ctype}; "
                f"parsed={len(rows)}; saved={saved}; source=fallback_xlsx; sha256={digest}"
            )
            upsert_source_status(
                source_code=source_code,
                source_name="EU sanctions goods correlation",
                source_url=xlsx_url,
                revision=f"sha256:{digest}",
                is_stale=True,
                note=note[:2000],
            )
            append_sync_log(source_code, "OK" if sync_ok else "ERROR", f"sha256:{digest}", saved, note[:2000])
            print(f"eu_sanctions_list parsed={len(rows)} saved={saved} (fallback_xlsx)")
            if args.json:
                print("REGULATORY_SYNC_RESULT=" + json.dumps({
                    "status": "ok" if sync_ok else "error",
                    "source_ids": ["eu_sanctions_list"],
                    "official_source": bool(
                        args.official_only and xlsx_url == EU_CORRELATION_XLSX_URL
                    ),
                    "operation": operation,
                    "enforcement_changed": False,
                    "snapshot_kind": "partial",
                    "source_variant": "goods_correlation_xlsx",
                    "rows_parsed": len(rows),
                    "rows_validated": len(rows),
                    "rows_applied": saved,
                    "sha256": digest,
                }, ensure_ascii=False, separators=(",", ":")))
            return 1
        except Exception as xerr:
            note = f"download_failed={e!r}; fallback_xlsx_failed={xerr!r}; urls={url_candidates!r}"
            upsert_source_status(
                source_code=source_code,
                source_name="EU consolidated sanctions",
                source_url=EU_DEFAULT_URL if args.official_only else args.url,
                revision="unavailable",
                is_stale=True,
                note=note[:2000],
            )
            append_sync_log(source_code, "ERROR", "unavailable", 0, note[:2000])
            print(f"eu_sanctions_list download skipped: {e}; fallback failed: {xerr}")
            if args.json:
                print("REGULATORY_SYNC_RESULT=" + json.dumps({
                    "status": "error",
                    "source_ids": ["eu_sanctions_list"],
                    "official_source": bool(args.official_only),
                    "operation": operation,
                    "enforcement_changed": False,
                    "rows_applied": 0,
                    "error": f"{e}; {xerr}",
                }, ensure_ascii=False, separators=(",", ":")))
            return 1
    rows: list[dict[str, str]]
    try:
        if args.official_only:
            if "xml" not in ctype or not text.lstrip().startswith("<"):
                raise ValueError("official EU consolidated feed is not XML")
            # Official mode never falls back to body sniffing: a schema failure
            # is a red result, not permission to reinterpret arbitrary JSON/CSV.
            rows = _rows_from_xml(text, require_official_schema=True)
        else:
            try:
                if "json" in ctype:
                    rows = _rows_from_json(text)
                elif "csv" in ctype:
                    rows = _rows_from_csv(text)
                else:
                    rows = _rows_from_xml(text)
            except Exception:
                # Manual/custom sources retain tolerant body detection.
                stripped = text.lstrip()
                if stripped.startswith("{") or stripped.startswith("["):
                    rows = _rows_from_json(text)
                elif stripped.startswith("<"):
                    rows = _rows_from_xml(text)
                else:
                    rows = _rows_from_csv(text)
    except Exception as exc:
        note = f"parse_failed={exc!r}; url={source_url}; content_type={ctype}"
        upsert_source_status(
            source_code=source_code,
            source_name="EU consolidated sanctions",
            source_url=source_url,
            revision="unavailable",
            is_stale=True,
            note=note[:2000],
        )
        append_sync_log(source_code, "ERROR", "unavailable", 0, note[:2000])
        print(f"eu_sanctions_list parse failed: {exc}")
        if args.json:
            print("REGULATORY_SYNC_RESULT=" + json.dumps({
                "status": "error",
                "source_ids": ["eu_sanctions_list"],
                "official_source": bool(args.official_only and source_url == EU_DEFAULT_URL),
                "operation": operation,
                "enforcement_changed": False,
                "rows_applied": 0,
                "error": str(exc),
            }, ensure_ascii=False, separators=(",", ":")))
        return 1

    minimum_rows = configured_minimum_rows("eu_sanctions_list", 500)
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    revision = f"sha256:{digest}"
    try:
        if not apply_changes:
            validated = _validate_rows(rows, minimum_rows=minimum_rows)
            saved = 0
        else:
            validated = len(_snapshot_candidates(rows))
            success_note = (
                f"url={source_url}; content_type={ctype}; parsed={len(rows)}; "
                f"validated={validated}; saved={validated}; operation={operation}; sha256={digest}"
            )
            saved = _replace_rows(
                rows,
                minimum_rows=minimum_rows,
                source_url=source_url,
                revision=revision,
                note=success_note,
            )
            if saved <= 0:
                raise RuntimeError("official EU snapshot contained no valid rows")
    except Exception as exc:
        note = f"snapshot_rejected={exc!s}; url={source_url}; parsed={len(rows)}"
        upsert_source_status(
            source_code=source_code,
            source_name="EU consolidated sanctions",
            source_url=source_url,
            revision="unavailable",
            is_stale=True,
            note=note[:2000],
        )
        append_sync_log(source_code, "ERROR", "unavailable", 0, note[:2000])
        print(f"eu_sanctions_list snapshot rejected: {exc}")
        if args.json:
            print("REGULATORY_SYNC_RESULT=" + json.dumps({
                "status": "error",
                "source_ids": ["eu_sanctions_list"],
                "official_source": bool(args.official_only and source_url == EU_DEFAULT_URL),
                "operation": operation,
                "enforcement_changed": False,
                "rows_validated": 0,
                "rows_applied": 0,
                "error": str(exc),
            }, ensure_ascii=False, separators=(",", ":")))
        return 1
    sync_ok = validated > 0 if not apply_changes else saved > 0
    note = (
        f"url={source_url}; content_type={ctype}; parsed={len(rows)}; "
        f"validated={validated}; saved={saved}; operation={operation}; sha256={digest}"
    )
    if not apply_changes:
        upsert_source_status(
            source_code=source_code,
            source_name="EU consolidated sanctions",
            source_url=source_url,
            revision=revision,
            is_stale=not sync_ok,
            note=note[:2000],
        )
        append_sync_log(
            source_code,
            "OK" if sync_ok else "ERROR",
            revision,
            0,
            note[:2000],
        )
    if saved and apply_changes:
        try:
            bump_preview_cache_revision("sync_eu_sanctions")
        except Exception:
            pass
    print(f"eu_sanctions_list parsed={len(rows)} saved={saved}")
    if args.json:
        print("REGULATORY_SYNC_RESULT=" + json.dumps({
            "status": "ok" if sync_ok else "error",
            "source_ids": ["eu_sanctions_list"],
            "official_source": bool(args.official_only and source_url == EU_DEFAULT_URL),
            "operation": operation,
            "enforcement_changed": bool(saved) and apply_changes,
            "snapshot_kind": "full",
            "source_variant": "consolidated_entities",
            "rows_parsed": len(rows),
            "rows_validated": validated,
            "rows_applied": saved,
            "sha256": digest,
        }, ensure_ascii=False, separators=(",", ":")))
    return 0 if sync_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
