#!/usr/bin/env python3
"""
Загрузка в БД таблиц ``fss_notifications`` (нотификации ФСБ) и ``reo_registry`` (РЭС / ВЧУ).

Открытые машиночитаемые API реестров часто меняются; скрипт поддерживает:

- переменные окружения ``FSS_NOTIFICATIONS_SYNC_URL`` и ``REO_REGISTRY_SYNC_URL`` — HTTP(S) на CSV (UTF-8);
- локальные файлы: ``--fss-csv`` / ``--reo-csv``;
- ``--demo-seed`` — минимальный набор строк для проверки сверки в ``invoice_analyzer``.

HTTP: таймаут 15 с, повторы при 5xx/сетевых сбоях (см. ``app.services.registry_sync_http``).

Формат CSV (разделитель ``;`` или ``,``, авто по первой строке):

ФСБ: ``number``, ``name``, ``brand``, ``status``, ``expiry_date`` (YYYY-MM-DD).

РЭС: ``number``, ``model_name``, ``brand``, ``characteristics``, ``status``, ``expiry_date``.

Запуск из каталога ``customs-clear/backend``::

  python3 scripts/sync_state_registries.py
  python3 scripts/sync_state_registries.py --demo-seed
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.datetime_util import utc_now_naive
from app.db import SessionLocal
from app.models.core import FssNotification, ReoRegistryEntry
from app.services.normative_store import append_sync_log, init_db, upsert_source_status
from app.services.nsi_http import post_official_nsi_json
from app.services.preview_cache_revision import bump_preview_cache_revision
from app.services.registry_sync_http import registry_http_get_text
from app.services.snapshot_safety import configured_minimum_rows, validate_full_snapshot

NSI_BASE_API = "https://nsi.eaeunion.org/portal/api"
NSI_FSS_CODE = "1994"
NSI_REO_CODE = "1992"


def _parse_expiry(val: str | None) -> datetime | None:
    if not val or not str(val).strip():
        return None
    s = str(val).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _sniff_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,")
    except csv.Error:
        return csv.excel


def _read_csv_rows(text: str) -> list[dict[str, str]]:
    sample = text[:4096]
    dialect = _sniff_dialect(sample)
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {str(k or "").strip().lower(): str(v or "").strip() for k, v in raw.items() if k}
        rows.append(row)
    return rows


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    proxy: str = "",
    timeout_sec: float = 45.0,
    retries: int = 4,
) -> Any:
    return post_official_nsi_json(
        url,
        payload,
        headers={
            "User-Agent": "customs-clear-state-registries/1.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        proxy=proxy,
        timeout_sec=timeout_sec,
        retries=retries,
    )


def _nsi_payload(*, date_iso: str, offset: int, limit: int) -> dict[str, Any]:
    return {
        "date": date_iso,
        "offset": int(offset),
        "limit": int(limit),
        "filter": [{"code": "searchText", "value": "", "conditionType": "like"}],
        "sort": [],
    }


def _nsi_total(*, code: str, date_iso: str, proxy: str = "") -> int:
    url = f"{NSI_BASE_API}/dictionaries/{code}/get-list-data-total"
    payload = {"date": date_iso, "filter": [{"code": "searchText", "value": "", "conditionType": "like"}]}
    data = _http_post_json(url, payload, proxy=proxy)
    if isinstance(data, dict):
        for k in ("byFilterCount", "totalCount", "count"):
            if k in data:
                try:
                    return max(0, int(data.get(k) or 0))
                except Exception:
                    continue
    return 0


def _nsi_fetch_rows(
    *,
    code: str,
    date_iso: str,
    proxy: str = "",
    max_rows: int = 0,
    batch_size: int = 500,
) -> list[dict[str, Any]]:
    total = _nsi_total(code=code, date_iso=date_iso, proxy=proxy)
    if total <= 0:
        return []
    target = min(total, int(max_rows)) if int(max_rows) > 0 else total
    url = f"{NSI_BASE_API}/dictionaries/{code}/get-list-data"
    out: list[dict[str, Any]] = []
    offset = 0
    step = max(1, min(2000, int(batch_size)))
    while offset < target:
        payload = _nsi_payload(date_iso=date_iso, offset=offset, limit=min(step, target - offset))
        data = _http_post_json(url, payload, proxy=proxy)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("records") or data.get("content") or data.get("result") or data.get("data") or []
        else:
            rows = []
        if not isinstance(rows, list) or not rows:
            break
        for r in rows:
            if isinstance(r, dict):
                out.append(r)
        offset += len(rows)
        if len(rows) < payload["limit"]:
            break
    if len(out) != target:
        raise RuntimeError(
            f"NSI dictionary {code} snapshot is incomplete: "
            f"fetched_rows={len(out)} expected_rows={target} reported_total={total}"
        )
    return out


def _extract_brand_hint(name: str) -> str:
    t = str(name or "")
    if not t:
        return ""
    m = re.search(r"торгов[а-я\\s]+марк[а-я\\s]*[\"“”«]([^\"“”»]+)[\"“”»]", t, flags=re.I)
    if m:
        return m.group(1).strip()[:512]
    m2 = re.search(r"[\"“”«]([^\"“”»]{2,80})[\"“”»]", t)
    if m2:
        return m2.group(1).strip()[:512]
    return ""


def _norm_text(v: Any, *, max_len: int = 512) -> str:
    if isinstance(v, list):
        parts = []
        for x in v:
            if isinstance(x, dict):
                nm = str(x.get("name") or "").strip()
                if nm:
                    parts.append(nm)
            else:
                sx = str(x or "").strip()
                if sx:
                    parts.append(sx)
        s = "; ".join(parts)
    elif isinstance(v, dict):
        s = str(v.get("name") or v.get("value") or "").strip()
    else:
        s = str(v or "").strip()
    return s[:max_len]


def _rows_from_nsi_fss(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        data = row.get("data") if isinstance(row, dict) else None
        if not isinstance(data, dict):
            continue
        num = str(data.get("NotificationNumber") or "").strip()
        name = str(data.get("Name") or "").strip()
        # ``Id`` is an internal NSI row key, not a legal notification number.
        # Both the document identity and the product name are required so a
        # schema drift cannot replace the live registry with hollow rows.
        if not num or not name:
            continue
        brand = _extract_brand_hint(name)
        status = str(data.get("Status") or "").strip()
        exp = data.get("ValidityPeriod") or row.get("dateTo")
        out.append(
            {
                "number": num[:64],
                "name": name[:8000],
                "brand": brand[:512],
                "status": status[:64],
                "expiry_date": _parse_expiry(str(exp or "")),
            }
        )
    return out


def _rows_from_nsi_reo(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        data = row.get("data") if isinstance(row, dict) else None
        if not isinstance(data, dict):
            continue
        num = str(data.get("RecordId") or "").strip()
        model_name = str(data.get("DeviceModelNam") or data.get("DeviceName") or "").strip()
        if not num or not model_name:
            continue
        manufacturer = _norm_text(data.get("Name_manufacture"), max_len=512)
        country = _norm_text(data.get("Country_manufacture"), max_len=256)
        freq = _norm_text(data.get("DeviceInfo_FrequencyChannel"), max_len=800)
        energy = _norm_text(data.get("DeviceInfo_Energy"), max_len=400)
        unit = _norm_text(data.get("DeviceInfo_FrequencyMeasurementUnitCode"), max_len=200)
        status = str(data.get("Status") or "").strip()
        exp = data.get("ValidityPeriodDetails_EndDate") or row.get("dateTo")
        ch = " | ".join(x for x in [f"freq={freq}", f"unit={unit}", f"energy={energy}", f"country={country}"] if x).strip()
        out.append(
            {
                "number": num[:64],
                "model_name": model_name[:512],
                "brand": manufacturer[:512],
                "characteristics": ch[:8000],
                "status": status[:64],
                "expiry_date": _parse_expiry(str(exp or "")),
            }
        )
    return out


def _unique_registry_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate the candidate snapshot by its database identity."""
    return list(
        {
            str(row.get("number") or "").strip(): row
            for row in rows
            if str(row.get("number") or "").strip()
        }.values()
    )


