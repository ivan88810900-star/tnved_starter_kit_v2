"""
Тесты для эндпоинта /health
"""
import pytest
from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient):
    """Тест проверки здоровья API"""
    response = client.get("/health")
    
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_health_endpoint_structure(client: TestClient):
    """Тест структуры ответа health endpoint"""
    response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем наличие ключа "ok"
    assert "ok" in data
    assert data["ok"] is True
    
    # Проверяем тип данных
    assert isinstance(data["ok"], bool)


def test_health_endpoint_headers(client: TestClient):
    """Тест заголовков ответа health endpoint"""
    response = client.get("/health")
    
    assert response.status_code == 200
    
    # Проверяем Content-Type
    assert response.headers["content-type"] == "application/json"
    
    # Проверяем наличие стандартных заголовков
    assert "content-length" in response.headers


def test_health_endpoint_multiple_requests(client: TestClient):
    """Тест множественных запросов к health endpoint"""
    # Выполняем несколько запросов подряд
    for _ in range(5):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True}


def test_health_endpoint_with_different_methods(client: TestClient):
    """Тест health endpoint с разными HTTP методами"""
    # GET должен работать
    response = client.get("/health")
    assert response.status_code == 200
    
    # POST должен возвращать 405 Method Not Allowed
    response = client.post("/health")
    assert response.status_code == 405
    
    # PUT должен возвращать 405 Method Not Allowed
    response = client.put("/health")
    assert response.status_code == 405
















