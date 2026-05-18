"""Слой ведомственных документов для NTM-пайплайна."""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from sqlalchemy import or_

from ..db import SessionLocal
from ..models.regulatory import RegulatoryDocHsMapping, RegulatoryDocument
from .hs_matching import get_hs_prefixes, normalize_hs_code, specificity


def _regulatory_mapping_precedence(
    new_m: RegulatoryDocHsMapping,
    new_d: RegulatoryDocument,
    old_m: RegulatoryDocHsMapping,
    old_d: RegulatoryDocument,
) -> bool:
    """True, если пара (new_m, new_d) предпочтительнее (old_m, old_d) для того же doc_id."""
    sn = specificity(new_m.hs_prefix or "")
    so = specificity(old_m.hs_prefix or "")
    if sn != so:
        return sn > so
    na = bool(new_m.approved)
    oa = bool(old_m.approved)
    if na != oa:
        return na and not oa
    nc = float(new_m.confidence or 0.0)
    oc = float(old_m.confidence or 0.0)
    if nc != oc:
        return nc > oc
    nd = new_d.doc_date
    od = old_d.doc_date
    if nd != od:
        if nd is None:
            return False
        if od is None:
            return True
        return nd > od
    return False


def _doc_date_ordinal_for_sort(iso: str | None) -> int:
    if not iso:
        return 0
    try:
        return date.fromisoformat(iso[:10]).toordinal()
    except ValueError:
        return 0


def _mapping_doc_to_dict(mapping: RegulatoryDocHsMapping, doc: RegulatoryDocument) -> dict[str, Any]:
    return {
        "doc_id": doc.id,
        "agency": doc.agency,
        "doc_type": doc.doc_type,
        "doc_number": doc.doc_number,
        "doc_date": doc.doc_date.isoformat() if doc.doc_date else None,
        "title": doc.title,
        "summary": doc.summary,
        "source_url": doc.source_url,
        "matched_prefix": mapping.hs_prefix,
        "relevance": mapping.relevance,
        "confidence": mapping.confidence,
        "scope": mapping.scope,
        "note": mapping.note,
        "approved": mapping.approved,
    }


def merge_regulatory_document_mapping_rows(
    pairs: Iterable[tuple[RegulatoryDocHsMapping, RegulatoryDocument]],
    *,
    max_results: int,
) -> list[dict[str, Any]]:
    """
    Объединяет строки (mapping, document) со всех уровней HS: один doc_id — одна запись,
    выбирается mapping с наиболее специфичным ``hs_prefix``; затем сортировка и обрезка.
    """
    best: dict[Any, tuple[RegulatoryDocHsMapping, RegulatoryDocument]] = {}
    for mapping, doc in pairs:
        prev = best.get(doc.id)
        if prev is None or _regulatory_mapping_precedence(mapping, doc, prev[0], prev[1]):
            best[doc.id] = (mapping, doc)
    out = [_mapping_doc_to_dict(m, d) for m, d in best.values()]
    out.sort(
        key=lambda item: (
            -specificity(str(item.get("matched_prefix") or "")),
            -(1 if item.get("approved") else 0),
            -float(item.get("confidence") or 0.0),
            -_doc_date_ordinal_for_sort(item.get("doc_date")),
        ),
    )
    return out[:max_results]


def get_regulatory_documents_for_hs(
    hs_code: str,
    *,
    only_approved: bool = False,
    min_confidence: float = 0.5,
    max_results: int = 10,
) -> list[dict]:
    code = normalize_hs_code(hs_code)
    if not code:
        return []

    collected: list[tuple[RegulatoryDocHsMapping, RegulatoryDocument]] = []

    with SessionLocal() as db:
        for prefix in get_hs_prefixes(code, levels=(10, 8, 6, 4, 2)):
            query = (
                db.query(RegulatoryDocHsMapping, RegulatoryDocument)
                .join(RegulatoryDocument, RegulatoryDocHsMapping.doc_id == RegulatoryDocument.id)
                .filter(RegulatoryDocHsMapping.hs_prefix == prefix)
                .filter(RegulatoryDocument.status == "active")
                .filter(or_(RegulatoryDocument.quality.is_(None), RegulatoryDocument.quality != "noise"))
                .filter(RegulatoryDocHsMapping.confidence >= min_confidence)
            )

            if only_approved:
                query = query.filter(RegulatoryDocHsMapping.approved.is_(True))

            rows = (
                query.order_by(
                    RegulatoryDocHsMapping.confidence.desc(),
                    RegulatoryDocument.doc_date.desc(),
                )
                .limit(max_results)
                .all()
            )
            collected.extend(rows)

    return merge_regulatory_document_mapping_rows(collected, max_results=max_results)
