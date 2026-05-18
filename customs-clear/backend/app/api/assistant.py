"""API ИИ-ассистента декларанта."""
import csv
import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from loguru import logger

from ..services.non_tariff_service import check_position_non_tariff
from ..services.claude_service import analyze_non_tariff, analyze_copilot_bundle
from ..services.assistant_orchestrator import (
    run_copilot_pipeline,
    run_copilot_batch,
    bundle_for_llm,
)
from ..services.rag_service import rag_context_for_copilot
from ..services.audit_log import append_audit, request_audit_meta
from ..services.calculation_history_service import save_calculation_record
from ..security import require_admin_token, require_authenticated_user
from ..services.assistant_chat import run_assistant_chat
from ..services.decision_history import (
    append_decision,
    compute_journal_stats,
    export_all_decisions,
    find_similar_decisions,
    read_recent_decisions,
    similar_decisions_context,
    suggest_hs_codes,
)

router = APIRouter(dependencies=[Depends(require_authenticated_user)])
chat_router = APIRouter(dependencies=[Depends(require_authenticated_user)])


def _prefer_client_id(request: Request) -> str | None:
    return (request_audit_meta(request).get("client_id") or "").strip() or None


class PermitIn(BaseModel):
    type: str
    number: str


class AssistantItemIn(BaseModel):
    hs_code: str
    description: str
    country: str | None = None
    permits: List[PermitIn] = []


class AssistantRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: List[AssistantItemIn]


class CopilotRequest(BaseModel):
    """Единый конвейер: классификация (опц.) → платежи → нетарифка → реестр (опц.) → ИИ."""

    model_config = ConfigDict(extra="ignore")

    description: str = ""
    hs_code: str = ""
    country: str | None = None
    customs_value: float | None = None
    freight: float = 0.0
    insurance: float | None = None
    quantity: float | None = None
    permits: List[PermitIn] = []
    run_ai_classification: bool = False
    run_payment: bool = True
    run_registry_verify: bool = False
    save_calculation_history: bool = False
    document_id: str | None = None
    user_ref: str = ""


class CopilotLineIn(BaseModel):
    """Одна позиция в мульти-декларации."""

    description: str = ""
    hs_code: str = ""
    country: str | None = None
    customs_value: float | None = None
    freight: float = 0.0
    insurance: float | None = None
    quantity: float | None = None
    permits: List[PermitIn] = []


class CopilotBatchRequest(BaseModel):
    """Несколько товарных позиций: общий ИИ-обзор."""

    model_config = ConfigDict(extra="ignore")

    items: List[CopilotLineIn] = Field(..., min_length=1, max_length=50)
    run_ai_classification: bool = False
    run_payment: bool = True
    run_registry_verify: bool = False
    save_calculation_history: bool = False
    document_id: str | None = None
    user_ref: str = ""


class AssistantChatHistoryItem(BaseModel):
    """Одно сообщение в истории; текст — в `content` или `text` (оба принимаются)."""

    model_config = ConfigDict(populate_by_name=True)

    role: str = Field(..., description="user | assistant")
    text: str = Field(
        ...,
        min_length=1,
        max_length=12000,
        validation_alias=AliasChoices("content", "text"),
        serialization_alias="content",
    )


class AssistantNonTariffMeasureContext(BaseModel):
    measure_type: str = ""
    regulatory_act: str = ""
    document_required: str = ""
    description: str = ""


class AssistantCurrentContext(BaseModel):
    """Контекст расчёта в калькуляторе (опционально). Доп. поля разрешены для снимка breakdown."""

    model_config = ConfigDict(extra="allow")

    hs_code: Optional[str] = None
    product_name: Optional[str] = None
    origin_country: Optional[str] = None
    total_payable: Optional[float] = None
    non_tariff_measures: List[AssistantNonTariffMeasureContext] = Field(default_factory=list)


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str = Field(..., min_length=1, max_length=8000)
    history: List[AssistantChatHistoryItem] = Field(default_factory=list, max_length=40)
    # Алиас для клиентов: объект context (код ТН ВЭД, пошлины, нетарифка)
    context: Optional[AssistantCurrentContext] = None
    current_context: Optional[AssistantCurrentContext] = None

    @model_validator(mode="after")
    def _single_context_block(self) -> "AssistantChatRequest":
        if self.context is not None and self.current_context is not None:
            raise ValueError("Укажите только context или current_context, не оба поля")
        return self

    def resolved_context(self) -> Optional[AssistantCurrentContext]:
        return self.context if self.context is not None else self.current_context


class DecisionLogIn(BaseModel):
    """Фиксация выбора ТН ВЭД экспертом (для истории и будущего обучения)."""

    description: str = ""
    suggested_hs: str = ""
    confirmed_hs: str = ""
    source: str = "ui_assistant"
    notes: str = ""


