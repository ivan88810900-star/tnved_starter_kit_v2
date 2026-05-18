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
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from loguru import logger
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.datetime_util import utc_now_naive
from app.db import SessionLocal
from app.models.core import FssNotification, ReoRegistryEntry
from app.services.normative_store import append_sync_log, init_db
from app.services.preview_cache_revision import bump_preview_cache_revision
from app.services.registry_sync_http import registry_http_get_text

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


def _proxy_map(proxy: str) -> dict[str, str] | None:
    p = str(proxy or "").strip()
    if not p:
        return None
    return {"http": p, "https": p}


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    proxy: str = "",
    timeout_sec: float = 45.0,
    retries: int = 4,
) -> Any:
    err: Exception | None = None
    for i in range(1, max(1, retries) + 1):
        try:
            r = requests.post(
                url,
                json=payload,
                headers={
                    "User-Agent": "customs-clear-state-registries/1.0",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=timeout_sec,
                proxies=_proxy_map(proxy),
            )
            if r.status_code in (429, 500, 502, 503, 504) and i < retries:
                time.sleep(min(1.2 * i, 8.0))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            err = e
            if i >= retries:
                break
            time.sleep(min(1.2 * i, 8.0))
    raise RuntimeError(f"NSI POST failed: {url} | {err!r}")


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
        num = str(data.get("NotificationNumber") or data.get("Id") or "").strip()
        if not num:
            continue
        name = str(data.get("Name") or "").strip()
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
        if not num:
            continue
        model_name = str(data.get("DeviceModelNam") or data.get("DeviceName") or "").strip()
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
    args = ap.parse_args()

    init_db()

    fss_total = 0
    reo_total = 0
    notes: list[str] = []
    http_failed = False
    proxy = (args.proxy or "").strip()
    nsi_date = (args.nsi_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
    ua = {"User-Agent": "customs-clear-state-registries/1.0"}

    with SessionLocal() as db:
        if args.demo_seed:
            fss_rows, reo_rows = demo_seed_rows()
            fss_total = upsert_fss_rows(db, fss_rows)
            reo_total = upsert_reo_rows(db, reo_rows)
            notes.append("demo_seed")
        else:
            fss_url = (args.fss_url or os.getenv("FSS_NOTIFICATIONS_SYNC_URL") or "").strip()
            reo_url = (args.reo_url or os.getenv("REO_REGISTRY_SYNC_URL") or "").strip()

            if args.fss_csv and args.fss_csv.is_file():
                text = args.fss_csv.read_text(encoding="utf-8", errors="replace")
                parsed = _rows_from_csv_dicts(_read_csv_rows(text), kind="fss")
                fss_total = upsert_fss_rows(db, parsed)
                notes.append(f"fss_file={args.fss_csv.name}")
            elif fss_url:
                try:
                    text = registry_http_get_text(fss_url, headers=ua)
                    parsed = _rows_from_csv_dicts(_read_csv_rows(text), kind="fss")
                    fss_total = upsert_fss_rows(db, parsed)
                    notes.append("fss_url_ok")
                except Exception as e:
                    logger.error("FSS_NOTIFICATIONS_SYNC_URL: недоступен после повторов: {}", e)
                    notes.append(f"fss_url_error:{e!s}")
                    http_failed = True
            elif not args.disable_nsi:
                try:
                    raw = _nsi_fetch_rows(
                        code=str(args.fss_nsi_code or NSI_FSS_CODE).strip(),
                        date_iso=nsi_date,
                        proxy=proxy,
                        max_rows=max(0, int(args.nsi_limit)),
                    )
                    parsed = _rows_from_nsi_fss(raw)
                    fss_total = upsert_fss_rows(db, parsed)
                    notes.append(f"fss_nsi_ok:{len(parsed)}")
                except Exception as e:
                    logger.error("FSS NSI API: недоступен после повторов: {}", e)
                    notes.append(f"fss_nsi_error:{e!s}")
                    http_failed = True

            if args.reo_csv and args.reo_csv.is_file():
                text = args.reo_csv.read_text(encoding="utf-8", errors="replace")
                parsed = _rows_from_csv_dicts(_read_csv_rows(text), kind="reo")
                reo_total = upsert_reo_rows(db, parsed)
                notes.append(f"reo_file={args.reo_csv.name}")
            elif reo_url:
                try:
                    text = registry_http_get_text(reo_url, headers=ua)
                    parsed = _rows_from_csv_dicts(_read_csv_rows(text), kind="reo")
                    reo_total = upsert_reo_rows(db, parsed)
                    notes.append("reo_url_ok")
                except Exception as e:
                    logger.error("REO_REGISTRY_SYNC_URL: недоступен после повторов: {}", e)
                    notes.append(f"reo_url_error:{e!s}")
                    http_failed = True
            elif not args.disable_nsi:
                try:
                    raw = _nsi_fetch_rows(
                        code=str(args.reo_nsi_code or NSI_REO_CODE).strip(),
                        date_iso=nsi_date,
                        proxy=proxy,
                        max_rows=max(0, int(args.nsi_limit)),
                    )
                    parsed = _rows_from_nsi_reo(raw)
                    reo_total = upsert_reo_rows(db, parsed)
                    notes.append(f"reo_nsi_ok:{len(parsed)}")
                except Exception as e:
                    logger.error("REO NSI API: недоступен после повторов: {}", e)
                    notes.append(f"reo_nsi_error:{e!s}")
                    http_failed = True

            if not fss_total and not args.fss_csv and not fss_url:
                notes.append("fss_skipped_no_source")
            if not reo_total and not args.reo_csv and not reo_url:
                notes.append("reo_skipped_no_source")

        db.commit()

    note = "; ".join(notes) or "ok"
    log_status = "error" if http_failed else ("ok" if (fss_total or reo_total or args.demo_seed) else "partial")
    append_sync_log(
        "state_registries_fss_reo",
        log_status,
        "v1",
        fss_total + reo_total,
        note[:2000],
    )
    print(f"fss_rows={fss_total} reo_rows={reo_total} ({note})")
    try:
        bump_preview_cache_revision("sync_state_registries")
    except Exception:
        pass
    return 1 if http_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
