"""Сохранение загрузок документов в БД: IngestedDocument + ParsedInvoiceLine."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from loguru import logger
from sqlalchemy import func

from ..db import SessionLocal
from ..models import IngestedDocument, ParsedInvoiceLine


def _fingerprint(raw_text: str, filename: str) -> str:
    h = hashlib.sha256()
    h.update((filename or "").encode("utf-8", errors="ignore"))
    h.update(b"\0")
    h.update((raw_text or "").encode("utf-8", errors="ignore")[:2_000_000])
    return h.hexdigest()


def _detect_lang(text: str) -> str:
    t = (text or "")[:8000]
    if not t.strip():
        return ""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", t))
    cyr = len(re.findall(r"[\u0400-\u04ff]", t))
    lat = len(re.findall(r"[A-Za-z]", t))
    if cjk > max(cyr, lat) * 0.3 and cjk > 20:
        return "zh" if cjk > cyr else "mixed"
    if cyr > lat:
        return "ru"
    if lat > 10:
        return "en"
    return "mixed"


def _json_safe(data: Any) -> Any:
    try:
        return json.loads(json.dumps(data, default=str, ensure_ascii=False))
    except Exception:
        return {"_note": "payload_serialization_truncated", "repr": str(data)[:2000]}


def _hs_map_from_declaration_draft(draft: Any) -> dict[int, tuple[str, float | None]]:
    out: dict[int, tuple[str, float | None]] = {}
    if not isinstance(draft, dict):
        return out
    for row in draft.get("declaration_lines") or []:
        if not isinstance(row, dict):
            continue
        try:
            ln = int(row.get("line") or 0)
        except (TypeError, ValueError):
            continue
        hs = re.sub(r"\D", "", str(row.get("hs_code") or ""))[:10]
        if not ln or not hs:
            continue
        src = str(row.get("hs_code_source") or "")
        conf = 0.85 if "ии" in src else 0.55
        out[ln] = (hs.ljust(10, "0")[:12], conf)
    return out


def persist_extracted_bundle(
    *,
    original_filename: str,
    mime_type: str,
    invoice_data: dict[str, Any],
    packing_data: Optional[dict[str, Any]],
    api_response_snapshot: dict[str, Any],
    declaration_draft: Optional[dict[str, Any]] = None,
    status: str = "llm_structured",
) -> str:
    """
    Создаёт IngestedDocument и строки ParsedInvoiceLine.
    Возвращает id документа (UUID).
    """
    raw_text = str(invoice_data.get("raw_text") or "")
    fp = _fingerprint(raw_text, original_filename or "")
    hs_by_line = _hs_map_from_declaration_draft(declaration_draft or api_response_snapshot.get("declaration_draft"))

    structured = _json_safe(
        {
            "validation": {
                "status": api_response_snapshot.get("status"),
                "summary": api_response_snapshot.get("summary"),
                "invoice_number": api_response_snapshot.get("invoice_number"),
            },
            "packing_summary": (packing_data or {}).get("summary") if packing_data else None,
            "declaration_draft_summary": (declaration_draft or {}).get("summary")
            if isinstance(declaration_draft, dict)
            else None,
            "extracted_permits": api_response_snapshot.get("extracted_permits"),
            "permits_registry_note": api_response_snapshot.get("permits_registry_note"),
        }
    )

    items = list(invoice_data.get("items") or [])
    if not items and raw_text.strip():
        items = [
            {
                "line": 1,
                "description": raw_text.strip()[:4000],
                "quantity": 0.0,
                "unit": "",
                "weight_gross": 0.0,
                "weight_net": 0.0,
                "unit_price": 0.0,
                "total_price": 0.0,
                "packages": 0.0,
            }
        ]

    with SessionLocal() as db:
        doc = IngestedDocument(
            original_filename=(original_filename or "invoice")[:512],
            mime_type=(mime_type or "application/octet-stream")[:128],
            storage_uri="",
            file_sha256=fp,
            detected_lang=_detect_lang(raw_text)[:16],
            status=status[:32],
            raw_text=raw_text[:500_000] if len(raw_text) > 500_000 else raw_text,
            structured_payload=structured,
        )
        db.add(doc)
        db.flush()

        for it in items:
            try:
                line_no = int(it.get("line") or 0)
            except (TypeError, ValueError):
                line_no = 0
            if line_no <= 0:
                line_no = items.index(it) + 1
            desc = str(it.get("description") or "").strip()
            hs_pair = hs_by_line.get(line_no)
            suggested_hs = (hs_pair[0] if hs_pair else "")[:12]
            hs_conf = hs_pair[1] if hs_pair else None

            pl = ParsedInvoiceLine(
                document_id=doc.id,
                line_no=line_no,
                description_original=desc[:20000],
                description_ru="",
                quantity=float(it.get("quantity") or 0.0),
                unit=str(it.get("unit") or "")[:32],
                unit_price=float(it.get("unit_price") or 0.0),
                line_total=float(it.get("total_price") or 0.0),
                weight_net_kg=float(it.get("weight_net") or 0.0),
                weight_gross_kg=float(it.get("weight_gross") or 0.0),
                packages_count=float(it.get("packages") or it.get("places") or 0.0),
                attributes=_json_safe({k: v for k, v in it.items() if k not in ("description",)}),
                suggested_hs_code=suggested_hs,
                hs_confidence=hs_conf,
            )
            db.add(pl)

        db.commit()
        logger.info(f"Ingestion сохранён: document_id={doc.id}, lines={len(items)}")
        return doc.id


def list_ingested_documents(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with SessionLocal() as db:
        q = (
            db.query(IngestedDocument)
            .order_by(IngestedDocument.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = q.all()
        ids = [r.id for r in rows]
        counts: dict[str, int] = {}
        if ids:
            for did, cnt in (
                db.query(ParsedInvoiceLine.document_id, func.count(ParsedInvoiceLine.id))
                .filter(ParsedInvoiceLine.document_id.in_(ids))
                .group_by(ParsedInvoiceLine.document_id)
                .all()
            ):
                counts[str(did)] = int(cnt)
        return [
            {
                "id": r.id,
                "original_filename": r.original_filename,
                "status": r.status,
                "detected_lang": r.detected_lang,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "lines_count": counts.get(r.id, 0),
            }
            for r in rows
        ]


def get_ingested_document(document_id: str, include_lines: bool = True) -> Optional[dict[str, Any]]:
    with SessionLocal() as db:
        doc = db.query(IngestedDocument).filter(IngestedDocument.id == document_id).first()
        if not doc:
            return None
        out: dict[str, Any] = {
            "id": doc.id,
            "original_filename": doc.original_filename,
            "mime_type": doc.mime_type,
            "file_sha256": doc.file_sha256,
            "detected_lang": doc.detected_lang,
            "status": doc.status,
            "error_message": doc.error_message,
            "structured_payload": doc.structured_payload,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            "raw_text_preview": (doc.raw_text or "")[:2000],
        }
        if include_lines:
            lines = (
                db.query(ParsedInvoiceLine)
                .filter(ParsedInvoiceLine.document_id == document_id)
                .order_by(ParsedInvoiceLine.line_no)
                .all()
            )
            out["lines"] = [
                {
                    "line_no": ln.line_no,
                    "description_original": ln.description_original,
                    "description_ru": ln.description_ru,
                    "quantity": ln.quantity,
                    "unit": ln.unit,
                    "unit_price": ln.unit_price,
                    "line_total": ln.line_total,
                    "weight_net_kg": ln.weight_net_kg,
                    "weight_gross_kg": ln.weight_gross_kg,
                    "packages_count": ln.packages_count,
                    "suggested_hs_code": ln.suggested_hs_code,
                    "hs_confidence": ln.hs_confidence,
                    "attributes": ln.attributes,
                }
                for ln in lines
            ]
        return out
