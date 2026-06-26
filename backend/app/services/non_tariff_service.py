# Non-tariff measures service
from typing import List, Dict, Optional
from ..db import SessionLocal
from ..models import NTMMeasure

def check(hs_code: str, description: Optional[str] = None, country: Optional[str] = None) -> Dict[str, any]:
    """
    Поиск нетарифных мер по коду ТН ВЭД с поиском по префиксам
    """
    db = SessionLocal()
    try:
        measures = []
        
        # Поиск по префиксам (4 и 6 знаков)
        for prefix_length in [6, 4]:
            if len(hs_code) >= prefix_length:
                prefix = hs_code[:prefix_length]
                ntm_measures = db.query(NTMMeasure).filter(
                    NTMMeasure.hs_code_prefix == prefix
                ).all()
                
                for measure in ntm_measures:
                    # Фильтрация по стране, если указана
                    if country and measure.country and measure.country != country:
                        continue
                    
                    measures.append({
                        "title": measure.title,
                        "basis": measure.basis,
                        "country": measure.country,
                        "notes": measure.notes
                    })
        
        return {
            "hs_code": hs_code,
            "measures": measures,
            "country": country,
            "description": description,
            "total_found": len(measures)
        }
        
    except Exception as e:
        # В случае ошибки возвращаем пустой результат
        return {
            "hs_code": hs_code,
            "measures": [],
            "country": country,
            "description": description,
            "total_found": 0,
            "error": str(e)
        }
    finally:
        db.close()
