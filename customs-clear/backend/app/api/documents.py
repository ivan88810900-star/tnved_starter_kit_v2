import asyncio
import json

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body, Depends
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTasks
from typing import List, Dict, Any, Optional
from uuid import uuid4
from loguru import logger
from pydantic import BaseModel, Field

from ..deps_exports import verify_ved_export_allowed
from ..security import require_authenticated_user
from ..schemas.invoice import VedIntelligentAnalyzeResponse
from ..services.extractor import extract_invoice_and_packing_from_files
from ..services.validator import validate_invoice_only, validate_invoice_vs_packing
from ..services.permit_extractor import extract_permits_from_text
from ..services.permits_service import check_permits
from ..services.declaration_draft_service import build_declaration_draft
from ..services.document_intel import match_invoice_lines_to_hs, validate_counterparty
from ..services.calculation_history_service import list_history_for_ingested_document
from ..services.ingestion_service import (
    get_ingested_document,
    list_ingested_documents,
    persist_extracted_bundle,
)
from ..services.ved_intel_analyze_core import run_ved_intel_analyze_core, ved_intel_semaphore
from ..services.ved_intel_jobs import (
    create_ved_intel_job,
    get_ved_intel_job,
    list_ved_intel_jobs,
)
from ..services.export_service import generate_final_customs_excel_from_ved_result
from ..services.ved_report_pdf import build_ved_report_pdf


router = APIRouter(dependencies=[Depends(require_authenticated_user)])

_DOCUMENT_STORE: Dict[str, Dict[str, Any]] = {}


def _has_second_file(upload: Optional[UploadFile]) -> bool:
    return upload is not None and bool((upload.filename or "").strip())


class InvoiceLineIn(BaseModel):
    index: int | None = None
    description: str = ""
    text: str = ""


class MatchLinesRequest(BaseModel):
    lines: List[InvoiceLineIn] = Field(..., min_length=1)
    limit_per_line: int = Field(6, ge=1, le=20)


class CounterpartyIn(BaseModel):
    inn: str | None = None
    name: str | None = None
    country: str | None = None


