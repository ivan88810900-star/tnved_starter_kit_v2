"""Сохранение расчётов платежей в CustomsCalculationHistory."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import String, cast, func

from ..db import SessionLocal, engine
from ..models import CustomsCalculationHistory, IngestedDocument

HISTORY_KINDS: frozenset[str] = frozenset(
    {"compute", "compare", "compliance", "copilot", "copilot_batch"},
)


def _filter_by_kind(q, kind: str):
    if engine.dialect.name == "sqlite":
        return q.filter(
            func.json_extract(CustomsCalculationHistory.input_payload, "$._history_kind") == kind,
        )
    jp = CustomsCalculationHistory.input_payload["_history_kind"]
    return q.filter(cast(jp, String) == kind)


def _parse_date_bound(s: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    if not s or not str(s).strip():
        return None
    t = str(s).strip()
    try:
        if len(t) == 10 and t[4] == "-" and t[7] == "-":
            d = datetime.fromisoformat(t)
            if end_of_day:
                d = d.replace(hour=23, minute=59, second=59, microsecond=999999)
            return d
        d = datetime.fromisoformat(t.replace("Z", "+00:00"))
        if d.tzinfo:
            d = d.astimezone(timezone.utc).replace(tzinfo=None)
        return d
    except ValueError:
        return None


def _history_filter_query(
    db,
    *,
    user_ref: str = "",
    document_id: str = "",
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
):
    q = db.query(CustomsCalculationHistory)
    ur = (user_ref or "").strip()
    if ur:
        q = q.filter(CustomsCalculationHistory.user_ref == ur)
    did = (document_id or "").strip()
    if did:
        q = q.filter(CustomsCalculationHistory.document_id == did)
    df = _parse_date_bound(created_from, end_of_day=False)
    dt = _parse_date_bound(created_to, end_of_day=True)
    if df:
        q = q.filter(CustomsCalculationHistory.created_at >= df)
    if dt:
        q = q.filter(CustomsCalculationHistory.created_at <= dt)
    return q


def _json_safe(data: Any) -> Any:
    try:
        return json.loads(json.dumps(data, default=str, ensure_ascii=False))
    except Exception:
        return {"error": "serialization", "repr": str(data)[:5000]}


def _resolve_document_id(db, document_id: Optional[str]) -> Optional[str]:
    if not document_id or not str(document_id).strip():
        return None
    did = str(document_id).strip()[:36]
    if db.query(IngestedDocument).filter(IngestedDocument.id == did).first():
        return did
    return None


def save_calculation_record(
    *,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    document_id: Optional[str] = None,
    user_ref: str = "",
    currency: str = "RUB",
    kind: str = "compute",
) -> str:
    inp = dict(input_payload)
    inp["_history_kind"] = kind

    with SessionLocal() as db:
        did = _resolve_document_id(db, document_id)
        rec = CustomsCalculationHistory(
            document_id=did,
            user_ref=(user_ref or "")[:128],
            input_payload=_json_safe(inp),
            output_payload=_json_safe(output_payload),
            currency=(currency or "RUB")[:8],
        )
        db.add(rec)
        db.commit()
        logger.debug(f"История расчёта сохранена: id={rec.id}, kind={kind}")
        return rec.id


def list_calculation_history(
    limit: int = 50,
    offset: int = 0,
    user_ref: str = "",
    kind: Optional[str] = None,
    document_id: str = "",
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    k = (kind or "").strip()
    if k and k not in HISTORY_KINDS:
        k = ""
    with SessionLocal() as db:
        q = _history_filter_query(
            db,
            user_ref=user_ref,
            document_id=document_id,
            created_from=created_from,
            created_to=created_to,
        )
        if k:
            q = _filter_by_kind(q, k)
        q = q.order_by(CustomsCalculationHistory.created_at.desc())
        rows = q.offset(offset).limit(limit).all()
        return [_history_list_row(r) for r in rows]


def list_history_for_ingested_document(document_id: str, limit: int = 100) -> Optional[list[dict[str, Any]]]:
    """None если документа нет в ingested_documents."""
    limit = max(1, min(limit, 500))
    did = (document_id or "").strip()[:36]
    if not did:
        return None
    with SessionLocal() as db:
        if not db.query(IngestedDocument).filter(IngestedDocument.id == did).first():
            return None
    return list_calculation_history(limit=limit, offset=0, document_id=did)


def summarize_calculation_history(
    user_ref: str = "",
    document_id: str = "",
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
) -> dict[str, Any]:
    with SessionLocal() as db:
        q0 = _history_filter_query(
            db,
            user_ref=user_ref,
            document_id=document_id,
            created_from=created_from,
            created_to=created_to,
        )
        total = q0.count()
        by_kind: dict[str, int] = {}
        for name in sorted(HISTORY_KINDS):
            qn = _history_filter_query(
                db,
                user_ref=user_ref,
                document_id=document_id,
                created_from=created_from,
                created_to=created_to,
            )
            by_kind[name] = _filter_by_kind(qn, name).count()
        other = max(0, total - sum(by_kind.values()))
        return {
            "total": total,
            "by_kind": by_kind,
            "other": other,
            "kinds": sorted(HISTORY_KINDS),
        }


def export_calculation_history_rows(
    *,
    user_ref: str = "",
    kind: Optional[str] = None,
    document_id: str = "",
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    limit: int = 5000,
    full_json: bool = False,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 10_000))
    k = (kind or "").strip()
    if k and k not in HISTORY_KINDS:
        k = ""
    with SessionLocal() as db:
        q = _history_filter_query(
            db,
            user_ref=user_ref,
            document_id=document_id,
            created_from=created_from,
            created_to=created_to,
        )
        if k:
            q = _filter_by_kind(q, k)
        q = q.order_by(CustomsCalculationHistory.created_at.desc())
        rows = q.limit(limit).all()
        out: list[dict[str, Any]] = []
        for r in rows:
            base = _history_list_row(r)
            if full_json:
                base["input_payload"] = r.input_payload
                base["output_payload"] = r.output_payload
            out.append(base)
        return out


def calculation_history_as_csv(rows: list[dict[str, Any]]) -> str:
    fields = ["id", "created_at", "kind", "user_ref", "document_id", "hs_code", "total_payable", "currency"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for row in rows:
        flat = {k: row.get(k) for k in fields}
        w.writerow(flat)
    return buf.getvalue()


def _history_list_row(r: CustomsCalculationHistory) -> dict[str, Any]:
    inp = r.input_payload if isinstance(r.input_payload, dict) else {}
    out = r.output_payload if isinstance(r.output_payload, dict) else {}
    kind = str(inp.get("_history_kind") or "")
    hs_code: Any = inp.get("hs_code")
    total: Any = None

    if kind == "compliance":
        items_s = out.get("items_summary") or []
        if isinstance(items_s, list) and items_s:
            total = sum(float(x.get("total_payable") or 0) for x in items_s if isinstance(x, dict))
            first = items_s[0] if items_s else None
            hc = first.get("hs_code") if isinstance(first, dict) else None
            if hc:
                hs_code = f"{hc} +{len(items_s) - 1}" if len(items_s) > 1 else hc
    elif kind == "copilot_batch":
        pays = out.get("payments") or []
        if isinstance(pays, list) and pays:
            total = sum(float(x.get("total") or 0) for x in pays if isinstance(x, dict))
        hs_code = hs_code or "batch"
    elif kind == "copilot":
        total = (out.get("breakdown") or {}).get("total_payable")
        hs_code = hs_code or inp.get("effective_hs_code") or inp.get("hs_code")
    else:
        total = (out.get("breakdown") or {}).get("total_payable")

    return {
        "id": r.id,
        "document_id": r.document_id,
        "user_ref": r.user_ref,
        "currency": r.currency,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "hs_code": hs_code,
        "kind": kind or None,
        "total_payable": total,
    }


def get_calculation_record(calc_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as db:
        r = db.query(CustomsCalculationHistory).filter(CustomsCalculationHistory.id == calc_id).first()
        if not r:
            return None
        return {
            "id": r.id,
            "document_id": r.document_id,
            "user_ref": r.user_ref,
            "currency": r.currency,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "input_payload": r.input_payload,
            "output_payload": r.output_payload,
        }
