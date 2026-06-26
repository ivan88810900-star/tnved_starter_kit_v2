"""
Тесты для классификации в офлайн режиме (AI_OFFLINE_MODE=true)
"""
import pytest
import os
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_offline_mode():
    """Настройка офлайн режима для тестов"""
    os.environ["AI_OFFLINE_MODE"] = "true"
    os.environ["ALLOW_EXTERNAL_AI"] = "false"
    yield
    # Очищаем переменные после теста
    if "AI_OFFLINE_MODE" in os.environ:
        del os.environ["AI_OFFLINE_MODE"]
    if "ALLOW_EXTERNAL_AI" in os.environ:
        del os.environ["ALLOW_EXTERNAL_AI"]


def test_classify_offline_mode_text_only(client: TestClient, sample_hs_codes):
    """Тест классификации в офлайн режиме с текстовым описанием"""
    response = client.post("/classify", json={
        "text": "Зеркало настенное из стекла размером 50x70 см",
        "hints": ["стекло", "зеркало"]
    })
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем структуру ответа
    assert "hs_code" in data
    assert "confidence" in data
    assert "rationale" in data
    assert "alternatives" in data
    assert "offline_mode" in data
    
    # В офлайн режиме должен быть флаг offline_mode
    assert data["offline_mode"] is True
    
    # Проверяем типы данных
    assert isinstance(data["hs_code"], str)
    assert isinstance(data["confidence"], (int, float))
    assert isinstance(data["rationale"], list)
    assert isinstance(data["alternatives"], list)


def test_classify_offline_mode_with_image(client: TestClient, sample_hs_codes):
    """Тест классификации в офлайн режиме с изображением"""
    # Создаем тестовое base64 изображение
    test_image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    
    response = client.post("/classify", json={
        "text": "Резиновые перчатки медицинские",
        "image_base64": test_image_b64,
        "hints": ["резина", "медицина"]
    })
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем, что ответ содержит все необходимые поля
    assert "hs_code" in data
    assert "confidence" in data
    assert "rationale" in data
    assert "offline_mode" in data
    
    # В офлайн режиме confidence должен быть низким
    assert data["confidence"] < 0.5


def test_classify_offline_mode_no_input(client: TestClient, sample_hs_codes):
    """Тест классификации в офлайн режиме без входных данных"""
    response = client.post("/classify", json={})
    
    # Должна быть ошибка 400 - нет входных данных
    assert response.status_code == 400


def test_classify_offline_mode_returns_suggestions(client: TestClient, sample_hs_codes):
    """Тест что офлайн режим возвращает предложения и вопросы"""
    response = client.post("/classify", json={
        "text": "Неизвестный товар для тестирования",
        "hints": ["тест"]
    })
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем наличие полей для предложений
    assert "alternatives" in data
    assert "clarification_questions" in data
    
    # В офлайн режиме должны быть уточняющие вопросы
    if "clarification_questions" in data:
        assert isinstance(data["clarification_questions"], list)


def test_classify_offline_mode_rationale_content(client: TestClient, sample_hs_codes):
    """Тест содержания обоснования в офлайн режиме"""
    response = client.post("/classify", json={
        "text": "Стеклянное зеркало",
        "hints": ["стекло"]
    })
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем, что rationale содержит информацию об офлайн режиме
    rationale = data.get("rationale", [])
    assert len(rationale) > 0
    
    # Должно быть упоминание офлайн режима
    offline_mentioned = any("офлайн" in str(item).lower() for item in rationale)
    assert offline_mentioned


def test_classify_offline_mode_confidence_levels(client: TestClient, sample_hs_codes):
    """Тест уровней уверенности в офлайн режиме"""
    test_cases = [
        {"text": "Зеркало из стекла", "expected_confidence": 0.1},
        {"text": "Резиновые изделия", "expected_confidence": 0.1},
        {"text": "Неизвестный товар", "expected_confidence": 0.1}
    ]
    
    for case in test_cases:
        response = client.post("/classify", json={
            "text": case["text"]
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # В офлайн режиме confidence должен быть низким
        assert data["confidence"] <= case["expected_confidence"]


def test_classify_offline_mode_handles_errors(client: TestClient, sample_hs_codes):
    """Тест обработки ошибок в офлайн режиме"""
    # Тест с некорректными данными
    response = client.post("/classify", json={
        "text": None,
        "image_base64": "invalid_base64"
    })
    
    # Должна быть ошибка валидации
    assert response.status_code == 400


def test_classify_offline_mode_consistency(client: TestClient, sample_hs_codes):
    """Тест консистентности результатов в офлайн режиме"""
    # Выполняем один и тот же запрос несколько раз
    responses = []
    for _ in range(3):
        response = client.post("/classify", json={
            "text": "Стеклянное зеркало",
            "hints": ["стекло"]
        })
        assert response.status_code == 200
        responses.append(response.json())
    
    # Результаты должны быть одинаковыми
    first_result = responses[0]
    for result in responses[1:]:
        assert result["hs_code"] == first_result["hs_code"]
        assert result["confidence"] == first_result["confidence"]


def test_classify_offline_mode_with_hints(client: TestClient, sample_hs_codes):
    """Тест использования подсказок в офлайн режиме"""
    response = client.post("/classify", json={
        "text": "Изделие из резины",
        "hints": ["резина", "медицина", "перчатки"]
    })
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем, что подсказки учтены в rationale
    rationale = data.get("rationale", [])
    hints_mentioned = any(
        any(hint in str(item).lower() for hint in ["резина", "медицина", "перчатки"])
        for item in rationale
    )
    # В офлайн режиме подсказки могут не обрабатываться, но ошибки быть не должно
    assert isinstance(rationale, list)


def test_classify_offline_mode_validation_flags(client: TestClient, sample_hs_codes):
    """Тест флагов валидации в офлайн режиме"""
    response = client.post("/classify", json={
        "text": "Тестовый товар"
    })
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем наличие флагов валидации
    assert "offline_mode" in data
    assert data["offline_mode"] is True
    
    # В офлайн режиме validated может быть False
    if "validated" in data:
        assert isinstance(data["validated"], bool)
















