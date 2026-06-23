"""Локальный lookup сертификатов/деклараций и метаданные актуальности opendata."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ..db import SessionLocal
from ..models.tnved import FsaCertificate, OpendataSyncLog
from .permits_service import build_fsa_manual_link, normalize_number

OPENDATA_FSA_SOURCE = "открытые данные Росаккредитации (fsa.gov.ru/opendata)"
OPENDATA_TROIS_SOURCE = "открытые данные ФТС России (customs.gov.ru/opendata)"


def get_sync_freshness(source_key: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        row = (
            db.query(OpendataSyncLog)
            .filter(OpendataSyncLog.source_key == source_key, OpendataSyncLog.status == "ok")
            .order_by(OpendataSyncLog.id.desc())
            .first()
        )
    if not row:
        return None
    return {
        "source_key": row.source_key,
        "dataset_id": row.dataset_id,
        "snapshot_id": row.snapshot_id,
        "data_as_of": row.data_as_of,
        "synced_at": row.synced_at,
        "row_count": row.row_count,
    }


def _parse_ru_date(s: str) -> datetime | None:
    s = (s or "").strip()
    for fmt in ("%d.%m.%Y", "%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt)
        except ValueError:
            continue
    return None


def _registry_status_to_verify(status: str, expiry: str) -> str:
    st = (status or "").lower()
    if any(x in st for x in ("недейств", "прекращ", "аннулир", "отозван", "приостанов")):
        return "NOT_FOUND"
    exp = _parse_ru_date(expiry)
    if exp and exp.date() < datetime.utcnow().date():
        return "NOT_FOUND"
    if any(x in st for x in ("действ", "архив")):
        return "VALID"
    return "VALID" if status else "UNKNOWN"


def lookup_fsa_certificate(number: str, doc_type: str) -> dict[str, Any] | None:
    norm = normalize_number(number)
    if not norm:
        return None
    with SessionLocal() as db:
        row = (
            db.query(FsaCertificate)
            .filter(FsaCertificate.registry_number == norm)
            .one_or_none()
        )
        if row is None:
            # fuzzy: без пробелов иногда отличается регистр ЕАЭС
            rows = db.query(FsaCertificate).filter(FsaCertificate.registry_number.ilike(f"%{norm[-20:]}%")).limit(5).all()
            for candidate in rows:
                if normalize_number(candidate.registry_number) == norm:
                    row = candidate
                    break
        if row is None:
            return None

    verify_status = _registry_status_to_verify(row.status, row.expiry_date)
    codes = [c.strip() for c in re.split(r"[,;\s]+", row.tn_ved_codes or "") if c.strip()]
    freshness = get_sync_freshness("fsa_rss" if doc_type == "СС" else "fsa_rds") or get_sync_freshness(
        "fsa_rds" if doc_type == "ДС" else "fsa_rss"
    )
    data_as_of = (freshness or {}).get("data_as_of", "")
    return {
        "type": doc_type,
        "status": verify_status,
        "number": norm,
        "holder": row.applicant or row.manufacturer or None,
        "valid_from": row.issue_date or None,
        "valid_to": row.expiry_date or None,
        "registry_link": build_fsa_manual_link(doc_type, norm),
        "registry_source": OPENDATA_FSA_SOURCE,
        "data_as_of": data_as_of,
        "source_kind": "opendata_local",
        "raw": {
            "registry_tnved_codes": codes[:50],
            "product_name": row.product_name,
            "tr_ts": row.tr_ts,
            "fsa_status": row.status,
            "snapshot": row.source_snapshot,
        },
    }


def search_fsa_by_tnved(code: str, *, doc_type: str = "", limit: int = 25) -> list[dict[str, Any]]:
    prefix = re.sub(r"\D", "", code or "")[:10]
    if len(prefix) < 4:
        return []
    with SessionLocal() as db:
        q = db.query(FsaCertificate)
        if doc_type in ("СС", "ДС"):
            q = q.filter(FsaCertificate.doc_type == doc_type)
        rows = q.filter(FsaCertificate.tn_ved_codes.contains(prefix)).limit(limit * 3).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        codes = [re.sub(r"\D", "", c) for c in re.split(r"[,;\s]+", row.tn_ved_codes or "")]
        if not any(c.startswith(prefix) or prefix.startswith(c[: len(prefix)]) for c in codes if c):
            continue
        out.append(
            {
                "registry_number": row.registry_number,
                "doc_type": row.doc_type,
                "status": row.status,
                "applicant": row.applicant,
                "manufacturer": row.manufacturer,
                "product_name": row.product_name[:200],
                "tn_ved_codes": row.tn_ved_codes,
                "tr_ts": row.tr_ts[:200] if row.tr_ts else "",
                "issue_date": row.issue_date,
                "expiry_date": row.expiry_date,
            }
        )
        if len(out) >= limit:
            break
    return out
