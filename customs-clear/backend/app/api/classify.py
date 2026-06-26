from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from loguru import logger

from ..security import require_authenticated_user

from ..services.audit_log import request_audit_meta
from ..services.claude_service import classify_hs_code
from ..services.safe_http_errors import AI_SERVICE_UNAVAILABLE, contains_sensitive_error_text
from ..services import custom_classifier_service as ccs
from ..services.smart_classifier import get_smart_classifier


router = APIRouter(dependencies=[Depends(require_authenticated_user)])


class ClassifyRequest(BaseModel):
    """Поле `api_key` из старых клиентов игнорируется (extra=ignore)."""

    model_config = ConfigDict(extra="ignore")

    description: str = ""
    use_journal_hints: bool = True
    client_id: str | None = None
    use_custom_classifier: bool = True
    fallback_to_llm: bool = True
    use_smart_classifier: bool = False
    image_base64: str | None = None
    image_url: str | None = None
    article: str | None = None
    manufacturer: str | None = None


class ClassifyBatchItem(BaseModel):
    description: str = ""
    image_base64: str | None = None
    image_url: str | None = None
    article: str | None = None
    manufacturer: str | None = None


class ClassifyBatchRequest(BaseModel):
    items: list[ClassifyBatchItem] = Field(..., min_length=1, max_length=50)


def _llm_result_usable(res: dict) -> bool:
    if not res or res.get("status") == "ERROR":
        return False
    r = res.get("results")
    return bool(isinstance(r, list) and len(r) > 0)


def _uses_smart_pipeline(req: ClassifyRequest) -> bool:
    if req.use_smart_classifier:
        return True
    return bool(req.image_base64 or req.image_url or req.article or req.manufacturer)


@router.post("")
async def classify(req: ClassifyRequest, request: Request) -> JSONResponse:
    """Классификация ТН ВЭД: SmartClassifier (фото/перевод/web) или LLM/ONNX."""
    desc = req.description.strip()
    if not desc and not (req.image_base64 or req.image_url or req.article):
        raise HTTPException(status_code=400, detail="Укажите description, фото или артикул")

    if _uses_smart_pipeline(req):
        try:
            result = await get_smart_classifier().classify(
                description=desc or None,
                image_base64=req.image_base64,
                image_url=req.image_url,
                article=req.article,
                manufacturer=req.manufacturer,
            )
            payload = result.to_api_dict()
            if result.status == "ERROR" and payload.get("error_code") == "llm_not_configured":
                return JSONResponse(status_code=503, content=payload)
            if result.status == "ERROR":
                return JSONResponse(status_code=503, content=payload)
            payload.setdefault("query", desc or req.article or "")
            return JSONResponse(payload)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("SmartClassifier error")
            if contains_sensitive_error_text(str(exc)):
                raise HTTPException(status_code=503, detail=AI_SERVICE_UNAVAILABLE) from exc
            raise HTTPException(status_code=500, detail=AI_SERVICE_UNAVAILABLE) from exc

    if not desc:
        raise HTTPException(status_code=400, detail="Описание товара не должно быть пустым")
    try:
        logger.info("Запрос классификации ТН ВЭД")
        meta = request_audit_meta(request)
        prefer_cid = (req.client_id or "").strip() or (meta.get("client_id") or "").strip() or None

        if ccs.is_custom_only_mode() and req.use_custom_classifier:
            custom = await ccs.call_custom_classifier(desc)
            if custom and custom.get("results"):
                custom.setdefault("status", "OK")
                return JSONResponse(custom)
            return JSONResponse(
                {
                    "status": "OK",
                    "query": desc,
                    "results": [],
                    "classifier_source": "custom_unavailable",
                    "note": "Режим CUSTOM_CLASSIFIER_MODE=custom_only: ONNX/HTTP не вернули применимых кодов.",
                }
            )

        if (
            req.use_custom_classifier
            and ccs.should_try_custom_before_llm()
            and not ccs.is_custom_only_mode()
        ):
            custom = await ccs.call_custom_classifier(desc)
            if custom and custom.get("results"):
                custom.setdefault("status", "OK")
                return JSONResponse(custom)
            if not req.fallback_to_llm:
                return JSONResponse(
                    {
                        "status": "OK",
                        "query": desc,
                        "results": [],
                        "classifier_source": "custom_unavailable",
                        "note": "ONNX/HTTP классификатор не дал результат; fallback_to_llm=false.",
                    }
                )

        result = await classify_hs_code(
            desc,
            use_journal_hints=req.use_journal_hints,
            prefer_client_id=prefer_cid,
        )
        if result.get("error_code") == "llm_not_configured":
            result.setdefault("classifier_source", "llm")
            return JSONResponse(status_code=503, content=result)
        result.setdefault("status", "OK")
        result.setdefault("classifier_source", "llm")

        if (
            req.use_custom_classifier
            and ccs.should_try_custom_after_llm()
            and not _llm_result_usable(result)
        ):
            custom = await ccs.call_custom_classifier(desc)
            if custom and custom.get("results"):
                custom.setdefault("status", "OK")
                if custom.get("classifier_source") != "onnx_local":
                    custom["classifier_source"] = "custom_http"
                custom["note"] = (custom.get("note") or "") + " (после неудачного/пустого ответа LLM)"
                return JSONResponse(custom)

        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Ошибка классификации ТН ВЭД")
        if contains_sensitive_error_text(str(exc)):
            raise HTTPException(status_code=503, detail=AI_SERVICE_UNAVAILABLE) from exc
        raise HTTPException(status_code=500, detail=AI_SERVICE_UNAVAILABLE) from exc


