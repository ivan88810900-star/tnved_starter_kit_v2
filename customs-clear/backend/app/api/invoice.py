"""Invoice upload and batch payment calculation (#145)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..security import require_authenticated_user
from ..services.invoice_batch_service import (
    build_invoice_template_xlsx,
    calculate_batch_lines,
    parse_invoice_file,
)
from ..services.packing_list_tasks import (
    create_packing_list_task,
    get_task,
    get_task_export_path,
    get_task_results,
    task_status_payload,
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


@router.post("/upload-packing-list")
async def upload_packing_list(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    classify: bool = Form(False),
    max_rows: int | None = Form(None),
    start_row: int = Form(1),
) -> dict:
    """Универсальный разбор пакинг-листа (.xlsx). При classify=true — фоновая задача."""
    name = (file.filename or "").strip()
    if not name.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Поддерживается только .xlsx")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Пустой файл")

    max_rows_int: int | None = None
    if max_rows is not None and str(max_rows).strip() != "":
        max_rows_int = max(1, min(int(max_rows), 500))

    try:
        return await create_packing_list_task(
            file_bytes=content,
            original_filename=Path(name).name,
            background_tasks=background_tasks,
            classify=bool(classify),
            max_rows=max_rows_int,
            start_row=max(1, int(start_row)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/task/{task_id}")
async def packing_list_task_status(task_id: str) -> dict:
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return task_status_payload(task)


@router.get("/task/{task_id}/results")
async def packing_list_task_results(
    task_id: str,
    start: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    payload = await get_task_results(task_id, start=start, limit=limit)
    if not payload:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return payload


@router.get("/download/{task_id}")
async def packing_list_download(task_id: str) -> FileResponse:
    export_path = await get_task_export_path(task_id)
    if not export_path:
        task = await get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        if task.get("status") == "processing":
            raise HTTPException(status_code=409, detail="Классификация ещё выполняется")
        raise HTTPException(status_code=404, detail="Файл экспорта недоступен")
    filename = export_path.name
    if filename.startswith("classified_"):
        parts = filename.split("_", 2)
        if len(parts) == 3:
            filename = f"classified_{parts[2]}"
    return FileResponse(
        path=export_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )
