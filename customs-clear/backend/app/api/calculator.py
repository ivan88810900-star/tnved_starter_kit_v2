from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from loguru import logger

from ..schemas.payment_profile import (
    PaymentCompareResponse,
    PaymentProfileResponse,
)
from ..services.calculation_history_service import save_calculation_record
from ..services.exchange_rates import get_rates_map
from ..services.payment_profile_builder import (
    build_compare_payment_profiles,
)
from ..services.export_service import generate_final_customs_excel
from ..security import require_admin_token
from ..services.payment_engine_compat import (
    compute_payments,
    get_commodity_meta_info,
    get_duty_rule_info,
)


def _round2(value: float) -> float:
    return round(float(value), 2)


router = APIRouter()

class CompareSharedEconomics(BaseModel):
    """Общие параметры для всех сценариев сравнения."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    customs_value: float
    invoice_currency: str = Field(default="RUB", validation_alias=AliasChoices("invoice_currency", "currency"))
    freight: float = 0.0
    insurance: float | None = None
    country: str | None = None
    quantity: float | None = None
    net_weight_kg: float | None = Field(default=None, validation_alias=AliasChoices("net_weight_kg", "weight_kg"))
    extra_quantity: float | None = None
    apply_reduced_vat: bool = False


class CompareScenarioIn(BaseModel):
    hs_code: str
    label: str | None = None
    country: str | None = None
    duty_rate: float | None = None
    vat_rate: float | None = None
    excise: float | None = None


class CompareRequest(BaseModel):
    """Сравнение платежей при разных ТН ВЭД и одинаковой стоимости поставки."""

    shared: CompareSharedEconomics
    scenarios: list[CompareScenarioIn] = Field(..., min_length=2, max_length=8)
    save_history: bool = Field(True, description="Сохранить расчёт в customs_calculation_history")
    document_id: str | None = Field(None, description="Связь с ingested_documents.id")
    user_ref: str = Field("", description="Пользователь / клиент для журнала")


class CalculatorRequest(BaseModel):
    """Вход расчётного движка: ТН ВЭД, стоимость, фрахт, страховка, количество, признаки льгот."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    hs_code: str
    customs_value: float  # инвойсная стоимость (в валюте invoice_currency)
    invoice_currency: str = Field(default="RUB", validation_alias=AliasChoices("invoice_currency", "currency"))
    freight: float = 0.0
    insurance: float | None = None
    duty_rate: float | None = None  # ставка пошлины в % (переопределение)
    vat_rate: float | None = None  # ставка НДС (переопределение)
    excise: float | None = None  # акциз в руб. (переопределение)
    country: str | None = Field(default=None, validation_alias=AliasChoices("country", "country_of_origin"))  # страна происхождения (ISO-2)
    quantity: float | None = None  # количество/объём для акциза и антидемпинга
    net_weight_kg: float | None = Field(default=None, validation_alias=AliasChoices("net_weight_kg", "weight_kg"))  # вес нетто для специфических ставок /kg
    extra_quantity: float | None = None  # объём/шт для специфических ставок /l, /pcs и т.д.
    apply_reduced_vat: bool = False  # льготный НДС 10%
    vehicle_is_new: bool | None = None  # ТС: новое (True) / б.у. (False) — для утильсбора (8701-8705, 8711)
    engine_volume: int | None = None  # объём двигателя, см³ — выбор ставки утильсбора
    save_history: bool = Field(True, description="Сохранить расчёт в customs_calculation_history")
    document_id: str | None = Field(None, description="Связь с ingested_documents.id")
    user_ref: str = Field("", description="Пользователь / клиент для журнала")


class ExportExcelItemIn(BaseModel):
    item_description: str = Field("", description="Описание строки из инвойса")
    ai_technical_description: str | None = Field(None, description="Техническое описание по фото/ИИ")
    payment_profile: PaymentProfileResponse
    # В PaymentProfileResponse сейчас нет rate-полей, поэтому принимаем их опционально.
    duty_rate: float | None = None
    vat_rate: float | None = None