def _validate_nsi_snapshot(
    db,
    *,
    source_id: str,
    model,
    raw_rows: list[dict[str, Any]],
    parsed_rows: list[dict[str, Any]],
    max_rows: int,
    default_minimum_rows: int,
) -> list[dict[str, Any]]:
    """Validate complete NSI snapshots before any live rows are deleted.

    A limited request is explicitly a partial upsert.  It still benefits from
    exact HTTP pagination in ``_nsi_fetch_rows`` but must never be interpreted
    as a replacement snapshot.
    """
    candidates = _unique_registry_rows(parsed_rows)
    if int(max_rows) > 0:
        return candidates
    validate_full_snapshot(
        source_id=source_id,
        candidate_count=len(candidates),
        existing_count=db.query(model).count(),
        minimum_rows=configured_minimum_rows(source_id, default_minimum_rows),
        reported_total=len(raw_rows),
        fetched_count=len(candidates),
    )
    return candidates


def _is_sqlite(db) -> bool:
    return db.bind.dialect.name == "sqlite"


def upsert_fss_rows(db, rows: list[dict[str, Any]]) -> int:
    now = utc_now_naive()
    n = 0
    for row in rows:
        num = str(row.get("number") or "").strip()
        if not num:
            continue
        payload = {
            "number": num[:64],
            "name": str(row.get("name") or "")[:8000],
            "brand": str(row.get("brand") or "")[:512],
            "status": str(row.get("status") or "")[:64],
            "expiry_date": row.get("expiry_date"),
            "last_updated": now,
        }
        if _is_sqlite(db):
            stmt = sqlite_insert(FssNotification.__table__).values(**payload)
            stmt = stmt.on_conflict_do_update(
                index_elements=["number"],
                set_={
                    "name": stmt.excluded.name,
                    "brand": stmt.excluded.brand,
                    "status": stmt.excluded.status,
                    "expiry_date": stmt.excluded.expiry_date,
                    "last_updated": stmt.excluded.last_updated,
                },
            )
            db.execute(stmt)
        else:
            obj = db.query(FssNotification).filter(FssNotification.number == payload["number"]).first()
            if obj:
                for k, v in payload.items():
                    setattr(obj, k, v)
            else:
                db.add(FssNotification(**payload))
        n += 1
    return n


