import os
import logging
from typing import List, Optional, Dict, Any
from .ai_providers import classify_with_rag

logger = logging.getLogger(__name__)

def ai_classify(text: Optional[str], image_b64: Optional[str], hints: List[str]) -> Dict[str, Any]:
    """
    Классификация товара с использованием AI провайдеров
    """
    try:
        # Используем провайдерный слой с RAG
        result = classify_with_rag(text, image_b64, hints)
        
        # Преобразуем результат в ожидаемый формат
        if "error" in result:
            logger.error(f"Ошибка классификации: {result['error']}")
            return {
                "hs_code": "0000.00.00.00",
                "confidence": 0.0,
                "rationale": [f"Ошибка: {result['error']}"],
                "alternatives": []
            }
        
        # Формируем ответ в ожидаемом формате
        response = {
            "hs_code": result.get("hs_code", "0000.00.00.00"),
            "confidence": result.get("confidence", 0.0),
            "rationale": result.get("rationale", []),
            "alternatives": result.get("alternatives", [])
        }
        
        # Добавляем дополнительную информацию если есть
        if "validated" in result:
            response["validated"] = result["validated"]
        
        if "title_ru" in result:
            response["title_ru"] = result["title_ru"]
        
        if "title_en" in result:
            response["title_en"] = result["title_en"]
        
        if "clarification_questions" in result:
            response["clarification_questions"] = result["clarification_questions"]
        
        if "offline_mode" in result:
            response["offline_mode"] = result["offline_mode"]
        
        return response
        
    except Exception as e:
        logger.error(f"Критическая ошибка в ai_classify: {e}")
        return {
            "hs_code": "0000.00.00.00",
            "confidence": 0.0,
            "rationale": [f"Критическая ошибка: {str(e)}"],
            "alternatives": []
        }
