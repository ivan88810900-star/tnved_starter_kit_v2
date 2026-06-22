"""Invoice upload and batch payment calculation (#145)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..security import require_authenticated_user
from ..services.invoice_batch_service import (
    build_invoice_template_xlsx,
    calculate_batch_lines,
    parse_invoice_file,
)

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


class InvoiceLineIn(BaseModel):
    description: str
    hs_code: str = ""
    quantity: float = 1.0
    unit: str = ""
    unit_price: float = 0.0
    currency: str = "USD"
    weight_gross_kg: float | None = None
    weight_net_kg: float | None = None
    country_of_origin: str = ""


class InvoiceBatchRequest(BaseModel):
    lines: list[InvoiceLineIn] = Field(..., min_length=1, max_length=500)
    auto_classify: bool = True
    calendar_year: int | None = None


@router.get("/template")
def invoice_template() -> Response:
    data = build_invoice_template_xlsx()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="invoice_template.xlsx"'},
    )


@router.post("/upload")
async def invoice_upload(
    file: UploadFile = File(...),
    auto_classify: bool = True,
    calendar_year: int | None = None,
) -> dict:
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="Поддерживаются .xlsx, .xls, .csv")
    content = await file.read()
    try:
        lines = parse_invoice_file(content, name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not lines:
        raise HTTPException(status_code=422, detail="Файл не содержит позиций")
    return await calculate_batch_lines(lines, auto_classify=auto_classify, calendar_year=calendar_year)


@router.post("/calculate-batch")
async def invoice_calculate_batch(body: InvoiceBatchRequest) -> dict:
    lines = [ln.model_dump() for ln in body.lines]
    return await calculate_batch_lines(
        lines,
        auto_classify=body.auto_classify,
        calendar_year=body.calendar_year,
    )