def upsert_reo_rows(db, rows: list[dict[str, Any]]) -> int:
    n = 0
    for row in rows:
        num = str(row.get("number") or "").strip()
        if not num:
            continue
        payload = {
            "number": num[:64],
            "model_name": str(row.get("model_name") or "")[:512],
            "brand": str(row.get("brand") or "")[:512],
            "characteristics": str(row.get("characteristics") or "")[:8000],
            "status": str(row.get("status") or "")[:64],
            "expiry_date": row.get("expiry_date"),
        }
        if _is_sqlite(db):
            stmt = sqlite_insert(ReoRegistryEntry.__table__).values(**payload)
            stmt = stmt.on_conflict_do_update(
                index_elements=["number"],
                set_={
                    "model_name": stmt.excluded.model_name,
                    "brand": stmt.excluded.brand,
                    "characteristics": stmt.excluded.characteristics,
                    "status": stmt.excluded.status,
                    "expiry_date": stmt.excluded.expiry_date,
                },
            )
            db.execute(stmt)
        else:
            obj = db.query(ReoRegistryEntry).filter(ReoRegistryEntry.number == payload["number"]).first()
            if obj:
                for k, v in payload.items():
                    setattr(obj, k, v)
            else:
                db.add(ReoRegistryEntry(**payload))
        n += 1
    return n