class ExportExcelRequest(BaseModel):
    items: list[ExportExcelItemIn] = Field(default_factory=list)


@router.post("/compute")
async def compute(req: CalculatorRequest) -> JSONResponse:
    """Расчёт платежей: пошлина, НДС, акциз, антидемпинг, утильсбор.

    Возвращает развёрнутый профиль расчёта (богатый контракт):
    `breakdown` (включая `duty_rate`, `vat_rate`, `recycling_fee`),
    `auto_detected`, `tnved_context`, `special_duties`, `tariff_preference`
    и метаданные утильсбора — именно эти поля потребляет UI калькулятора.
    """
    try:
        logger.info(f"Расчёт платежей для кода {req.hs_code}")
        payload = req.model_dump(exclude={"save_history", "document_id", "user_ref"})
        rates = get_rates_map()
        invoice_currency = (req.invoice_currency or "RUB").upper().strip()
        if invoice_currency not in rates:
            raise HTTPException(status_code=400, detail=f"Неизвестная валюта инвойса: {invoice_currency}")
        invoice_fx_rate = float(rates.get(invoice_currency) or 1.0)
        invoice_amount = float(req.customs_value)
        customs_value_rub = invoice_amount * invoice_fx_rate
        payload["customs_value"] = customs_value_rub
        payload["hs_code"] = req.hs_code
        payload["country"] = req.country
        payload["_fx_rates"] = rates
        result = compute_payments(payload)
        result["invoice"] = {
            "currency": invoice_currency,
            "amount": _round2(invoice_amount),
            "fx_rate": _round2(invoice_fx_rate),
            "customs_value_rub": _round2(customs_value_rub),
        }
        result["fx_source"] = "ЦБ РФ"
        if req.save_history:
            save_calculation_record(
                input_payload=payload,
                output_payload=result,
                document_id=req.document_id,
                user_ref=req.user_ref or "",
                kind="compute",
            )
        return JSONResponse(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Критическая ошибка /api/calculator/compute")
        raise HTTPException(status_code=500, detail=f"Ошибка расчета: {exc}")


@router.post("/calculate")
async def calculate(req: CalculatorRequest) -> JSONResponse:
    """Совместимый alias для /compute."""
    return await compute(req)


@router.post("/export-excel", response_model=None)
async def export_excel(req: ExportExcelRequest) -> Response:
    """Экспорт финального XLSX по рассчитанным профилям платежей/комплаенса."""
    if not req.items:
        raise HTTPException(status_code=400, detail="items не должны быть пустыми")
    payload = [x.model_dump() for x in req.items]
    xlsx_bytes = generate_final_customs_excel(payload)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="customs_final_export.xlsx"'},
    )


@router.get("/duty-rule/{hs_code}")
async def duty_rule(hs_code: str) -> JSONResponse:
    rule = get_duty_rule_info(hs_code)
    meta = get_commodity_meta_info(hs_code)
    return JSONResponse({"status": "OK", "hs_code": hs_code, "duty_rule": rule, "commodity_meta": meta})


