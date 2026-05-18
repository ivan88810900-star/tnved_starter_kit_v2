from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Query, Header, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from .db import init_db, SessionLocal
from .models_hs import HSCode, Note
from .models import TariffRate, NTMMeasure, DataSource
from .ai import ai_classify
from .services import tariff_service, non_tariff_service
from .middleware.ai_security import AISecurityMiddleware
from sqlalchemy import text, inspect
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
from pathlib import Path
import base64
import os
from .routers import batch, tariff as tariff_router, codes as codes_router, notes as notes_router, vat as vat_router, classify as classify_router

app = FastAPI(title="TN VED Pro API", version="0.1.0")

# Сжатие ответов GZip
app.add_middleware(GZipMiddleware, minimum_size=500)

# Добавляем CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Добавляем AI Security middleware
app.add_middleware(AISecurityMiddleware)

@app.on_event("startup")
def startup():
    init_db()

@app.get("/health")
def health():
    return {"ok": True}

debug_router = APIRouter(prefix="/debug", tags=["debug"])

@debug_router.get("/dbinfo")
def dbinfo():
    db = SessionLocal()
    try:
        inspector = inspect(db.bind)
        hs = db.execute(text("SELECT COUNT(*) FROM hs_codes")).scalar() if inspector.has_table("hs_codes") else None
        nt = db.execute(text("SELECT COUNT(*) FROM notes")).scalar() if inspector.has_table("notes") else None
        return {"db_url": str(db.bind.url), "hs_codes": hs, "notes": nt}
    finally:
        db.close()

class ClassifyRequest(BaseModel):
    text: str | None = None
    image_base64: str | None = None
    hints: list[str] | None = None

@app.post("/classify")
def classify(req: ClassifyRequest):
    """Классификация товара с ИИ и пост-валидацией"""
    if not req.text and not req.image_base64:
        raise HTTPException(400, "Provide 'text' and/or 'image_base64'")
    # Если явно передан некорректный image_base64 без текста — считаем ошибкой
    if req.text is None and req.image_base64:
        # минимальная проверка base64
        try:
            base64.b64decode(req.image_base64, validate=True)
        except Exception:
            raise HTTPException(400, "Invalid image_base64")
    
    # Получаем результат от ИИ
    ai_result = ai_classify(text=req.text, image_b64=req.image_base64, hints=req.hints or [])
    
    # Пост-валидация и улучшение результата
    db = SessionLocal()
    try:
        validated_result = validate_and_enhance_classification(ai_result, db)
        
        # Логируем классификацию только если включено
        if os.getenv("AUDIT_LOGGING", "false").lower() == "true":
            _log_classification(req, validated_result)
        
        return validated_result
    finally:
        db.close()

def validate_and_enhance_classification(ai_result, db):
    """Валидация и улучшение результата классификации"""
    if not ai_result or 'codes' not in ai_result:
        return ai_result
    
    validated_codes = []
    
    for code_info in ai_result['codes']:
        hs_code = code_info.get('code', '')
        
        # Проверяем существование кода в БД
        existing_code = db.query(HSCode).filter(HSCode.code == hs_code).first()
        
        if existing_code:
            # Код существует - добавляем дополнительную информацию
            enhanced_code = {
                **code_info,
                'validated': True,
                'title_ru': existing_code.title_ru,
                'title_en': existing_code.title_en,
                'chapter': existing_code.chapter,
                'heading': existing_code.heading,
                'subheading': existing_code.subheading,
                'notes': get_related_notes(existing_code, db)
            }
            validated_codes.append(enhanced_code)
        else:
            # Код не найден - ищем ближайшие по дереву
            similar_codes = find_similar_codes(hs_code, db)
            if similar_codes:
                for similar_code in similar_codes:
                    enhanced_code = {
                        **code_info,
                        'code': similar_code.code,
                        'validated': False,
                        'suggestion': True,
                        'title_ru': similar_code.title_ru,
                        'title_en': similar_code.title_en,
                        'chapter': similar_code.chapter,
                        'heading': similar_code.heading,
                        'subheading': similar_code.subheading,
                        'notes': get_related_notes(similar_code, db)
                    }
                    validated_codes.append(enhanced_code)
            else:
                # Добавляем исходный код с пометкой о невалидности
                validated_codes.append({
                    **code_info,
                    'validated': False,
                    'error': 'Code not found in database'
                })
    
    # Обновляем результат
    result = ai_result.copy()
    result['codes'] = validated_codes
    
    # Добавляем статистику валидации
    result['validation_stats'] = {
        'total_codes': len(validated_codes),
        'valid_codes': len([c for c in validated_codes if c.get('validated', False)]),
        'suggestions': len([c for c in validated_codes if c.get('suggestion', False)]),
        'invalid_codes': len([c for c in validated_codes if not c.get('validated', False) and not c.get('suggestion', False)])
    }
    
    return result

def find_similar_codes(hs_code, db):
    """Поиск ближайших кодов по дереву (6/4/2 знака)"""
    similar_codes = []
    
    # Пробуем найти по усеченным кодам
    for prefix_length in [6, 4, 2]:
        if len(hs_code) > prefix_length:
            prefix = hs_code[:prefix_length]
            codes = db.query(HSCode).filter(HSCode.code.like(f"{prefix}%")).limit(3).all()
            similar_codes.extend(codes)
            if similar_codes:
                break
    
    return similar_codes

