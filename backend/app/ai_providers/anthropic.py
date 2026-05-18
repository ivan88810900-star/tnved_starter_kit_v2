"""
Anthropic Provider для классификации товаров
"""
import os
import re
import logging
import requests
from typing import Dict, Any, List
from ..db import SessionLocal
from ..models_hs import HSCode

logger = logging.getLogger(__name__)

class AnthropicProvider:
    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        self.base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
    
    def classify_with_rag(self, text: str = None, image_b64: str = None, hints: List[str] = None) -> Dict[str, Any]:
        """
        Классификация с RAG (Retrieval-Augmented Generation)
        """
        try:
            # 1. Извлечение признаков
            features = self._extract_features(text, image_b64, hints)
            
            # 2. Сужение поиска по дереву
            candidate_codes = self._narrow_search(features)
            
            # 3. Основная классификация
            result = self._classify_with_model(features, candidate_codes, text, image_b64)
            
            # 4. Валидация и улучшение
            validated_result = self._validate_and_enhance(result)
            
            return validated_result
            
        except Exception as e:
            logger.error(f"Ошибка классификации Anthropic: {e}")
            return {"error": str(e)}
    
    def _extract_features(self, text: str, image_b64: str, hints: List[str]) -> Dict[str, Any]:
        """Извлечение признаков товара"""
        features = {
            "material": [],
            "purpose": [],
            "completeness": [],
            "keywords": []
        }
        
        if text:
            # Извлечение материала
            material_patterns = [
                r'пластик|пластмасса|полимер',
                r'металл|железо|сталь|алюминий',
                r'дерево|древесина',
                r'стекло|керамика',
                r'текстиль|ткань|хлопок|шерсть',
                r'резина|каучук',
                r'бумага|картон'
            ]
            
            for pattern in material_patterns:
                matches = re.findall(pattern, text.lower())
                features["material"].extend(matches)
            
            # Извлечение назначения
            purpose_patterns = [
                r'для\s+(\w+)',
                r'используется\s+для\s+(\w+)',
                r'применяется\s+в\s+(\w+)',
                r'назначение[:\s]+(\w+)'
            ]
            
            for pattern in purpose_patterns:
                matches = re.findall(pattern, text.lower())
                features["purpose"].extend(matches)
            
            # Извлечение комплектности
            completeness_patterns = [
                r'комплект|набор|серия',
                r'одиночный|единичный',
                r'упаковка|пачка|коробка'
            ]
            
            for pattern in completeness_patterns:
                matches = re.findall(pattern, text.lower())
                features["completeness"].extend(matches)
            
            # Общие ключевые слова
            words = re.findall(r'\b\w{3,}\b', text.lower())
            features["keywords"] = words[:20]
        
        return features
    
    def _narrow_search(self, features: Dict[str, Any]) -> List[str]:
        """Сужение поиска по дереву на основе признаков"""
        db = SessionLocal()
        try:
            candidate_codes = []
            
            # Поиск по ключевым словам в названиях
            keywords = features["keywords"][:5]
            
            for keyword in keywords:
                codes = db.query(HSCode).filter(
                    HSCode.title_ru.ilike(f"%{keyword}%")
                ).limit(10).all()
                
                for code in codes:
                    candidate_codes.append(code.code)
            
            # Поиск по материалу
            for material in features["material"]:
                codes = db.query(HSCode).filter(
                    HSCode.title_ru.ilike(f"%{material}%")
                ).limit(5).all()
                
                for code in codes:
                    candidate_codes.append(code.code)
            
            return list(set(candidate_codes))
            
        finally:
            db.close()
    
    def _classify_with_model(self, features: Dict[str, Any], candidate_codes: List[str], 
                           text: str, image_b64: str) -> Dict[str, Any]:
        """Основная классификация с помощью модели"""
        
        # Загружаем системный промпт
        prompt_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'ai', 'prompts', 'classify_ru.md')
        system_prompt = self._load_system_prompt(prompt_path)
        
        # Формируем контекст
        context = self._build_context(features, candidate_codes)
        
        # Формируем пользовательский запрос
        user_message = self._build_user_message(text, image_b64, context)
        
        # Вызов API
        response = self._call_anthropic_api(system_prompt, user_message)
        
        # Парсинг ответа
        return self._parse_response(response)
    
    def _load_system_prompt(self, prompt_path: str) -> str:
        """Загрузка системного промпта"""
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return "Вы эксперт по классификации товаров по ТН ВЭД. Определите код ТН ВЭД для товара."
    
    def _build_context(self, features: Dict[str, Any], candidate_codes: List[str]) -> str:
        """Построение контекста для модели"""
        context_parts = []
        
        if features["material"]:
            context_parts.append(f"Материал: {', '.join(features['material'])}")
        
        if features["purpose"]:
            context_parts.append(f"Назначение: {', '.join(features['purpose'])}")
        
        if features["completeness"]:
            context_parts.append(f"Комплектность: {', '.join(features['completeness'])}")
        
        if candidate_codes:
            context_parts.append(f"Кандидаты: {', '.join(candidate_codes[:10])}")
        
        return "\n".join(context_parts)
    
    def _build_user_message(self, text: str, image_b64: str, context: str) -> str:
        """Построение пользовательского сообщения"""
        message_parts = []
        
        if text:
            message_parts.append(f"Описание товара: {text}")
        
        if context:
            message_parts.append(f"Контекст: {context}")
        
        if image_b64:
            message_parts.append("Изображение товара приложено")
        
        return "\n\n".join(message_parts)
    
    def _call_anthropic_api(self, system_prompt: str, user_message: str) -> str:
        """Вызов Anthropic API"""
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        data = {
            "model": self.model,
            "max_tokens": 1000,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_message}
            ]
        }
        
        response = requests.post(
            f"{self.base_url}/messages",
            headers=headers,
            json=data
        )
        
        if response.status_code == 200:
            result = response.json()
            return result["content"][0]["text"]
        else:
            raise Exception(f"Anthropic API error: {response.status_code} - {response.text}")
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Парсинг ответа модели"""
        try:
            # Простой парсинг JSON-подобного ответа
            import json
            
            # Ищем JSON в ответе
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            
            # Если JSON не найден, пытаемся извлечь код
            code_match = re.search(r'\b\d{2}\.\d{2}\.\d{2}\.\d{2}\b', response)
            if code_match:
                return {
                    "hs_code": code_match.group(),
                    "confidence": 0.8,
                    "rationale": [response],
                    "alternatives": []
                }
            
            return {
                "hs_code": "0000.00.00.00",
                "confidence": 0.1,
                "rationale": [response],
                "alternatives": []
            }
            
        except Exception as e:
            logger.error(f"Ошибка парсинга ответа: {e}")
            return {
                "hs_code": "0000.00.00.00",
                "confidence": 0.1,
                "rationale": ["Ошибка парсинга ответа"],
                "alternatives": []
            }
    
    def _validate_and_enhance(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация и улучшение результата"""
        db = SessionLocal()
        try:
            hs_code = result.get("hs_code", "")
            
            # Проверяем существование кода
            existing_code = db.query(HSCode).filter(HSCode.code == hs_code).first()
            
            if existing_code:
                result["validated"] = True
                result["title_ru"] = existing_code.title_ru
                result["title_en"] = existing_code.title_en
            else:
                # Ищем ближайшие коды
                similar_codes = self._find_similar_codes(hs_code, db)
                if similar_codes:
                    result["alternatives"] = [
                        {
                            "code": code.code,
                            "title_ru": code.title_ru,
                            "confidence": 0.7
                        }
                        for code in similar_codes[:3]
                    ]
                    result["clarification_questions"] = [
                        "Уточните материал товара",
                        "Уточните назначение товара",
                        "Уточните комплектность"
                    ]
                else:
                    result["error"] = "Код не найден в базе данных"
            
            return result
            
        finally:
            db.close()
    
    def _find_similar_codes(self, hs_code: str, db) -> List[HSCode]:
        """Поиск похожих кодов"""
        similar_codes = []
        
        # Поиск по префиксам
        for prefix_length in [6, 4, 2]:
            if len(hs_code) > prefix_length:
                prefix = hs_code[:prefix_length]
                codes = db.query(HSCode).filter(
                    HSCode.code.like(f"{prefix}%")
                ).limit(3).all()
                similar_codes.extend(codes)
                if similar_codes:
                    break
        
        return similar_codes