@router.post("/compare", response_model=PaymentCompareResponse)
async def compare(req: CompareRequest) -> PaymentCompareResponse:
    """Сравнение 2–8 кодов ТН ВЭД при общих customs_value / freight / стране и т.д."""
    try:
        rates = get_rates_map()
        shared = req.shared.model_dump(exclude_none=True)
        invoice_currency = (shared.get("invoice_currency") or "RUB").upper().strip()
        if invoice_currency not in rates:
            raise HTTPException(status_code=400, detail=f"Неизвестная валюта инвойса: {invoice_currency}")
        invoice_fx_rate = float(rates.get(invoice_currency) or 1.0)
        shared["customs_value"] = float(shared.get("customs_value") or 0.0) * invoice_fx_rate
        shared["_fx_rates"] = rates
        payload = {
            "shared": shared,
            "scenarios": [s.model_dump(exclude_none=True) for s in req.scenarios],
        }
        result = build_compare_payment_profiles(payload=payload)
        if req.save_history:
            save_calculation_record(
                input_payload=payload,
                output_payload=result.model_dump(),
                document_id=req.document_id,
                user_ref=req.user_ref or "",
                kind="compare",
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Критическая ошибка /api/calculator/compare")
        raise HTTPException(status_code=500, detail=f"Ошибка сравнения: {exc}")


class ScenarioCompareBase(BaseModel):
    hs_code: str
    customs_value: float
    currency: str = "USD"
    weight_gross_kg: float | None = None
    weight_net_kg: float | None = None
    country: str | None = None


class ScenarioCompareItem(BaseModel):
    name: str = "Сценарий"
    hs_code: str | None = None
    country_of_origin: str | None = None
    procedure_code: str | None = None


class ScenarioCompareRequest(BaseModel):
    base: ScenarioCompareBase
    scenarios: list[ScenarioCompareItem] = Field(..., min_length=2, max_length=8)


@router.post("/compare-scenarios")
async def compare_scenarios(req: ScenarioCompareRequest) -> JSONResponse:
    """Сравнение сценариев: страны, коды, процедуры + РОП (#146)."""
    from ..services.scenario_compare_service import compare_scenarios_extended

    try:
        result = compare_scenarios_extended(req.model_dump())
        return JSONResponse(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/history/summary")
async def calculator_history_summary(
    user_ref: str = "",
    document_id: str = "",
    created_from: str | None = None,
    created_to: str | None = None,
) -> JSONResponse:
    """Сводка по типам записей (для фильтров в UI)."""
    from ..services.calculation_history_service import summarize_calculation_history

    data = summarize_calculation_history(
        user_ref=user_ref,
        document_id=document_id,
        created_from=created_from,
        created_to=created_to,
    )
    return JSONResponse({"status": "OK", **data})


@router.get("/history/export", response_model=None)
async def calculator_history_export(
    format: str = Query("csv", description="csv или json"),
    user_ref: str = "",
    kind: str | None = Query(None, description="Тип записи"),
    document_id: str = "",
    created_from: str | None = None,
    created_to: str | None = None,
    limit: int = Query(2000, ge=1, le=10000),
    full_json: bool = Query(False, description="В JSON добавить полные input/output"),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> PlainTextResponse | JSONResponse:
    """Выгрузка журнала расчётов. Требует X-Admin-Token."""
    require_admin_token(x_admin_token)
    from ..services.calculation_history_service import (
        calculation_history_as_csv,
        export_calculation_history_rows,
    )

    fmt = (format or "csv").strip().lower()
    if fmt not in ("csv", "json"):
        raise HTTPException(status_code=400, detail="format должен быть csv или json")
    rows = export_calculation_history_rows(
        user_ref=user_ref,
        kind=kind,
        document_id=document_id,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        full_json=full_json,
    )
    if fmt == "csv":
        return PlainTextResponse(
            calculation_history_as_csv(rows),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="calculation_history.csv"'},
        )
    return JSONResponse({"status": "OK", "count": len(rows), "items": rows})


@router.get("/history")
async def calculator_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = 0,
    user_ref: str = "",
    document_id: str = "",
    created_from: str | None = None,
    created_to: str | None = None,
    kind: str | None = Query(
        None,
        description="Фильтр: compute | compare | compliance | copilot | copilot_batch",
    ),
) -> JSONResponse:
    """Последние сохранённые расчёты (таблица customs_calculation_history)."""
    from ..services.calculation_history_service import list_calculation_history

    items = list_calculation_history(
        limit=limit,
        offset=offset,
        user_ref=user_ref,
        kind=kind,
        document_id=document_id,
        created_from=created_from,
        created_to=created_to,
    )
    return JSONResponse({"status": "OK", "items": items})


@router.get("/history/{calc_id}")
async def calculator_history_item(calc_id: str) -> JSONResponse:
    from ..services.calculation_history_service import get_calculation_record

    row = get_calculation_record(calc_id)
    if not row:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return JSONResponse({"status": "OK", **row})