def get_related_notes(hs_code_obj, db):
    """Получение связанных примечаний для кода"""
    notes = []
    
    # Примечания к главе
    if hs_code_obj.chapter:
        chapter_notes = db.query(Note).filter(
            Note.level == "chapter",
            Note.ref_id == hs_code_obj.chapter
        ).all()
        notes.extend(chapter_notes)
    
    # Примечания к разделу
    section_mapping = {"01": "I", "02": "II", "03": "III", "04": "IV", "05": "V", "06": "VI"}
    if hs_code_obj.chapter in section_mapping:
        section_notes = db.query(Note).filter(
            Note.level == "section",
            Note.ref_id == section_mapping[hs_code_obj.chapter]
        ).all()
        notes.extend(section_notes)
    
    return [
        {
            "level": note.level,
            "ref_id": note.ref_id,
            "text": note.text
        }
        for note in notes
    ]

@app.get("/codes/tree")
def codes_tree(depth: str = "chapter"):
    # demo stub — return minimal shape
    return {
        "depth": depth,
        "nodes": [
            {"id": "01", "title": "Живые животные", "children": []},
            {"id": "02", "title": "Мясо и пищевые мясные субпродукты", "children": []},
        ]
    }

# /codes/search реализован в routers.codes

# /codes/{hs_code} реализован в routers.codes

@app.get("/notes/{level}/{id}")
def get_notes(level: str, id: str):
    """Получение примечаний по уровню и ID"""
    db = SessionLocal()
    try:
        q = db.query(Note).filter(Note.level == level, Note.ref_id == id).all()
        return [{"level": n.level, "ref_id": n.ref_id, "text": n.text} for n in q]
    finally:
        db.close()

## /tariff реализован в routers.tariff

class NonTariffRequest(BaseModel):
    hs_code: str
    description: str | None = None
    country: str | None = None

@app.post("/non_tariff")
def non_tariff(req: NonTariffRequest):
    return non_tariff_service.check(req.hs_code, req.description, req.country)

class EcoFeeRequest(BaseModel):
    hs_code: str
    weight_net_kg: float
    material: str | None = None

@app.post("/eco_fee")
def eco_fee(req: EcoFeeRequest):
    # Placeholder: replace with real tables
    rate_per_kg = 12.5
    return {
        "hs_code": req.hs_code,
        "rate_per_kg": rate_per_kg,
        "fee": round(rate_per_kg * req.weight_net_kg, 2)
    }

@app.get("/data/sources")
def get_data_sources():
    """Список загруженных источников данных"""
    db = SessionLocal()
    try:
        sources = db.query(DataSource).order_by(DataSource.imported_at.desc()).all()
        return [
            {
                "key": source.key,
                "version": source.version,
                "authority": source.authority,
                "url": source.url,
                "checksum": source.checksum,
                "imported_at": source.imported_at.isoformat() if source.imported_at else None
            }
            for source in sources
        ]
    finally:
        db.close()

def verify_api_key(api_key: str = Header(..., alias="X-API-Key")):
    """Проверка API ключа для административных операций"""
    expected_key = os.getenv("ADMIN_API_KEY")
    if not expected_key:
        raise HTTPException(500, "Admin API key not configured")
    if api_key != expected_key:
        raise HTTPException(401, "Invalid admin API key")
    return api_key

@app.post("/admin/reindex")
def reindex_data(api_key: str = Depends(verify_api_key)):
    """Переиндексация данных (защищено API ключом)"""
    # Здесь можно добавить логику переиндексации FTS
    # Пока что просто возвращаем успех
    return {
        "status": "success",
        "message": "Reindexing completed",
        "timestamp": "2024-01-01T00:00:00Z"
    }

def _log_classification(req: ClassifyRequest, result: dict):
    """Логирование классификации для аудита"""
    import logging
    from datetime import datetime
    
    logger = logging.getLogger(__name__)
    
    # Логируем только основную информацию, без персональных данных
    log_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "has_text": bool(req.text),
        "has_image": bool(req.image_base64),
        "hints_count": len(req.hints or []),
        "result_hs_code": result.get("hs_code"),
        "confidence": result.get("confidence", 0.0),
        "validated": result.get("validated", False),
    }
    
    logger.info(f"Classification audit: {log_data}")

app.include_router(batch.router)
app.include_router(tariff_router.router)
app.include_router(codes_router.router)
app.include_router(notes_router.router)
app.include_router(vat_router.router)
app.include_router(classify_router.router)
app.include_router(debug_router)

# Static files (css/js) from UI directory
STATIC_DIR = Path(__file__).parent / "ui"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/ui/classifier", response_class=HTMLResponse)
def ui_classifier():
    return (Path(__file__).parent / "ui" / "classifier.html").read_text("utf-8")

@app.get("/ui/tree", response_class=HTMLResponse)
def ui_tree():
    return (Path(__file__).parent / "ui" / "tnved_tree.html").read_text("utf-8")

@app.get("/ui/modern", response_class=HTMLResponse)
def ui_modern():
    return (Path(__file__).parent / "ui" / "modern.html").read_text("utf-8")

@app.get("/ui/hierarchy", response_class=HTMLResponse)
def ui_hierarchy():
    return (Path(__file__).parent / "ui" / "tnved_hierarchy.html").read_text("utf-8")

@app.get("/ui/customs_verifier", response_class=HTMLResponse)
def ui_customs_verifier():
    """Одностраничное приложение для проверки нетарифного контроля по инвойсу"""
    return (Path(__file__).parent / "ui" / "customs_verifier.html").read_text("utf-8")
