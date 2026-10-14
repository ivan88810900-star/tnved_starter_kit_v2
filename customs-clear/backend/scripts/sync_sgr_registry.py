#!/usr/bin/env python3
"""
Загрузка в таблицу ``sgr_certificates`` данных Единого реестра СГР (ЕАЭС).

Источники (по приоритету):

1. **OData портала ЕЭК** — задайте ``SGR_ODATA_LIST_TITLE`` (точное наименование списка НСИ из каталога реестров
   ``portal.eaeunion.org``). Пагинация по полю ``__next`` / ``odata.nextLink`` в ответе JSON.
   Инкремент: в ``data/sgr_sync_checkpoint.json`` хранится ``last_modified_iso`` — при повторном запуске
   добавляется ``$filter=Modified gt datetime'<...>'`` (если поле ``Modified`` присутствует в ответе).

2. **CSV** — ``SGR_REGISTRY_SYNC_URL`` или ``--csv`` (UTF-8; разделитель ``;`` или ``,``).

Колонки CSV: ``sgr_number``, ``product_name``, ``manufacturer``, ``brand``, ``recipient``, ``status``, ``issue_date`` (YYYY-MM-DD).

Запуск из ``customs-clear/backend``::

  python3 scripts/sync_sgr_registry.py
  python3 scripts/sync_sgr_registry.py --demo-seed
  python3 scripts/sync_sgr_registry.py --csv /path/to/sgr_export.csv
  python3 scripts/sync_sgr_registry.py --odata --reset-checkpoint   # сбросить фильтр Modified
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loguru import logger
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.core import SgrCertificate, SgrRegistryRawRevision
from app.services.normative_store import append_sync_log, init_db
from app.services.preview_cache_revision import bump_preview_cache_revision
from app.services.registry_sync_http import registry_http_get, registry_http_get_text

CHECKPOINT_PATH = ROOT / "data" / "sgr_sync_checkpoint.json"
UA = {"User-Agent": "customs-clear-sgr-sync/1.0"}
DEFAULT_SGR_ODATA_LIST_TITLE = "Единый реестр свидетельств о государственной регистрации"
NSI_BASE_API = "https://nsi.eaeunion.org/portal/api"
NSI_SGR_CODE = "1995"
NSI_SGR_MAX_BATCH_SIZE = 1500


def _parse_dt(val: str | None) -> datetime | None:
    if not val or not str(val).strip():
        return None
    s = str(val).strip()
    if "T" in s:
        s = s.split("T")[0][:10]
    else:
        s = s[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _load_checkpoint() -> dict[str, Any]:
    if not CHECKPOINT_PATH.is_file():
        return {}
    try:
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_checkpoint(data: dict[str, Any]) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _row_from_csv_dict(d: dict[str, str]) -> dict[str, Any] | None:
    num = (
        d.get("sgr_number")
        or d.get("номер")
        or d.get("number")
        or d.get("№ свидетельства")
        or ""
    ).strip()
    if not num:
        return None
    return {
        "sgr_number": num[:128],
        "product_name": (d.get("product_name") or d.get("наименование") or d.get("продукция") or "")[:16000],
        "manufacturer": (d.get("manufacturer") or d.get("изготовитель") or "")[:512],
        "brand": (d.get("brand") or d.get("бренд") or d.get("торговая марка") or "")[:512],
        "recipient": (d.get("recipient") or d.get("заявитель") or "")[:512],
        "status": (d.get("status") or d.get("статус") or "")[:128],
        "issue_date": _parse_dt(d.get("issue_date") or d.get("дата") or d.get("дата выдачи")),
    }


def _is_sqlite(db: Session) -> bool:
    return db.bind.dialect.name == "sqlite"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _source_value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return _canonical_json(value)
    return str(value)


def _insert_nsi_raw_revision(db: Session, row: dict[str, Any]) -> None:
    raw_sha256 = str(row.get("_nsi_raw_sha256") or "")
    if not raw_sha256:
        return
    payload = {
        "sgr_number": row["sgr_number"],
        "source_record_id": row.get("_nsi_source_record_id") or "",
        "source_version_id": row.get("_nsi_source_version_id"),
        "date_time_from": row.get("_nsi_date_time_from") or "",
        "date_time_to": row.get("_nsi_date_time_to") or "",
        "update_datetime": row.get("_nsi_update_datetime") or "",
        "date_time_updated": row.get("_nsi_date_time_updated") or "",
        "raw_json": row["_nsi_raw_json"],
        "raw_sha256": raw_sha256,
    }
    if _is_sqlite(db):
        stmt = sqlite_insert(SgrRegistryRawRevision.__table__).values(**payload)
        db.execute(stmt.on_conflict_do_nothing(index_elements=["raw_sha256"]))
        return
    if db.bind.dialect.name == "postgresql":
        stmt = postgresql_insert(SgrRegistryRawRevision.__table__).values(**payload)
        db.execute(stmt.on_conflict_do_nothing(index_elements=["raw_sha256"]))
        return
    exists = (
        db.query(SgrRegistryRawRevision.id)
        .filter(SgrRegistryRawRevision.raw_sha256 == raw_sha256)
        .first()
    )
    if not exists:
        db.add(SgrRegistryRawRevision(**payload))
        db.flush()


def upsert_sgr(db: Session, row: dict[str, Any]) -> None:
    num = row["sgr_number"]
    payload = {
        "sgr_number": num,
        "product_name": row.get("product_name") or "",
        "manufacturer": row.get("manufacturer") or "",
        "brand": row.get("brand") or "",
        "recipient": row.get("recipient") or "",
        "status": row.get("status") or "",
        "issue_date": row.get("issue_date"),
    }
    provenance_update: dict[str, Any] = {}
    if row.get("_nsi_raw_sha256"):
        _insert_nsi_raw_revision(db, row)
        provenance_update = {
            "doc_norm": row.get("doc_norm") or "",
            "doc_usearea": row.get("doc_usearea") or "",
            "source_raw_sha256": row["_nsi_raw_sha256"],
        }
        payload.update(provenance_update)
    if _is_sqlite(db):
        stmt = sqlite_insert(SgrCertificate.__table__).values(**payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["sgr_number"],
            set_={
                "product_name": stmt.excluded.product_name,
                "manufacturer": stmt.excluded.manufacturer,
                "brand": stmt.excluded.brand,
                "recipient": stmt.excluded.recipient,
                "status": stmt.excluded.status,
                "issue_date": stmt.excluded.issue_date,
                **{key: getattr(stmt.excluded, key) for key in provenance_update},
            },
        )
        db.execute(stmt)
        return
    obj = db.query(SgrCertificate).filter(SgrCertificate.sgr_number == num).first()
    if obj:
        obj.product_name = row.get("product_name") or obj.product_name
        obj.manufacturer = row.get("manufacturer") or obj.manufacturer
        obj.brand = row.get("brand") or obj.brand
        obj.recipient = row.get("recipient") or obj.recipient
        obj.status = row.get("status") or obj.status
        if row.get("issue_date") is not None:
            obj.issue_date = row["issue_date"]
        if provenance_update:
            obj.doc_norm = provenance_update["doc_norm"]
            obj.doc_usearea = provenance_update["doc_usearea"]
            obj.source_raw_sha256 = provenance_update["source_raw_sha256"]
    else:
        db.add(SgrCertificate(**payload))


def _parse_sharepoint_item(it: dict[str, Any]) -> dict[str, Any] | None:
    """Гибкий разбор полей элемента SharePoint REST (имена полей в реестрах НСИ могут отличаться)."""
    flat: dict[str, str] = {}
    for k, v in it.items():
        if k.startswith("__") or k == "Attachments":
            continue
        if isinstance(v, dict):
            continue
        flat[str(k).lower()] = str(v).strip() if v is not None else ""

    def pick(*keys: str) -> str:
        for key in keys:
            for fk, fv in flat.items():
                if key in fk and fv:
                    return fv
        return ""

    blob = " ".join(flat.values())
    mnum = re.search(
        r"RU\.[\dA-ZА-ЯЁа-яё]{1,3}\.[\dA-ZА-ЯЁа-яё]{1,3}\.[\dA-ZА-ЯЁа-яё]{1,3}\.[\dA-ZА-ЯЁа-яё]{1,4}\.[\dA-ZА-ЯЁа-яё]{1}\.[\dA-ZА-ЯЁа-яё.]{6,}",
        blob,
        flags=re.IGNORECASE,
    )
    num = (mnum.group(0).strip() if mnum else "") or pick("sgr", "certificate", "номер", "registration", "title")
    if not num or len(num) < 8:
        return None
    return {
        "sgr_number": num[:128],
        "product_name": pick("product", "наимен", "назван", "composition", "состав")[:16000],
        "manufacturer": pick("manuf", "изготов", "producer")[:512],
        "brand": pick("brand", "trademark", "торгов", "марк")[:512],
        "recipient": pick("recipient", "заявит", "applicant")[:512],
        "status": pick("status", "статус", "state")[:128],
        "issue_date": _parse_dt(pick("issue", "дата", "created")),
    }


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
                headers={**UA, "Accept": "application/json", "Content-Type": "application/json"},
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


def _nsi_sgr_total(*, code: str, date_iso: str, proxy: str = "") -> int:
    url = f"{NSI_BASE_API}/dictionaries/{code}/get-list-data-total"
    payload = {"date": date_iso, "filter": [{"code": "searchText", "value": "", "conditionType": "like"}]}
    data = _http_post_json(url, payload, proxy=proxy)
    if not isinstance(data, dict):
        raise RuntimeError("NSI SGR total response has unsupported shape")
    for k in ("byFilterCount", "totalCount", "count"):
        if k not in data:
            continue
        raw = data.get(k)
        try:
            if isinstance(raw, bool):
                raise ValueError("boolean is not a row count")
            total = int(raw)
            if isinstance(raw, float) and not raw.is_integer():
                raise ValueError("fractional row count")
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"NSI SGR total field {k!r} is malformed") from exc
        if total < 0:
            raise RuntimeError(f"NSI SGR total field {k!r} is negative")
        return total
    raise RuntimeError("NSI SGR total response has no supported count field")


def _nsi_sgr_rows(
    *,
    code: str,
    date_iso: str,
    proxy: str = "",
    max_rows: int = 0,
    batch_size: int = 500,
) -> tuple[list[dict[str, Any]], int, bool]:
    total = _nsi_sgr_total(code=code, date_iso=date_iso, proxy=proxy)
    requested_max = int(max_rows)
    target = min(total, requested_max) if requested_max > 0 else total
    is_partial = requested_max > 0 and requested_max < total
    if target == 0:
        return [], total, is_partial
    url = f"{NSI_BASE_API}/dictionaries/{code}/get-list-data"
    out: list[dict[str, Any]] = []
    offset = 0
    step = max(1, min(NSI_SGR_MAX_BATCH_SIZE, int(batch_size)))
    while offset < target:
        payload = {
            "date": date_iso,
            "offset": int(offset),
            "limit": int(min(step, target - offset)),
            "filter": [{"code": "searchText", "value": "", "conditionType": "like"}],
            "sort": [],
        }
        data = _http_post_json(url, payload, proxy=proxy)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            supported_keys = ("records", "content", "result", "data")
            page_key = next((key for key in supported_keys if key in data), None)
            if page_key is None:
                raise RuntimeError(f"NSI SGR page at offset {offset} has unsupported shape")
            rows = data.get(page_key)
        else:
            raise RuntimeError(f"NSI SGR page at offset {offset} has unsupported shape")
        if not isinstance(rows, list):
            raise RuntimeError(f"NSI SGR page at offset {offset} is not a list")
        if not rows:
            raise RuntimeError(
                f"NSI SGR pagination exhausted at offset {offset} before target {target}"
            )
        if len(rows) > payload["limit"]:
            raise RuntimeError(
                f"NSI SGR page at offset {offset} exceeds requested limit {payload['limit']}"
            )
        if not all(isinstance(row, dict) for row in rows):
            raise RuntimeError(f"NSI SGR page at offset {offset} contains a non-object row")
        out.extend(rows)
        offset += len(rows)
        # A short page is not proof of exhaustion: the NSI endpoint can return
        # uneven page sizes. Continue from the actual row count until target.
    if len(out) != target:
        raise RuntimeError(f"NSI SGR fetched {len(out)} rows, expected {target}")
    return out, total, is_partial


def _row_from_nsi_dict(item: dict[str, Any]) -> dict[str, Any] | None:
    data = item.get("data") if isinstance(item, dict) else None
    if not isinstance(data, dict):
        return None
    num = str(data.get("NUMB_DOC") or "").strip()
    if not num:
        return None
    status_raw = data.get("STATUS")
    status = (
        str(status_raw.get("name") or "").strip()
        if isinstance(status_raw, dict)
        else str(status_raw or "").strip()
    )
    raw_json = _canonical_json(item)
    raw_sha256 = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
    version_id = item.get("versionId")
    return {
        "sgr_number": num[:128],
        "product_name": str(data.get("NAME_PROD") or "")[:16000],
        "manufacturer": str(data.get("FIRMMADE_NAME") or "")[:512],
        "brand": "",
        "recipient": str(data.get("FIRMGET_NAME") or "")[:512],
        "status": status[:128],
        "issue_date": _parse_dt(str(data.get("DATE_DOC") or "")),
        "doc_norm": _source_value_text(data.get("DOC_NORM")),
        "doc_usearea": _source_value_text(data.get("DOC_USEAREA")),
        "_nsi_source_record_id": _source_value_text(item.get("id"))[:128],
        "_nsi_source_version_id": (
            _source_value_text(version_id)[:128] if version_id is not None else None
        ),
        "_nsi_date_time_from": _source_value_text(item.get("dateTimeFrom"))[:64],
        "_nsi_date_time_to": _source_value_text(item.get("dateTimeTo"))[:64],
        "_nsi_update_datetime": _source_value_text(item.get("updateDateTime"))[:64],
        "_nsi_date_time_updated": _source_value_text(item.get("dateTimeUpdated"))[:64],
        "_nsi_raw_json": raw_json,
        "_nsi_raw_sha256": raw_sha256,
    }


def sync_from_nsi(
    db: Session,
    *,
    code: str,
    date_iso: str,
    proxy: str = "",
    max_rows: int = 0,
) -> tuple[int, str]:
    rows, official_total, is_partial = _nsi_sgr_rows(
        code=code,
        date_iso=date_iso,
        proxy=proxy,
        max_rows=max_rows,
    )
    parsed_rows: list[dict[str, Any]] = []
    for index, item in enumerate(rows):
        row = _row_from_nsi_dict(item)
        if not row:
            raise RuntimeError(f"NSI SGR row {index} is malformed or has no NUMB_DOC")
        parsed_rows.append(row)

    n = 0
    for row in parsed_rows:
        upsert_sgr(db, row)
        n += 1
    if is_partial:
        return n, f"nsi_partial:max_rows={len(rows)};official_total={official_total}"
    return n, "nsi_ok"


def sync_from_odata(db: Session, *, list_title: str, reset_checkpoint: bool) -> tuple[int, str]:
    cp = {} if reset_checkpoint else _load_checkpoint()
    last_mod = (cp.get("last_modified_iso") or "").strip()
    enc_title = list_title.replace("'", "''")
    base = (
        "https://portal.eaeunion.org/sites/odata/_api/web/lists"
        f"/getByTitle('{enc_title}')/items"
    )
    headers = {**UA, "Accept": "application/json;odata=verbose"}
    total = 0
    max_modified: str | None = None
    url: str | None = base + "?$top=200"
    if last_mod:
        # OData datetime literal for SharePoint
        safe = last_mod.replace("'", "''")
        url = base + f"?$top=200&$filter=Modified gt datetime'{safe}'"

    pages = 0
    while url and pages < 50_000:
        try:
            r = registry_http_get(url, headers=headers)
        except Exception as e:
            logger.error("SGR OData: HTTP после повторов: {}", e)
            return total, f"odata_http_error:{e!s}"
        try:
            payload = r.json()
        except Exception as e:
            return total, f"odata_json_error:{e!s}"

        if isinstance(payload.get("value"), list):
            results = payload["value"]
            next_link = payload.get("@odata.nextLink") or payload.get("odata.nextLink")
        else:
            d = payload.get("d") or {}
            if isinstance(d, dict):
                results = d.get("results") or []
                next_link = d.get("__next") or payload.get("odata.nextLink")
            else:
                results = []
                next_link = None

        if not isinstance(results, list):
            return total, "odata_unexpected_shape"

        for it in results:
            if not isinstance(it, dict):
                continue
            row = _parse_sharepoint_item(it)
            if not row:
                continue
            upsert_sgr(db, row)
            total += 1
            mod = str(it.get("Modified") or it.get("LastModifiedDate") or "").strip()
            if mod and (max_modified is None or mod > max_modified):
                max_modified = mod[:30]

        pages += 1
        if isinstance(next_link, str) and next_link.startswith("http"):
            url = next_link
        elif isinstance(next_link, str) and next_link.startswith("/"):
            url = f"https://portal.eaeunion.org{next_link}"
        else:
            url = None

    if max_modified:
        cp["last_modified_iso"] = max_modified
    cp["last_run_at"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    _save_checkpoint(cp)
    return total, "odata_ok"


def sync_from_csv_text(db: Session, text: str, *, since_date: datetime | None) -> int:
    n = 0
    for d in _read_csv_rows(text):
        row = _row_from_csv_dict(d)
        if not row:
            continue
        if since_date and row.get("issue_date") and row["issue_date"] < since_date:
            continue
        upsert_sgr(db, row)
        n += 1
    return n


def demo_seed(db: Session) -> int:
    rows = [
        {
            "sgr_number": "RU.77.99.88.002.Е.000123.01.26",
            "product_name": "Косметика для ухода за лицом: гели, тоники, лосьоны, торговая марка DemoCosmetics",
            "manufacturer": "OOO Demo Plant",
            "brand": "DemoCosmetics",
            "recipient": "OOO Заявитель Демо",
            "status": "действует",
            "issue_date": _parse_dt("2025-06-01"),
        },
        {
            "sgr_number": "RU.77.01.02.003.Е.000999.01.25",
            "product_name": "Очищающий гель для лица, серия ухода, бренд DemoCosmetics",
            "manufacturer": "OOO Demo Plant",
            "brand": "DemoCosmetics",
            "recipient": "OOO Заявитель Демо",
            "status": "подписан",
            "issue_date": _parse_dt("2024-11-15"),
        },
    ]
    for row in rows:
        upsert_sgr(db, row)
    return len(rows)


def _sgr_sync_log_status(
    *,
    total: int,
    note_parts: list[str],
    http_failed: bool,
    demo_seed_enabled: bool,
) -> str:
    if http_failed:
        return "error"
    nsi_messages = [part.removeprefix("auto_nsi:") for part in note_parts]
    if any(message.startswith("nsi_partial:") for message in nsi_messages):
        return "partial"
    if total or demo_seed_enabled or "nsi_ok" in nsi_messages:
        return "ok"
    return "partial"


def main() -> int:
    ap = argparse.ArgumentParser(description="Синхронизация реестра СГР")
    ap.add_argument("--csv", type=Path, default=None, help="Локальный CSV выгрузки СГР")
    ap.add_argument("--odata", action="store_true", help="Загрузка через OData (нужен SGR_ODATA_LIST_TITLE)")
    ap.add_argument("--reset-checkpoint", action="store_true", help="Сбросить чекпоинт инкрементальной OData-синхронизации")
    ap.add_argument("--since", type=str, default=None, help="Для CSV: пропускать строки с issue_date раньше YYYY-MM-DD")
    ap.add_argument(
        "--full-load",
        action="store_true",
        help="Полная загрузка без инкремента/чекпоинтов (не применять фильтры даты)",
    )
    ap.add_argument("--demo-seed", action="store_true", help="Вставить демо-строки для тестов")
    ap.add_argument(
        "--nsi",
        action="store_true",
        help=f"Загрузка через официальный NSI API по коду словаря (по умолчанию {NSI_SGR_CODE})",
    )
    ap.add_argument(
        "--nsi-code",
        type=str,
        default=NSI_SGR_CODE,
        help=f"Код словаря NSI для СГР (по умолчанию {NSI_SGR_CODE})",
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
        help="Лимит строк NSI (0 = все строки)",
    )
    ap.add_argument(
        "--proxy",
        type=str,
        default="",
        help="Опциональный прокси для HTTP-запросов (например, http://user:pass@host:port)",
    )
    args = ap.parse_args()

    init_db()
    proxy = (args.proxy or "").strip()
    if proxy:
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
    since_dt = None if args.full_load else (_parse_dt(args.since) if args.since else None)
    nsi_date = (args.nsi_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
    if since_dt is None and not args.demo_seed and not args.reset_checkpoint and not args.full_load:
        cp0 = _load_checkpoint()
        if cp0.get("last_issue_date"):
            since_dt = _parse_dt(cp0["last_issue_date"])

    note_parts: list[str] = []
    total = 0
    http_failed = False

    with SessionLocal() as db:
        if args.demo_seed:
            total = demo_seed(db)
            note_parts.append("demo_seed")
        elif args.nsi:
            n, msg = sync_from_nsi(
                db,
                code=str(args.nsi_code or NSI_SGR_CODE).strip(),
                date_iso=nsi_date,
                proxy=proxy,
                max_rows=max(0, int(args.nsi_limit)),
            )
            total = n
            note_parts.append(msg)
        elif args.odata:
            title = (os.getenv("SGR_ODATA_LIST_TITLE") or DEFAULT_SGR_ODATA_LIST_TITLE).strip()
            if not title:
                print("Задайте переменную окружения SGR_ODATA_LIST_TITLE (наименование списка НСИ на portal.eaeunion.org).")
                return 2
            n, msg = sync_from_odata(db, list_title=title, reset_checkpoint=(args.reset_checkpoint or args.full_load))
            total = n
            note_parts.append(msg)
            if msg.startswith("odata_http_error") or msg.startswith("odata_json_error"):
                http_failed = True
        elif args.csv and args.csv.is_file():
            text = args.csv.read_text(encoding="utf-8", errors="replace")
            total = sync_from_csv_text(db, text, since_date=since_dt)
            note_parts.append(f"csv={args.csv.name}")
        else:
            url = (os.getenv("SGR_REGISTRY_SYNC_URL") or "").strip()
            if url:
                try:
                    text = registry_http_get_text(url, headers=UA)
                    total = sync_from_csv_text(db, text, since_date=since_dt)
                    note_parts.append("csv_url")
                except Exception as e:
                    logger.error("SGR_REGISTRY_SYNC_URL: недоступен после повторов: {}", e)
                    note_parts.append(f"csv_url_error:{e!s}")
                    http_failed = True
            else:
                # Официальный fallback без ручной конфигурации env: сначала NSI API, затем OData.
                try:
                    n, msg = sync_from_nsi(
                        db,
                        code=str(args.nsi_code or NSI_SGR_CODE).strip(),
                        date_iso=nsi_date,
                        proxy=proxy,
                        max_rows=max(0, int(args.nsi_limit)),
                    )
                    total = n
                    note_parts.append(f"auto_nsi:{msg}")
                except Exception as e:
                    logger.warning("SGR NSI fallback failed: {}", e)
                    title = (os.getenv("SGR_ODATA_LIST_TITLE") or DEFAULT_SGR_ODATA_LIST_TITLE).strip()
                    n, msg = sync_from_odata(db, list_title=title, reset_checkpoint=(args.reset_checkpoint or args.full_load))
                    total = n
                    note_parts.append(f"auto_odata:{msg}")
                    if msg.startswith("odata_http_error") or msg.startswith("odata_json_error"):
                        http_failed = True

        db.commit()

    if total and since_dt:
        cp = _load_checkpoint()
        cp["last_issue_date"] = args.since or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _save_checkpoint(cp)

    note = "; ".join(note_parts) or "ok"
    log_status = _sgr_sync_log_status(
        total=total,
        note_parts=note_parts,
        http_failed=http_failed,
        demo_seed_enabled=args.demo_seed,
    )
    append_sync_log(
        "sgr_registry",
        log_status,
        "v1",
        total,
        note[:2000],
    )
    print(f"sgr_rows={total} ({note})")
    try:
        bump_preview_cache_revision("sync_sgr_registry")
    except Exception:
        pass
    return 1 if http_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
