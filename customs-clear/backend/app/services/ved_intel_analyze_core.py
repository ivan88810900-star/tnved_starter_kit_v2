"""Общая логика полного ВЭД-разбора документа (синхронный HTTP и фоновые задания)."""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import UploadFile
from loguru import logger

from .extractor import extract_invoice_and_packing_from_files
from .ingestion_service import persist_extracted_bundle
from .validator import validate_invoice_only, validate_invoice_vs_packing
from .ved_intel_service import run_ved_intel_pipeline

_VED_INTEL_SEM: Optional[asyncio.Semaphore] = None


def ved_intel_semaphore() -> asyncio.Semaphore:
    """Ограничение параллельных полных ВЭД-разборов. См. VED_INTEL_MAX_CONCURRENT."""
    global _VED_INTEL_SEM
    if _VED_INTEL_SEM is None:
        raw = (os.getenv("VED_INTEL_MAX_CONCURRENT") or "4").strip()
        try:
            n = int(raw)
        except ValueError:
            n = 4
        n = max(1, min(n, 64))
        _VED_INTEL_SEM = asyncio.Semaphore(n)
    return _VED_INTEL_SEM


def has_second_upload(upload: Optional[UploadFile]) -> bool:
    return upload is not None and bool((upload.filename or "").strip())


def slim_ved_intel_for_persist(intel: Dict[str, Any]) -> Dict[str, Any]:
    """Укороченный снимок для БД (без тяжёлых bundle)."""
    out = {k: v for k, v in intel.items() if k != "copilot_batch"}
    cb = intel.get("copilot_batch")
    if isinstance(cb, dict) and isinstance(cb.get("bundles"), list):
        light = []
        for b in cb["bundles"]:
            if not isinstance(b, dict):
                continue
            pay = b.get("payment") or {}
            bd = pay.get("breakdown") if isinstance(pay, dict) else {}
            nt = b.get("non_tariff") or {}
            light.append(
                {
                    "effective_hs_code": b.get("effective_hs_code"),
                    "non_tariff_status": nt.get("status") if isinstance(nt, dict) else None,
                    "total_payable": bd.get("total_payable") if isinstance(bd, dict) else None,
                }
            )
        out["copilot_batch_light"] = light
    return out


async def run_ved_intel_analyze_core(
    *,
    document: UploadFile,
    companion: Optional[UploadFile],
    country: str,
    freight_total_rub: float,
    fallback_customs_total_rub: float,
    extract_permits: bool,
    verify_fsa: bool,
    skip_registry_verify: bool,
    hs_code: Optional[str],
    use_ai_declaration: bool,
    client_id: Optional[str],
    persist: bool,
    run_payment: bool,
    document_store: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Возвращает объединённый результат (как тело JSON ответа). Бросает исключение при ошибке."""
    if skip_registry_verify:
        verify_fsa = False
    has_packing = has_second_upload(companion)
    logger.info(
        f"ВЭД-аналитик: doc={document.filename}, companion={companion.filename if has_packing else '(нет)'}",
    )
    data = await extract_invoice_and_packing_from_files(
        document,
        companion if has_packing else None,
    )
    result = (
        validate_invoice_vs_packing(data["invoice"], data["packing"])
        if has_packing
        else validate_invoice_only(data["invoice"])
    )
    base: Dict[str, Any] = dict(result)
    base["status"] = base.get("status", "OK")
    base["comparison_mode"] = "invoice_and_packing" if has_packing else "invoice_only"

    prefer_cid = (client_id or "").strip() or None
    intel = await run_ved_intel_pipeline(
        invoice_data=data["invoice"],
        packing_data=data.get("packing"),
        has_packing=has_packing,
        validation_snapshot={
            "status": base.get("status"),
            "summary": base.get("summary"),
            "verdict": base.get("verdict"),
        },
        country=(country or "CN").strip().upper()[:4] or "CN",
        hs_code_hint=(hs_code or "").strip(),
        use_ai_declaration=use_ai_declaration,
        extract_permits=extract_permits,
        verify_fsa=verify_fsa,
        skip_registry=skip_registry_verify,
        run_payment=run_payment,
        freight_total_rub=freight_total_rub,
        fallback_customs_total_rub=fallback_customs_total_rub,
        prefer_client_id=prefer_cid,
    )

    merged: Dict[str, Any] = {**base, **intel}
    draft = intel.get("declaration_draft")
    if isinstance(draft, dict):
        merged["declaration_draft"] = draft
    if extract_permits:
        merged["extracted_permits"] = intel.get("extracted_permits", [])
        merged["permits_registry_check"] = intel.get("permits_registry_check", [])
        if intel.get("permits_registry_note"):
            merged["permits_registry_note"] = intel["permits_registry_note"]

    doc_id = str(uuid4())
    merged["persisted_to_db"] = False
    if persist:
        try:
            snap = dict(merged)
            snap["ved_intel_persist_slim"] = slim_ved_intel_for_persist(intel)
            doc_id = persist_extracted_bundle(
                original_filename=document.filename or "document",
                mime_type=(document.content_type or "application/octet-stream"),
                invoice_data=data["invoice"],
                packing_data=data.get("packing") if has_packing else None,
                api_response_snapshot=snap,
                declaration_draft=draft if isinstance(draft, dict) else None,
                status="llm_structured" if use_ai_declaration else "ocr_done",
            )
            merged["persisted_to_db"] = True
        except Exception as ex:
            logger.exception("persist ved_intel")
            merged["persist_error"] = str(ex)

    merged["document_id"] = doc_id
    document_store[doc_id] = merged
    return merged
