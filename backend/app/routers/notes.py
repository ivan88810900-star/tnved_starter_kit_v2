from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, or_, func
from ..db import SessionLocal
from ..models_hs import Note

router = APIRouter(prefix="/notes", tags=["notes"])

@router.get("/debug")
def debug_notes():
    """Отладочный endpoint для проверки подключения к базе данных"""
    db = SessionLocal()
    try:
        # Принудительно коммитим изменения
        db.commit()
        
        total_notes = db.execute(select(Note)).scalars().all()
        chapter_70_notes = db.execute(select(Note).where(Note.level=='chapter', Note.ref_id=='70')).scalars().all()
        
        return {
            "total_notes": len(total_notes),
            "chapter_70_notes": len(chapter_70_notes),
            "sample_notes": [
                {"level": n.level, "ref_id": n.ref_id, "text_preview": n.text[:50]} 
                for n in total_notes[:5]
            ]
        }
    finally:
        db.close()

@router.get("/search")
def search_notes(q: str = Query(..., min_length=1, max_length=200), level: str | None = None, ref_id: str | None = None, limit: int = 50):
    """Полнотекстовый поиск по примечаниям (регистронезависимый, по словам/фразам)."""
    db = SessionLocal()
    try:
        tokens = [t.strip() for t in q.split() if t.strip()]
        conditions = []
        # SQLite: используем LIKE с вариантами регистра для надежности на кириллице
        variants = {q, q.lower(), q.upper(), q.capitalize()}
        for v in variants:
            conditions.append(Note.text.like(f"%{v}%"))
        for t in tokens:
            for v in {t, t.lower(), t.upper(), t.capitalize()}:
                conditions.append(Note.text.like(f"%{v}%"))
        stmt = select(Note).where(or_(*conditions)) if conditions else select(Note)
        if level:
            stmt = stmt.where(Note.level == level)
        if ref_id:
            stmt = stmt.where(Note.ref_id == ref_id)
        rows = db.execute(stmt.limit(limit)).scalars().all()
        return [{"level": r.level, "ref_id": r.ref_id, "text": r.text} for r in rows]
    finally:
        db.close()

@router.get("/{level}/{ref_id}")
def get_note(level: str, ref_id: str):
    db = SessionLocal()
    try:
        # Принудительно коммитим изменения
        db.commit()
        
        notes = db.execute(select(Note).where(Note.level==level, Note.ref_id==ref_id)).scalars().all()
        if not notes: 
            raise HTTPException(404, f"notes not found for level={level}, ref_id={ref_id}")
        return [{"level": n.level, "ref_id": n.ref_id, "text": n.text} for n in notes]
    finally:
        db.close()

