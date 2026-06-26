from sqlalchemy import select
from ..db import SessionLocal
from ..models import TariffRate
from ..models_vat import VatRule

def lookup(hs_code: str):
    code = (hs_code or "").replace(".", "").strip()
    db = SessionLocal()
    try:
        # Сначала ищем точное совпадение
        exact_match = db.execute(
            select(TariffRate).where(TariffRate.hs_code == code)
        ).scalars().all()
        
        if exact_match:
            r = exact_match[0]
            return {
                "duty": r.duty,
                "vat": r.vat,
                "add": r.add,
                "version": r.source_version
            }
        
        # Если точного совпадения нет, НЕ ищем по префиксам
        # Возвращаем N/A для несуществующих кодов
        return {"duty": "N/A", "vat": "N/A", "add": None}
    finally:
        db.close()

def resolve_vat_for_code(hs_code: str):
    code = (hs_code or "").replace(".", "").strip()
    db = SessionLocal()
    try:
        # ищем самый длинный префикс
        lengths = [10, 8, 6, 4, 2]
        for L in lengths:
            pref = code[:L]
            rows = db.execute(select(VatRule).where(VatRule.code_prefix == pref)).scalars().all()
            if rows:
                row = rows[0]
                # вернём ставку + источник + наименование из перечня
                return row.rate, row.source, row.title
        return 20, "DEFAULT", "Общая ставка НДС по умолчанию"
    finally:
        db.close()