@router.post("/decisions/log")
async def assistant_decision_log(req: DecisionLogIn, request: Request) -> JSONResponse:
    if not (req.confirmed_hs or "").strip():
        raise HTTPException(status_code=400, detail="Укажите подтверждённый код ТН ВЭД (confirmed_hs)")
    append_decision(
        {
            "description": (req.description or "").strip()[:2000],
            "suggested_hs": (req.suggested_hs or "").strip()[:32],
            "confirmed_hs": (req.confirmed_hs or "").strip()[:32],
            "source": (req.source or "ui").strip()[:64],
            "notes": (req.notes or "").strip()[:2000],
            **request_audit_meta(request),
        }
    )
    append_audit(
        {
            "action": "assistant.decision_log",
            "confirmed_hs": (req.confirmed_hs or "").strip()[:32],
            **request_audit_meta(request),
        }
    )
    return JSONResponse({"status": "OK"})


@router.get("/decisions/recent")
async def assistant_decisions_recent(limit: int = 30) -> JSONResponse:
    lim = max(1, min(limit, 200))
    return JSONResponse({"status": "OK", "items": read_recent_decisions(lim)})


@router.get("/decisions/stats")
async def assistant_decisions_stats() -> JSONResponse:
    """Сводка по журналу подтверждений (количество, топ кодов ТН ВЭД, источники)."""
    return JSONResponse({"status": "OK", **compute_journal_stats()})


@router.get("/decisions/similar")
async def assistant_decisions_similar(
    request: Request,
    q: str = "",
    limit: int = 8,
) -> JSONResponse:
    """Подсказки из журнала по похожести описания (для UI до запуска конвейера)."""
    lim = max(1, min(limit, 20))
    pc = _prefer_client_id(request)
    return JSONResponse(
        {
            "status": "OK",
            "items": find_similar_decisions(q.strip(), limit=lim, prefer_client_id=pc),
            "prefer_client_id": pc,
        }
    )


@router.get("/decisions/suggest-hs")
async def assistant_decisions_suggest_hs(
    request: Request,
    q: str = "",
    limit: int = 8,
) -> JSONResponse:
    """Агрегированные коды ТН ВЭД из журнала (вес = сумма похожестей описаний)."""
    lim = max(1, min(limit, 30))
    pc = _prefer_client_id(request)
    return JSONResponse(
        {
            "status": "OK",
            "items": suggest_hs_codes(q.strip(), limit=lim, prefer_client_id=pc),
            "prefer_client_id": pc,
        }
    )


@router.get("/decisions/hints")
async def assistant_decisions_hints(
    request: Request,
    q: str = "",
    similar_limit: int = 6,
    hs_limit: int = 8,
) -> JSONResponse:
    """Один запрос: похожие строки журнала + ранжирование кодов ТН ВЭД."""
    sl = max(1, min(similar_limit, 20))
    hl = max(1, min(hs_limit, 30))
    qs = q.strip()
    pc = _prefer_client_id(request)
    return JSONResponse(
        {
            "status": "OK",
            "similar": find_similar_decisions(qs, limit=sl, prefer_client_id=pc),
            "hs_suggestions": suggest_hs_codes(qs, limit=hl, prefer_client_id=pc),
            "prefer_client_id": pc,
        }
    )


@router.get("/decisions/export", response_model=None)
async def assistant_decisions_export(
    format: str = "json",
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
):
    """Выгрузка журнала для анализа / обучение. Требует X-Admin-Token."""
    require_admin_token(x_admin_token)
    rows = export_all_decisions()
    fmt = (format or "json").lower().strip()
    if fmt == "csv":
        buf = io.StringIO()
        fields = [
            "ts",
            "description",
            "suggested_hs",
            "confirmed_hs",
            "source",
            "notes",
            "client_id",
            "audit_subject",
        ]
        w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
        return PlainTextResponse(
            buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="user_decisions.csv"',
            },
        )
    return JSONResponse(
        {
            "status": "OK",
            "count": len(rows),
            "items": rows,
        }
    )


@router.post("/copilot")
async def assistant_copilot(req: CopilotRequest, request: Request) -> JSONResponse:
    if not (req.description or "").strip() and not (req.hs_code or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Укажите описание товара и/или код ТН ВЭД",
        )
    bundle = await run_copilot_pipeline(
        description=(req.description or "").strip(),
        hs_code=(req.hs_code or "").strip(),
        country=req.country,
        customs_value=req.customs_value,
        freight=req.freight,
        insurance=req.insurance,
        quantity=req.quantity,
        permits=[{"type": p.type, "number": p.number} for p in req.permits],
        run_ai_classification=req.run_ai_classification,
        run_payment=req.run_payment,
        run_registry_verify=req.run_registry_verify,
    )
    slim = bundle_for_llm(bundle)
    rag = await rag_context_for_copilot((req.description or "").strip())
    sim = similar_decisions_context((req.description or "").strip(), prefer_client_id=_prefer_client_id(request))
    slim = {**slim, **rag, **sim}
    ai = await analyze_copilot_bundle(slim)
    append_audit(
        {
            "action": "assistant.copilot",
            "effective_hs": bundle.get("effective_hs_code"),
            "registry_on": req.run_registry_verify,
            "document_id": (req.document_id or "").strip()[:36] or None,
            "user_ref": (req.user_ref or "").strip()[:128] or None,
            **request_audit_meta(request),
        }
    )
    if req.save_calculation_history and bundle.get("payment"):
        slim_in = req.model_dump(
            exclude={"save_calculation_history", "document_id", "user_ref"},
            exclude_none=True,
        )
        save_calculation_record(
            input_payload={**slim_in, "effective_hs_code": bundle.get("effective_hs_code")},
            output_payload=bundle["payment"],
            document_id=req.document_id,
            user_ref=(req.user_ref or "").strip(),
            kind="copilot",
        )
    return JSONResponse({"status": "OK", "bundle": bundle, "context_for_ai": slim, "ai": ai})