class ClassifyImageRequest(BaseModel):
    image_base64: str = ""
    image_url: str | None = None
    description: str = ""
    hint: str = ""
    article: str | None = None
    manufacturer: str | None = None


class ClassifyCharacteristicsRequest(BaseModel):
    material: str = ""
    purpose: str = ""
    principle: str = ""
    function: str = ""
    description: str = ""


@router.post("/image")
async def classify_image(req: ClassifyImageRequest) -> JSONResponse:
    desc = (req.description or req.hint or "").strip()
    if not req.image_base64 and not req.image_url:
        raise HTTPException(status_code=400, detail="Укажите image_base64 или image_url")
    result = await get_smart_classifier().classify(
        description=desc or None,
        image_base64=req.image_base64 or None,
        image_url=req.image_url,
        article=req.article,
        manufacturer=req.manufacturer,
    )
    payload = result.to_api_dict()
    if result.status == "ERROR":
        return JSONResponse(status_code=503 if payload.get("error_code") else 500, content=payload)
    return JSONResponse(payload)


@router.post("/batch")
async def classify_batch(req: ClassifyBatchRequest) -> JSONResponse:
    classifier = get_smart_classifier()
    items_out: list[dict] = []
    for idx, item in enumerate(req.items):
        desc = item.description.strip()
        if not desc and not (item.image_base64 or item.image_url or item.article):
            items_out.append({"index": idx, "status": "ERROR", "error": "Пустая позиция", "results": []})
            continue
        result = await classifier.classify(
            description=desc or None,
            image_base64=item.image_base64,
            image_url=item.image_url,
            article=item.article,
            manufacturer=item.manufacturer,
        )
        row = result.to_api_dict()
        row["index"] = idx
        items_out.append(row)
    return JSONResponse({"status": "OK", "items": items_out, "count": len(items_out)})


@router.post("/characteristics")
async def classify_characteristics(req: ClassifyCharacteristicsRequest) -> JSONResponse:
    from ..services.classify_enhancements import classify_by_characteristics

    result = await classify_by_characteristics(req.model_dump())
    return JSONResponse(result)


@router.get("/history")
async def classify_history(limit: int = 20) -> JSONResponse:
    from ..services.classify_enhancements import list_classification_history

    return JSONResponse({"items": list_classification_history(limit=min(limit, 20))})
