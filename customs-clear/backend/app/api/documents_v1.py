"""API v1: разбор инвойсов ИИ для калькулятора."""

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, Depends
from fastapi.responses import JSONResponse
from loguru import logger

from ..services.audit_log import append_audit, request_audit_meta
from ..services.document_invoice_analyze import analyze_invoice_file
from ..security import require_authenticated_user

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


@router.post("/analyze")
async def documents_analyze(
    request: Request,
    file: UploadFile = File(
        ...,
        description="Инвойс/спецификация: .pdf, .png, .jpg, .jpeg, .xlsx, .xls, .csv",
    ),
) -> JSONResponse:
    """Извлечение строк товаров (ТН ВЭД, цена, вес) через Gemini 2.x (ключ только из env сервера)."""
    fname = (file.filename or "upload").strip()
    try:
        data = await file.read()
    except Exception as e:
        logger.exception("documents analyze read")
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать файл: {e}") from e

    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")

    out = await analyze_invoice_file(
        data=data,
        filename=fname,
        content_type=file.content_type,
    )

    append_audit(
        {
            "action": "documents.v1.analyze",
            "filename": fname[:256],
            "result_status": out.get("status"),
            "items_count": out.get("items_count", len(out.get("items") or [])),
            **request_audit_meta(request),
        }
    )

    if out.get("error_code") == "llm_not_configured":
        return JSONResponse(out, status_code=503)

    if out.get("status") != "OK":
        return JSONResponse(out, status_code=200)

    return JSONResponse(out)