@router.post("/upload")
async def upload_documents(
    invoice: UploadFile = File(..., description="Файл инвойса"),
    packing_list: Optional[UploadFile] = File(
        None,
        description="Упаковочный лист (необязательно — для сверки с инвойсом)",
    ),
    persist: bool = Form(True, description="Сохранить извлечённые данные в БД (ingested_documents)"),
    user_ref: Optional[str] = Form(None, description="Не используется в upload; для единообразия формы"),
) -> JSONResponse:
    """Загрузка файлов с немедленной базовой проверкой и сохранением результата в истории."""
    try:
        has_packing = _has_second_file(packing_list)
        logger.info(
            f"Загрузка: invoice={invoice.filename}, packing={packing_list.filename if has_packing else '(нет)'}",
        )
        data = await extract_invoice_and_packing_from_files(
            invoice,
            packing_list if has_packing else None,
        )
        result = (
            validate_invoice_vs_packing(data["invoice"], data["packing"])
            if has_packing
            else validate_invoice_only(data["invoice"])
        )
        doc_id = str(uuid4())
        persisted = False
        if persist:
            try:
                snap = dict(result)
                snap["status"] = snap.get("status", "OK")
                doc_id = persist_extracted_bundle(
                    original_filename=invoice.filename or "invoice",
                    mime_type=(invoice.content_type or "application/octet-stream"),
                    invoice_data=data["invoice"],
                    packing_data=data.get("packing") if has_packing else None,
                    api_response_snapshot=snap,
                    declaration_draft=None,
                    status="ocr_done",
                )
                persisted = True
            except Exception as ex:
                logger.exception("persist upload")
                doc_id = str(uuid4())
                mem = dict(result)
                mem["document_id"] = doc_id
                mem["persisted_to_db"] = False
                mem["persist_error"] = str(ex)
                _DOCUMENT_STORE[doc_id] = mem
                return JSONResponse(
                    {
                        "status": "OK",
                        "document_id": doc_id,
                        "persisted_to_db": False,
                        "persist_error": str(ex),
                    }
                )
        mem = dict(result)
        mem["document_id"] = doc_id
        mem["persisted_to_db"] = persisted
        _DOCUMENT_STORE[doc_id] = mem
        return JSONResponse(
            {"status": "OK", "document_id": doc_id, "persisted_to_db": persisted},
        )
    except Exception as exc:
        logger.exception("Ошибка при загрузке документов")
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/check")
async def check_documents(
    invoice: UploadFile = File(..., description="Файл инвойса"),
    packing_list: Optional[UploadFile] = File(
        None,
        description="Упаковочный лист (необязательно)",
    ),
    extract_permits: bool = Form(True, description="Извлечь номера СС/ДС/СГР из текста PDF"),
    verify_fsa: bool = Form(True, description="Проверить извлечённые номера в реестре ФСА"),
    skip_registry_verify: bool = Form(
        False,
        description="Если true — не обращаться к ФСА/СГР (только извлечение номеров из текста)",
    ),
    hs_code: Optional[str] = Form(None, description="ТН ВЭД для сверки с реестром"),
    declaration_draft: bool = Form(
        True,
        description="Собрать черновик ДТ: ТН ВЭД, графа 31, веса, документы",
    ),
    use_ai_declaration: bool = Form(True, description="Вызывать ИИ для строк (при наличии ключей в .env сервера)"),
    client_id: Optional[str] = Form(None, description="Идентификатор клиента для журнала (опционально)"),
    persist: bool = Form(True, description="Сохранить документ и строки в БД (ingested_documents / parsed_invoice_lines)"),
) -> JSONResponse:
    """Запуск проверки документов и возврат подробного результата."""
    try:
        if skip_registry_verify:
            verify_fsa = False
        has_packing = _has_second_file(packing_list)
        logger.info(
            f"Проверка: invoice={invoice.filename}, packing={packing_list.filename if has_packing else '(нет)'}",
        )
        data = await extract_invoice_and_packing_from_files(
            invoice,
            packing_list if has_packing else None,
        )
        result = (
            validate_invoice_vs_packing(data["invoice"], data["packing"])
            if has_packing
            else validate_invoice_only(data["invoice"])
        )
        result_with_meta: Dict[str, Any] = dict(result)
        result_with_meta["status"] = result_with_meta.get("status", "OK")

        if extract_permits:
            text_parts = []
            for key in ("invoice", "packing"):
                block = data.get(key) or {}
                raw = block.get("raw_text") or ""
                if raw:
                    text_parts.append(raw)
            combined = "\n".join(text_parts)
            extracted = extract_permits_from_text(combined)
            result_with_meta["extracted_permits"] = extracted
            if verify_fsa and extracted:
                result_with_meta["permits_registry_check"] = await check_permits(
                    extracted, (hs_code or "").strip(), enrich=True
                )
            elif verify_fsa and not extracted:
                result_with_meta["permits_registry_check"] = []
                result_with_meta["permits_registry_note"] = "Номера СС/ДС/СГР в тексте не обнаружены"

        draft: Optional[Dict[str, Any]] = None
        if declaration_draft:
            prefer_cid = (client_id or "").strip() or None
            draft = await build_declaration_draft(
                data["invoice"],
                data["packing"] if has_packing else None,
                use_llm=use_ai_declaration,
                prefer_client_id=prefer_cid,
            )
            result_with_meta["declaration_draft"] = draft

        doc_id = str(uuid4())
        result_with_meta["persisted_to_db"] = False
        if persist:
            try:
                doc_id = persist_extracted_bundle(
                    original_filename=invoice.filename or "invoice",
                    mime_type=(invoice.content_type or "application/octet-stream"),
                    invoice_data=data["invoice"],
                    packing_data=data.get("packing") if has_packing else None,
                    api_response_snapshot=result_with_meta,
                    declaration_draft=draft if isinstance(draft, dict) else None,
                    status="llm_structured" if declaration_draft else "ocr_done",
                )
                result_with_meta["persisted_to_db"] = True
            except Exception as ex:
                logger.exception("persist check_documents")
                result_with_meta["persist_error"] = str(ex)

        result_with_meta["document_id"] = doc_id
        _DOCUMENT_STORE[doc_id] = result_with_meta

        return JSONResponse(result_with_meta)
    except Exception as exc:
        logger.exception("Ошибка при проверке документов")
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/ved-intelligent-analyze", response_model=VedIntelligentAnalyzeResponse)
async def ved_intelligent_analyze(
    document: UploadFile = File(
        ...,
        description="Инвойс или упаковочный лист (Excel/PDF/CSV; текст на китайском допускается)",
    ),
    companion: Optional[UploadFile] = File(
        None,
        description="Второй файл для сверки (упаковочный лист или инвойс)",
    ),
    country: str = Form("CN", description="Страна происхождения (ISO-2) для нетарифки и платежей"),
    freight_total_rub: float = Form(
        0.0,
        ge=0.0,
        description="Общий фрахт в руб. — распределяется по строкам пропорционально таможенной стоимости",
    ),
    fallback_customs_total_rub: float = Form(
        0.0,
        ge=0.0,
        description="Если в файле нет сумм по строкам: всего таможенная стоимость в ₽ — распределить по количеству или поровну",
    ),
    extract_permits: bool = Form(True),
    verify_fsa: bool = Form(True),
    skip_registry_verify: bool = Form(False),
    hs_code: Optional[str] = Form(None, description="Подсказка ТН ВЭД для сверки разрешений"),
    use_ai_declaration: bool = Form(True),
    client_id: Optional[str] = Form(None),
    persist: bool = Form(True),
    run_payment: bool = Form(True, description="Оценка пошлин/НДС по строкам (нужна стоимость в файле)"),
) -> JSONResponse:
    """Полный ВЭД-разбор: ТН ВЭД, графа 31, разрешения, нетарифка, платежи, ФСА, ИИ-сводка и риски."""
    async with ved_intel_semaphore():
        try:
            merged = await run_ved_intel_analyze_core(
                document=document,
                companion=companion,
                country=country,
                freight_total_rub=freight_total_rub,
                fallback_customs_total_rub=fallback_customs_total_rub,
                extract_permits=extract_permits,
                verify_fsa=verify_fsa,
                skip_registry_verify=skip_registry_verify,
                hs_code=hs_code,
                use_ai_declaration=use_ai_declaration,
                client_id=client_id,
                persist=persist,
                run_payment=run_payment,
                document_store=_DOCUMENT_STORE,
            )
            return JSONResponse(merged)
        except Exception as exc:
            logger.exception("ved_intelligent_analyze")
            raise HTTPException(status_code=400, detail=str(exc))


