"""Invoice upload and batch payment calculation (#145)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..security import require_authenticated_user
from ..services.invoice_batch_service import (
    build_invoice_template_xlsx,
    calculate_batch_lines,
    parse_invoice_file,
)
from ..services.packing_list_parser import parse_packing_list
from ..services.smart_classifier import get_smart_classifier

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


@router.post("/upload-packing-list")
async def upload_packing_list(
    file: UploadFile = File(...),
    classify: bool = Form(False),
    max_rows: int = Form(10),
    start_row: int = Form(1),
) -> dict:
    """Универсальный разбор пакинг-листа (.xlsx) с автоопределением колонок."""
    name = (file.filename or "").lower()
    if not name.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Поддерживается только .xlsx")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Пустой файл")

    max_rows = max(1, min(int(max_rows), 500))
    start_row = max(1, int(start_row))

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        rows, meta = parse_packing_list(tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Не удалось разобрать файл: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if not rows:
        raise HTTPException(status_code=422, detail="В файле не найдено строк данных")

    slice_start = start_row - 1
    slice_end = slice_start + max_rows
    selected = rows[slice_start:slice_end]

    results: list[dict] = []
    for row in selected:
        item: dict = row.to_dict(include_image=classify)
        if classify:
            desc_parts = [p for p in (row.name_cn, row.material) if p]
            clf = await get_smart_classifier().classify(
                description=" ".join(desc_parts) if desc_parts else None,
                image_base64=row.image_base64,
                article=row.article,
            )
            api = clf.to_api_dict()
            item["translation_used"] = api.get("translation_used") or ""
            item["visual_analysis"] = api.get("visual_analysis")
            item["classify_status"] = api.get("status")
            top = (api.get("results") or [{}])[0] if api.get("results") else {}
            item["hs_code"] = top.get("hs_code")
            item["hs_confidence"] = top.get("confidence")
            item["hs_description"] = top.get("description")
            item["hs_rationale"] = top.get("rationale")
            item["classify_results"] = api.get("results") or []
            if api.get("note"):
                item["classify_note"] = api.get("note")
        results.append(item)

    return {
        "status": "OK",
        "meta": meta,
        "results": results,
    }
