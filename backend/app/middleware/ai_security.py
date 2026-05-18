"""
Middleware для контроля ИИ-вызовов и безопасности
"""
import os
import logging
from typing import Callable
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

class AISecurityMiddleware:
    """Middleware для контроля внешних ИИ-вызовов"""
    
    def __init__(self, app):
        self.app = app
        self.allow_external_ai = os.getenv("ALLOW_EXTERNAL_AI", "false").lower() == "true"
        self.audit_logging = os.getenv("AUDIT_LOGGING", "false").lower() == "true"
        
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            
            # Проверяем, является ли запрос к ИИ-эндпоинту
            if self._is_ai_endpoint(request.url.path):
                if not self.allow_external_ai:
                    logger.warning(f"Блокирован ИИ-вызов к {request.url.path} - ALLOW_EXTERNAL_AI=false")
                    response = JSONResponse(
                        status_code=403,
                        content={
                            "error": "External AI calls are disabled",
                            "message": "Внешние ИИ-вызовы отключены для безопасности"
                        }
                    )
                    await response(scope, receive, send)
                    return
                
                # Логируем ИИ-вызовы если включено
                if self.audit_logging:
                    await self._log_ai_request(request)
        
        await self.app(scope, receive, send)
    
    def _is_ai_endpoint(self, path: str) -> bool:
        """Проверяет, является ли эндпоинт ИИ-связанным"""
        ai_endpoints = [
            "/classify",
            "/batch/classify",
            "/ai/",
        ]
        return any(path.startswith(endpoint) for endpoint in ai_endpoints)
    
    async def _log_ai_request(self, request: Request):
        """Логирует ИИ-запросы для аудита"""
        try:
            # Получаем IP адрес клиента
            client_ip = request.client.host if request.client else "unknown"
            
            # Получаем заголовки
            user_agent = request.headers.get("user-agent", "unknown")
            
            logger.info(f"ИИ-запрос: {request.method} {request.url.path} от {client_ip} ({user_agent})")
            
            # Здесь можно добавить сохранение в базу данных для аудита
            # await self._save_ai_audit_log(request, client_ip)
            
        except Exception as e:
            logger.error(f"Ошибка логирования ИИ-запроса: {e}")

def create_ai_security_middleware(app):
    """Создает middleware для контроля ИИ-вызовов"""
    return AISecurityMiddleware(app)
