@router.post("/ved-intelligent-analyze/async")
async def ved_intelligent_analyze_async(
    background_tasks: BackgroundTasks,
    document: UploadFile = File(
        ...,
        description="Инвойс или упаковочный лист (Excel/PDF/CSV)",
    ),
    companion: Optional[UploadFile] = File(
        None,
        description="Второй файл для сверки",
    ),
    country: str = Form("CN"),
    freight_total_rub: float = Form(0.0, ge=0.0),
    fallback_customs_total_rub: float = Form(0.0, ge=0.0),
    extract_permits: bool = Form(True),
    verify_fsa: bool = Form(True),
    skip_registry_verify: bool = Form(False),
    hs_code: Optional[str] = Form(None),
    use_ai_declaration: bool = Form(True),
    client_id: Optional[str] = Form(None),
    persist: bool = Form(True),
    run_payment: bool = Form(True),
) -> JSONResponse:
    """Тот же разбор, что `ved-intelligent-analyze`, но в фоне. Результат: GET `/ved-intel-jobs/{job_id}`."""
    main_bytes = await document.read()
    comp_bytes: Optional[bytes] = None
    comp_fn: Optional[str] = None
    comp_ct: Optional[str] = None
    if _has_second_file(companion):
        comp_bytes = await companion.read()
        comp_fn = companion.filename
        comp_ct = companion.content_type
    job_id = await create_ved_intel_job(
        main_bytes=main_bytes,
        main_filename=document.filename or "document",
        main_content_type=document.content_type or "application/octet-stream",
        companion_bytes=comp_bytes,
        companion_filename=comp_fn,
        companion_content_type=comp_ct,
        country=country,
        freight_total_rub=freight_total_rub,
        fallback_customs_total_rub=fallback_customs_total_rub,
        extract_permits=extract_permits,
        verify_fsa=verify_fsa,
        skip_registry_verify=skip_registry_verify,
        hs_code=(hs_code or "").strip() or None,
        use_ai_declaration=use_ai_declaration,
        client_id=(client_id or "").strip() or None,
        persist=persist,
        run_payment=run_payment,
        document_store=_DOCUMENT_STORE,
        background_tasks=background_tasks,
    )
    return JSONResponse(
        {
            "status": "accepted",
            "job_id": job_id,
            "poll_url": f"/api/documents/ved-intel-jobs/{job_id}",
        }
    )


@router.get("/ved-intel-jobs/{job_id}")
async def ved_intel_job_status(job_id: str) -> JSONResponse:
    """Статус фонового ВЭД-разбора; при `done` в теле поле `result` — как у синхронного ответа."""
    row = await get_ved_intel_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    return JSONResponse(row)


@router.get("/{job_id}/export")
async def ved_intel_job_export_excel(
    job_id: str,
    _: None = Depends(verify_ved_export_allowed),
) -> Response:
    """
    Экспорт XLSX по результату фонового задания ved-intel.
    """
    row = await get_ved_intel_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    if row.get("status") != "done":
        raise HTTPException(status_code=409, detail="Задание еще не завершено")
    result = row.get("result")
    if not isinstance(result, dict):
        raise HTTPException(status_code=400, detail="В задании отсутствует result")
    try:
        xlsx = generate_final_customs_excel_from_ved_result(result)
    except Exception as exc:
        logger.exception("ved_intel_job_export_excel")
        raise HTTPException(status_code=400, detail=str(exc))
    filename = f"customs_report_{job_id[:8]}.xlsx"
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/ved-intel-jobs")
async def ved_intel_jobs_list(limit: int = 50) -> JSONResponse:
    """Краткий список заданий (без полного result)."""
    items = await list_ved_intel_jobs(limit=limit)
    return JSONResponse({"status": "OK", "items": items})