def _rows_from_csv_dicts(dict_rows: list[dict[str, str]], *, kind: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for d in dict_rows:
        if kind == "fss":
            num = d.get("number") or d.get("№") or d.get("номер")
            name = d.get("name") or d.get("наименование") or d.get("товар")
            brand = d.get("brand") or d.get("бренд") or d.get("торговая марка") or d.get("tm")
            status = d.get("status") or d.get("статус")
            exp = d.get("expiry_date") or d.get("срок") or d.get("действует до")
            if not num:
                continue
            out.append(
                {
                    "number": num,
                    "name": name or "",
                    "brand": brand or "",
                    "status": status or "",
                    "expiry_date": _parse_expiry(exp),
                }
            )
        else:
            num = d.get("number") or d.get("№") or d.get("номер")
            model = d.get("model_name") or d.get("model") or d.get("модель")
            brand = d.get("brand") or d.get("бренд")
            ch = d.get("characteristics") or d.get("характеристики") or ""
            status = d.get("status") or d.get("статус")
            exp = d.get("expiry_date") or d.get("срок")
            if not num:
                continue
            out.append(
                {
                    "number": num,
                    "model_name": model or "",
                    "brand": brand or "",
                    "characteristics": ch,
                    "status": status or "",
                    "expiry_date": _parse_expiry(exp),
                }
            )
    return out


def demo_seed_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fss = [
        {
            "number": "RU0000000000123",
            "name": "Wireless access point dual-band antenna integrated",
            "brand": "DemoBrand",
            "status": "действует",
            "expiry_date": _parse_expiry("2028-10-12"),
        },
        {
            "number": "RU0000000000456",
            "name": "Ethernet switch managed 24 ports",
            "brand": "DemoBrand",
            "status": "действует",
            "expiry_date": _parse_expiry("2027-01-15"),
        },
    ]
    reo = [
        {
            "number": "REO-DEMO-0001",
            "model_name": "AP-PRO-X1",
            "brand": "DemoBrand",
            "characteristics": "Wi-Fi 6, 2.4/5 GHz",
            "status": "зарегистрировано",
            "expiry_date": None,
        },
    ]
    return fss, reo


def main() -> int:
    ap = argparse.ArgumentParser(description="Синхронизация реестров ФСБ и РЭС")
    ap.add_argument("--fss-csv", type=Path, default=None, help="Локальный CSV нотификаций ФСБ")
    ap.add_argument("--reo-csv", type=Path, default=None, help="Локальный CSV реестра РЭС")
    ap.add_argument(
        "--fss-url",
        type=str,
        default="",
        help="URL CSV для нотификаций ФСБ (переопределяет FSS_NOTIFICATIONS_SYNC_URL)",
    )
    ap.add_argument(
        "--reo-url",
        type=str,
        default="",
        help="URL CSV для реестра РЭС (переопределяет REO_REGISTRY_SYNC_URL)",
    )
    ap.add_argument(
        "--demo-seed",
        action="store_true",
        help="Вставить демонстрационные строки (для тестов сверки)",
    )
    ap.add_argument(
        "--proxy",
        type=str,
        default="",
        help="Опциональный прокси для запросов к источникам (например, http://user:pass@host:port)",
    )
    ap.add_argument(
        "--disable-nsi",
        action="store_true",
        help="Отключить fallback к официальному NSI API ЕАЭС",
    )
    ap.add_argument(
        "--nsi-only",
        action="store_true",
        help="Использовать только канонические NSI API, игнорируя CSV URL из окружения",
    )
    ap.add_argument(
        "--nsi-date",
        type=str,
        default="",
        help="Дата среза NSI в формате YYYY-MM-DD (по умолчанию сегодня)",
    )
    ap.add_argument(
        "--nsi-limit",
        type=int,
        default=0,
        help="Лимит строк NSI на каждый реестр (0 = все строки)",
    )
    ap.add_argument(
        "--fss-nsi-code",
        type=str,
        default=NSI_FSS_CODE,
        help=f"Код словаря NSI для нотификаций ФСБ (по умолчанию {NSI_FSS_CODE})",
    )
    ap.add_argument(
        "--reo-nsi-code",
        type=str,
        default=NSI_REO_CODE,
        help=f"Код словаря NSI для реестра РЭС/ВЧУ (по умолчанию {NSI_REO_CODE})",
    )
    ap.add_argument("--strict", action="store_true", help="Require non-empty FSS and REO official results")
    ap.add_argument("--json", action="store_true", help="Emit the adapter result contract")
    args = ap.parse_args()

    if args.nsi_only and (
        args.demo_seed
        or args.disable_nsi
        or args.fss_csv is not None
        or args.reo_csv is not None
        or bool((args.fss_url or "").strip())
        or bool((args.reo_url or "").strip())
    ):
        ap.error("--nsi-only cannot be combined with demo, CSV/URL, or --disable-nsi")

    fss_nsi_code = str(args.fss_nsi_code or NSI_FSS_CODE).strip()
    reo_nsi_code = str(args.reo_nsi_code or NSI_REO_CODE).strip()
    if fss_nsi_code != NSI_FSS_CODE or reo_nsi_code != NSI_REO_CODE:
        ap.error("FSS/REO source identities are pinned to NSI dictionaries 1994/1992")
    init_db()

    fss_total = 0
    reo_total = 0
    notes: list[str] = []
    http_failed = False
    fss_failed = False
    reo_failed = False
    proxy = (args.proxy or "").strip()
    nsi_date = (args.nsi_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
    nsi_limit = max(0, int(args.nsi_limit))
    ua = {"User-Agent": "customs-clear-state-registries/1.0"}
    fss_variant = "unknown"
    reo_variant = "unknown"
    fss_snapshot_kind = "partial"
    reo_snapshot_kind = "partial"

    with SessionLocal() as db:
        if args.demo_seed:
            fss_variant = "demo"
            reo_variant = "demo"
            fss_rows, reo_rows = demo_seed_rows()
            fss_total = upsert_fss_rows(db, fss_rows)
            reo_total = upsert_reo_rows(db, reo_rows)
            notes.append("demo_seed")
        else:
            fss_url = "" if args.nsi_only else (
                args.fss_url or os.getenv("FSS_NOTIFICATIONS_SYNC_URL") or ""
            ).strip()
            reo_url = "" if args.nsi_only else (
                args.reo_url or os.getenv("REO_REGISTRY_SYNC_URL") or ""
            ).strip()

            if args.fss_csv:
                fss_variant = "csv_file"
                try:
                    if not args.fss_csv.is_file():
                        raise RuntimeError(f"CSV file does not exist: {args.fss_csv}")
                    text = args.fss_csv.read_text(encoding="utf-8", errors="replace")
                    parsed = _rows_from_csv_dicts(_read_csv_rows(text), kind="fss")
                    # Operator-provided exports are not authoritative snapshots:
                    # only upsert them, never delete live registry rows.
                    fss_total = upsert_fss_rows(db, parsed)
                    notes.append(f"fss_file={args.fss_csv.name}")
                except Exception as e:
                    db.rollback()
                    fss_total = 0
                    reo_total = 0
                    logger.error("FSS CSV: {}", e)
                    notes.append(f"fss_file_error:{e!s}")
                    fss_failed = True
            elif fss_url:
                fss_variant = "csv_url"
                try:
                    text = registry_http_get_text(fss_url, headers=ua)
                    parsed = _rows_from_csv_dicts(_read_csv_rows(text), kind="fss")
                    fss_total = upsert_fss_rows(db, parsed)
                    notes.append("fss_url_ok")
                except Exception as e:
                    db.rollback()
                    fss_total = 0
                    reo_total = 0
                    logger.error("FSS_NOTIFICATIONS_SYNC_URL: недоступен после повторов: {}", e)
                    notes.append(f"fss_url_error:{e!s}")
                    http_failed = True
                    fss_failed = True
            elif not args.disable_nsi:
                fss_variant = "nsi"
                fss_snapshot_kind = "partial" if nsi_limit > 0 else "full"
                try:
                    raw = _nsi_fetch_rows(
                        code=fss_nsi_code,
                        date_iso=nsi_date,
                        proxy=proxy,
                        max_rows=nsi_limit,
                    )
                    parsed = _validate_nsi_snapshot(
                        db,
                        source_id="eec_fss_notifications_registry",
                        model=FssNotification,
                        raw_rows=raw,
                        parsed_rows=_rows_from_nsi_fss(raw),
                        max_rows=nsi_limit,
                        default_minimum_rows=100,
                    )
                    if parsed and nsi_limit <= 0:
                        db.query(FssNotification).delete(synchronize_session=False)
                    fss_total = upsert_fss_rows(db, parsed)
                    notes.append(f"fss_nsi_ok:{len(parsed)}")
                except Exception as e:
                    db.rollback()
                    fss_total = 0
                    reo_total = 0
                    logger.error("FSS NSI API: недоступен после повторов: {}", e)
                    notes.append(f"fss_nsi_error:{e!s}")
                    http_failed = True
                    fss_failed = True

            if args.reo_csv:
                reo_variant = "csv_file"
                try:
                    if not args.reo_csv.is_file():
                        raise RuntimeError(f"CSV file does not exist: {args.reo_csv}")
                    text = args.reo_csv.read_text(encoding="utf-8", errors="replace")
                    parsed = _rows_from_csv_dicts(_read_csv_rows(text), kind="reo")
                    reo_total = upsert_reo_rows(db, parsed)
                    notes.append(f"reo_file={args.reo_csv.name}")
                except Exception as e:
                    # REO is the second half of the pair. Its failure rolls
                    # back any uncommitted FSS replacement as well.
                    db.rollback()
                    fss_total = 0
                    reo_total = 0
                    logger.error("REO CSV: {}", e)
                    notes.append(f"reo_file_error:{e!s}")
                    reo_failed = True
            elif reo_url:
                reo_variant = "csv_url"
                try:
                    text = registry_http_get_text(reo_url, headers=ua)
                    parsed = _rows_from_csv_dicts(_read_csv_rows(text), kind="reo")
                    reo_total = upsert_reo_rows(db, parsed)
                    notes.append("reo_url_ok")
                except Exception as e:
                    db.rollback()
                    fss_total = 0
                    reo_total = 0
                    logger.error("REO_REGISTRY_SYNC_URL: недоступен после повторов: {}", e)
                    notes.append(f"reo_url_error:{e!s}")
                    http_failed = True
                    reo_failed = True
            elif not args.disable_nsi:
                reo_variant = "nsi"
                reo_snapshot_kind = "partial" if nsi_limit > 0 else "full"
                try:
                    raw = _nsi_fetch_rows(
                        code=reo_nsi_code,
                        date_iso=nsi_date,
                        proxy=proxy,
                        max_rows=nsi_limit,
                    )
                    parsed = _validate_nsi_snapshot(
                        db,
                        source_id="eec_reo_vchu_registry",
                        model=ReoRegistryEntry,
                        raw_rows=raw,
                        parsed_rows=_rows_from_nsi_reo(raw),
                        max_rows=nsi_limit,
                        default_minimum_rows=100,
                    )
                    if parsed and nsi_limit <= 0:
                        db.query(ReoRegistryEntry).delete(synchronize_session=False)
                    reo_total = upsert_reo_rows(db, parsed)
                    notes.append(f"reo_nsi_ok:{len(parsed)}")
                except Exception as e:
                    db.rollback()
                    fss_total = 0
                    reo_total = 0
                    logger.error("REO NSI API: недоступен после повторов: {}", e)
                    notes.append(f"reo_nsi_error:{e!s}")
                    http_failed = True
                    reo_failed = True

            if not fss_total and not args.fss_csv and not fss_url:
                notes.append("fss_skipped_no_source")
            if not reo_total and not args.reo_csv and not reo_url:
                notes.append("reo_skipped_no_source")

        strict_failure = bool(
            not args.demo_seed
            and (http_failed or fss_failed or reo_failed or fss_total <= 0 or reo_total <= 0)
        )
        if strict_failure:
            # FSS and REO form one scheduled adapter contract.  Do not expose a
            # half-refreshed pair when either official snapshot is unavailable.
            db.rollback()
            fss_total = 0
            reo_total = 0
        else:
            db.commit()

    if strict_failure:
        notes.append("transaction_rolled_back")
        fss_failed = reo_failed = True
    note = "; ".join(notes) or "ok"
    if args.strict and not args.demo_seed:
        fss_failed = fss_failed or fss_total <= 0
        reo_failed = reo_failed or reo_total <= 0
    fss_ok = not fss_failed and (fss_total > 0 or not args.strict)
    reo_ok = not reo_failed and (reo_total > 0 or not args.strict)
    sync_ok = fss_ok and reo_ok and not http_failed
    revision = (
        f"{fss_variant}+{reo_variant}:{nsi_date}"
        if not args.demo_seed
        else "demo"
    )
    for source_code, source_name, source_url, rows, source_ok in (
        (
            "FSS_NOTIFICATIONS",
            "Единый реестр нотификаций ЕАЭС",
            "https://nsi.eaeunion.org/portal/1994",
            fss_total,
            fss_ok,
        ),
        (
            "REO_VCHU",
            "Единый реестр РЭС и ВЧУ ЕАЭС",
            "https://nsi.eaeunion.org/portal/1992",
            reo_total,
            reo_ok,
        ),
    ):
        variant = fss_variant if source_code == "FSS_NOTIFICATIONS" else reo_variant
        kind = fss_snapshot_kind if source_code == "FSS_NOTIFICATIONS" else reo_snapshot_kind
        official_provenance = bool(source_ok and rows > 0 and variant == "nsi"
                                   and kind == "full" and not args.demo_seed)
        upsert_source_status(
            source_code=source_code,
            source_name=source_name,
            source_url=source_url if official_provenance else "",
            revision=revision if source_ok else "unavailable",
            is_stale=not official_provenance,
            note=note[:2000],
        )
        append_sync_log(
            source_code,
            "OK" if official_provenance else "ERROR",
            revision,
            rows,
            note[:2000],
        )
    print(f"fss_rows={fss_total} reo_rows={reo_total} ({note})")
    if fss_total or reo_total:
        try:
            bump_preview_cache_revision("sync_state_registries")
        except Exception:
            pass
    if args.json:
        official_source = bool(
            args.strict
            and args.nsi_only
            and fss_variant == "nsi"
            and reo_variant == "nsi"
            and fss_nsi_code == NSI_FSS_CODE
            and reo_nsi_code == NSI_REO_CODE
            and fss_snapshot_kind == "full"
            and reo_snapshot_kind == "full"
        )
        snapshot_kind = (
            "full"
            if fss_snapshot_kind == "full" and reo_snapshot_kind == "full"
            else "partial"
        )
        payload = {
            "status": "ok" if sync_ok else "error",
            "source_ids": ["eec_fss_notifications_registry", "eec_reo_vchu_registry"],
            "official_source": official_source,
            "snapshot_kind": snapshot_kind,
            "source_variant": f"{fss_variant}+{reo_variant}",
            "revision": revision,
            "sources": {
                "eec_fss_notifications_registry": {
                    "status": "ok" if fss_ok else "error",
                    "official_source": official_source,
                    "rows_applied": fss_total,
                },
                "eec_reo_vchu_registry": {
                    "status": "ok" if reo_ok else "error",
                    "official_source": official_source,
                    "rows_applied": reo_total,
                },
            },
            "note": note,
        }
        print("REGULATORY_SYNC_RESULT=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0 if sync_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
