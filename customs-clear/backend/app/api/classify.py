from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from loguru import logger

from ..security import require_authenticated_user

from ..services.audit_log import request_audit_meta
from ..services.claude_service import classify_hs_code
from ..services.safe_http_errors import AI_SERVICE_UNAVAILABLE, contains_sensitive_error_text
from ..services import custom_classifier_service as ccs


router = APIRouter(dependencies=[Depends(require_authenticated_user)])


class ClassifyRequest(BaseModel):
    """Поле `api_key` из старых клиентов игнорируется (extra=ignore)."""

    model_config = ConfigDict(extra="ignore")

    description: str
    use_journal_hints: bool = True
    client_id: str | None = None
    use_custom_classifier: bool = True
    fallback_to_llm: bool = True


def _llm_result_usable(res: dict) -> bool:
    if not res or res.get("status") == "ERROR":
        return False
    r = res.get("results")
    return bool(isinstance(r, list) and len(r) > 0)


@router.post("")
async def classify(req: ClassifyRequest, request: Request) -> JSONResponse:
    """Классификация ТН ВЭД: опционально внешний HTTP-классификатор, затем Gemini/Claude."""
    if not req.description.strip():
        raise HTTPException(status_code=400, detail="Описание товара не должно быть пустым")
    try:
        logger.info("Запрос классификации ТН ВЭД")
        meta = request_audit_meta(request)
        prefer_cid = (req.client_id or "").strip() or (meta.get("client_id") or "").strip() or None

        if ccs.is_custom_only_mode() and req.use_custom_classifier:
            custom = await ccs.call_custom_classifier(req.description)
            if custom and custom.get("results"):
                custom.setdefault("status", "OK")
                return JSONResponse(custom)
            return JSONResponse(
                {
                    "status": "OK",
                    "query": req.description.strip(),
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
            custom = await ccs.call_custom_classifier(req.description)
            if custom and custom.get("results"):
                custom.setdefault("status", "OK")
                return JSONResponse(custom)
            if not req.fallback_to_llm:
                return JSONResponse(
                    {
                        "status": "OK",
                        "query": req.description.strip(),
                        "results": [],
                        "classifier_source": "custom_unavailable",
                        "note": "ONNX/HTTP классификатор не дал результат; fallback_to_llm=false.",
                    }
                )

        result = await classify_hs_code(
            req.description,
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
            custom = await ccs.call_custom_classifier(req.description)
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
    image_base64: str
    hint: str = ""


class ClassifyCharacteristicsRequest(BaseModel):
    material: str = ""
    purpose: str = ""
    principle: str = ""
    function: str = ""
    description: str = ""


@router.post("/image")
async def classify_image(req: ClassifyImageRequest) -> JSONResponse:
    from ..services.classify_enhancements import classify_by_image_base64

    result = await classify_by_image_base64(req.image_base64, hint=req.hint)
    return JSONResponse(result)


@router.post("/characteristics")
async def classify_characteristics(req: ClassifyCharacteristicsRequest) -> JSONResponse:
    from ..services.classify_enhancements import classify_by_characteristics

    result = await classify_by_characteristics(req.model_dump())
    return JSONResponse(result)


@router.get("/history")
async def classify_history(limit: int = 20) -> JSONResponse:
    from ..services.classify_enhancements import list_classification_history

    return JSONResponse({"items": list_classification_history(limit=min(limit, 20))})