@router.get("/ved-intel-jobs/{job_id}/events")
async def ved_intel_job_events(job_id: str) -> StreamingResponse:
    """SSE: события статуса фонового ВЭД-разбора (JSON в каждом `data:`), до done/error. Интервал 2 с."""
    probe = await get_ved_intel_job(job_id)
    if not probe:
        raise HTTPException(status_code=404, detail="Задание не найдено")

    async def gen():
        for _ in range(900):
            row = await get_ved_intel_job(job_id)
            if not row:
                yield f"data: {json.dumps({'status': 'error', 'error': 'missing'}, ensure_ascii=False)}\n\n"
                return
            yield f"data: {json.dumps(row, ensure_ascii=False, default=str)}\n\n"
            if row.get("status") in ("done", "error"):
                return
            await asyncio.sleep(2.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/ved-report-pdf")
async def ved_report_pdf(
    body: Dict[str, Any] = Body(...),
    _: None = Depends(verify_ved_export_allowed),
) -> Response:
    """PDF по тем же полям, что JSON-экспорт «Скачать отчёт» на вкладке Документы (тело — JSON)."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Ожидается JSON-объект")
    try:
        pdf_bytes = build_ved_report_pdf(body)
    except Exception as exc:
        logger.exception("ved_report_pdf")
        raise HTTPException(status_code=400, detail=str(exc))
    did = body.get("document_id")
    fname = "ved_report.pdf"
    if isinstance(did, str) and len(did.strip()) >= 8:
        fname = f"ved_report_{did.strip()[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/match-lines")
async def documents_match_lines(req: MatchLinesRequest) -> JSONResponse:
    """Сопоставление строк описания из инвойса с кандидатами ТН ВЭД (эвристика, не ИИ)."""
    raw = [ln.model_dump() for ln in req.lines]
    matched = match_invoice_lines_to_hs(raw, limit_per_line=req.limit_per_line)
    return JSONResponse({"status": "OK", "items": matched})


@router.post("/validate-counterparty")
async def documents_validate_counterparty(body: CounterpartyIn) -> JSONResponse:
    """Проверка реквизитов контрагента (ИНН РФ — контрольная сумма)."""
    res = validate_counterparty(body.model_dump(exclude_none=True))
    return JSONResponse(res)


@router.get("/ingested")
async def ingested_list(limit: int = 50, offset: int = 0) -> JSONResponse:
    """Список документов, сохранённых в БД (ingested_documents)."""
    items = list_ingested_documents(limit=limit, offset=offset)
    return JSONResponse({"status": "OK", "items": items})


@router.get("/ingested/{ingested_id}")
async def ingested_detail(ingested_id: str, include_lines: bool = True) -> JSONResponse:
    """Детали сохранённого документа и распознанные строки."""
    row = get_ingested_document(ingested_id, include_lines=include_lines)
    if not row:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return JSONResponse({"status": "OK", **row})


@router.get("/ingested/{ingested_id}/calculations")
async def ingested_calculation_history(ingested_id: str, limit: int = 100) -> JSONResponse:
    """Записи customs_calculation_history с document_id = ingested_id."""
    items = list_history_for_ingested_document(ingested_id, limit=limit)
    if items is None:
        raise HTTPException(status_code=404, detail="Документ не найден в ingested_documents")
    return JSONResponse({"status": "OK", "document_id": ingested_id, "items": items})


@router.get("/history")
async def history(limit: int = 50) -> JSONResponse:
    """История последних проверок (ограниченная по количеству)."""
    items: List[Dict[str, Any]] = []
    for doc_id, payload in list(_DOCUMENT_STORE.items())[-limit:]:
        summary = payload.get("summary", {})
        items.append(
            {
                "id": doc_id,
                "status": payload.get("status", "OK"),
                "invoice_number": payload.get("invoice_number"),
                "errors": summary.get("errors", 0),
                "warnings": summary.get("warnings", 0),
            }
        )
    return JSONResponse({"status": "OK", "items": items})


@router.get("/{doc_id}/result")
async def get_result(doc_id: str) -> JSONResponse:
    """Получение ранее сохранённого результата проверки по идентификатору."""
    result = _DOCUMENT_STORE.get(doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Результат не найден")
    wrapped = dict(result)
    wrapped.setdefault("status", "OK")
    wrapped["document_id"] = doc_id
    return JSONResponse(wrapped)

