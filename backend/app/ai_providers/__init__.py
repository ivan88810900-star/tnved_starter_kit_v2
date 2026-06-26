"""
AI Providers для классификации товаров
"""
import os
from typing import Dict, Any, List, Optional
from .openai import OpenAIProvider
from .qwen import QwenProvider
from .anthropic import AnthropicProvider
from .deepseek import DeepSeekProvider

def get_ai_provider() -> Optional[Any]:
    """Возвращает активный AI провайдер на основе конфигурации"""
    provider_name = os.getenv("AI_PROVIDER", "openai").lower()
    
    if provider_name == "openai":
        return OpenAIProvider()
    elif provider_name == "qwen":
        return QwenProvider()
    elif provider_name == "anthropic":
        return AnthropicProvider()
    elif provider_name == "deepseek":
        return DeepSeekProvider()
    else:
        return None

def classify_with_rag(text: str = None, image_b64: str = None, hints: List[str] = None) -> Dict[str, Any]:
    """
    Классификация товара с RAG (Retrieval-Augmented Generation)
    """
    # Проверяем офлайн режим
    if os.getenv("AI_OFFLINE_MODE", "false").lower() == "true":
        return classify_offline(text, image_b64, hints)
    
    # Проверяем разрешение внешних ИИ-вызовов
    if os.getenv("ALLOW_EXTERNAL_AI", "false").lower() != "true":
        return {
            "error": "External AI calls are disabled",
            "message": "Внешние ИИ-вызовы отключены для безопасности",
            "offline_mode": True
        }
    
    # Получаем провайдер
    provider = get_ai_provider()
    if not provider:
        return {"error": "No AI provider configured"}
    
    # Выполняем классификацию с RAG
    return provider.classify_with_rag(text, image_b64, hints or [])

def classify_offline(text: str = None, image_b64: str = None, hints: List[str] = None) -> Dict[str, Any]:
    """
    Офлайн классификация только на основе правил и БД
    """
    # Здесь можно добавить логику классификации на основе правил
    # Пока возвращаем заглушку
    # Простая заглушка с дополнительными полями для тестов
    result: Dict[str, Any] = {
        "hs_code": "0000000000",
        "confidence": 0.1,
        "rationale": ["Офлайн режим: классификация недоступна"],
        "alternatives": [],
        "offline_mode": True,
        "clarification_questions": [
            "Уточните материал изделия?",
            "Укажите назначение товара?"
        ],
    }
    # Если вход невалидный, имитируем ошибку валидации
    if text is None and image_b64:
        # в тестах это считается ошибкой 400 на уровне API, но здесь пометим результат
        result["error"] = "Invalid input"
    return result