@router.post("/copilot/batch")
async def assistant_copilot_batch(req: CopilotBatchRequest, request: Request) -> JSONResponse:
    for it in req.items:
        if not (it.description or "").strip() and not (it.hs_code or "").strip():
            raise HTTPException(
                status_code=400,
                detail="Каждая позиция должна содержать описание и/или код ТН ВЭД",
            )
    rows = [it.model_dump() for it in req.items]
    out = await run_copilot_batch(
        rows,
        run_ai_classification=req.run_ai_classification,
        run_payment=req.run_payment,
        run_registry_verify=req.run_registry_verify,
    )
    merged = dict(out["merged_context_for_ai"])
    desc_join = " | ".join((r.get("description") or "") for r in rows)[:800]
    rag = await rag_context_for_copilot(desc_join)
    sim = similar_decisions_context(desc_join, prefer_client_id=_prefer_client_id(request))
    merged = {**merged, **rag, **sim}
    ai = await analyze_copilot_bundle(merged)
    append_audit(
        {
            "action": "assistant.copilot_batch",
            "positions": len(rows),
            "registry_on": req.run_registry_verify,
            "document_id": (req.document_id or "").strip()[:36] or None,
            "user_ref": (req.user_ref or "").strip()[:128] or None,
            **request_audit_meta(request),
        }
    )
    if req.save_calculation_history and req.run_payment:
        pays: List[Dict[str, Any]] = []
        for b in out["bundles"]:
            p = b.get("payment")
            tot = None
            if isinstance(p, dict):
                tot = (p.get("breakdown") or {}).get("total_payable")
            pays.append({"effective_hs": b.get("effective_hs_code"), "total": tot})
        save_calculation_record(
            input_payload={
                "positions": len(rows),
                "run_payment": req.run_payment,
                "run_registry_verify": req.run_registry_verify,
            },
            output_payload={"batch": True, "payments": pays},
            document_id=req.document_id,
            user_ref=(req.user_ref or "").strip(),
            kind="copilot_batch",
        )
    return JSONResponse(
        {
            "status": "OK",
            "bundles": out["bundles"],
            "context_for_ai": merged,
            "ai": ai,
        }
    )


@router.post("/analyze")
async def assistant_analyze(req: AssistantRequest, request: Request) -> JSONResponse:
    """Комбинированный анализ: правила нетарифки + ИИ-заключение."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Список позиций пуст")

    logger.info(f"Ассистент: анализ {len(req.items)} позиций")

    # 1. Проверка по правилам
    check_results: List[Dict[str, Any]] = []
    for item in req.items:
        res = await check_position_non_tariff(
            item.hs_code,
            item.description,
            item.country,
            [{"type": p.type, "number": p.number} for p in item.permits],
        )
        check_results.append(res)

    # 2. ИИ-анализ поверх результатов (+ похожие записи журнала по описаниям)
    desc_join = " | ".join((item.description or "").strip() for item in req.items)[:800]
    sim_ctx = similar_decisions_context(desc_join, prefer_client_id=_prefer_client_id(request))
    ai_result = await analyze_non_tariff(
        check_results,
        extra_context=sim_ctx,
    )

    append_audit(
        {
            "action": "assistant.analyze",
            "items": len(req.items),
            **request_audit_meta(request),
        }
    )

    return JSONResponse({
        "status": ai_result.get("status", "OK"),
        "items": check_results,
        "ai": ai_result,
    })


@chat_router.post("/chat")
async def assistant_chat(req: AssistantChatRequest, request: Request) -> JSONResponse:
    """Диалог с ИИ с учётом контекста текущего расчёта (калькулятор)."""
    eff = req.resolved_context()
    ctx_dict: dict[str, Any] | None = None
    if eff is not None:
        ctx_dict = eff.model_dump(mode="json", exclude_none=True)
    answer = await run_assistant_chat(
        message=req.message.strip(),
        history=[h.model_dump() for h in req.history],
        current_context=ctx_dict,
    )
    append_audit(
        {
            "action": "assistant.chat",
            "has_context": eff is not None,
            "hs": (eff.hs_code if eff else "") or "",
            **request_audit_meta(request),
        }
    )
    return JSONResponse({"status": "OK", "answer": answer})
