from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import io, pandas as pd, json
from ..ai import ai_classify

router = APIRouter(prefix="/batch", tags=["batch"])

@router.get("/template")
def template():
    # Create simple Excel template in-memory
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "data"
    ws.append(["Description", "Hints"])  # optional Hints, comma-separated
    # sample rows
    ws.append(["Зеркало настенное стеклянное, без рамы", "зеркало, стекло"])
    ws.append(["Сайлентблок (деталь из резины для подвески авто)", "резина, автозапчасти"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="tnved_batch_template.xlsx"'}
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)

class BatchResult(BaseModel):
    row: int
    description: str | None
    hints: list[str] | None
    hs_code: str
    confidence: float
    rationale: list[str]

@router.post("/classify")
def classify(file: UploadFile = File(...)) -> list[BatchResult]:
    name = (file.filename or "").lower()
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(file.file)
        else:
            df = pd.read_excel(file.file)
    except Exception as e:
        raise HTTPException(400, f"Не удалось прочитать файл: {e}")
    results = []
    for i, row in df.iterrows():
        desc = str(row.get("Description") or "").strip()
        hints_raw = str(row.get("Hints") or "").strip()
        hints = [h.strip() for h in hints_raw.split(",") if h.strip()] if hints_raw else []
        res = ai_classify(text=desc or None, image_b64=None, hints=hints)
        results.append(BatchResult(row=int(i)+1, description=desc or None, hints=hints or None,
                                   hs_code=res["hs_code"], confidence=res["confidence"], rationale=res["rationale"]))
    return [r.model_dump() for r in results]

@router.post("/classify_xlsx")
def classify_xlsx(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    # Разрешаем только .xlsx и .csv
    if not (name.endswith(".xlsx") or name.endswith(".csv")):
        raise HTTPException(422, "Ожидается Excel (.xlsx) или CSV файл")
    # Чтение файла
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(file.file)
        else:
            df = pd.read_excel(file.file)
    except Exception as e:
        raise HTTPException(400, f"Не удалось прочитать файл: {e}")

    # Пустой файл: считаем корректной обработкой без результатов
    if df.empty or len(df.columns) == 0:
        return {
            "status": "success",
            "message": "Empty file processed",
            "processed_count": 0,
            "results": []
        }

    # Валидация структуры
    # Требуем колонку 'Описание' (рус.) или 'Description' (en)
    has_ru = 'Описание' in df.columns
    has_en = 'Description' in df.columns
    if not (has_ru or has_en):
        raise HTTPException(422, "Отсутствует обязательная колонка 'Описание' или 'Description'")

    results: list[dict] = []
    processed = 0
    for i, row in df.iterrows():
        description = str(row.get('Описание') if has_ru else row.get('Description') or "").strip() or None
        hints_raw = str(row.get('Подсказки') if 'Подсказки' in df.columns else row.get('Hints') or "").strip()
        hints = [h.strip() for h in hints_raw.split(',') if h.strip()] if hints_raw else []
        try:
            res = ai_classify(text=description, image_b64=None, hints=hints)
        except Exception as e:
            res = {"hs_code": "0000000000", "confidence": 0.0, "rationale": [f"Ошибка: {e}"]}
        item = {
            "row": int(i) + 1,
            "ID": row.get('ID') if 'ID' in df.columns else None,
            "Описание": description if has_ru else None,
            "description": description if has_en else None,
            "hints": hints or None,
            "hs_code": res.get("hs_code"),
            "confidence": float(res.get("confidence", 0.0)),
            "rationale": res.get("rationale", []),
        }
        results.append(item)
        processed += 1

    return {
        "status": "success",
        "message": f"Processed {processed} rows",
        "processed_count": processed,
        "results": results,
    }
