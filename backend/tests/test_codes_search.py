"""
Тесты для эндпоинта поиска кодов /codes/search
"""
import pytest
from fastapi.testclient import TestClient


def test_search_by_exact_code(client: TestClient, sample_hs_codes):
    """Тест поиска по точному коду"""
    response = client.get("/codes/search?q=7009.10.0009")
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем, что вернулся массив
    assert isinstance(data, list)
    assert len(data) > 0
    
    # Проверяем структуру первого элемента
    first_result = data[0]
    assert "code" in first_result
    assert "title_ru" in first_result
    # Коды должны быть без точек
    assert first_result["code"] == "7009100009"


def test_search_by_partial_code(client: TestClient, sample_hs_codes):
    """Тест поиска по частичному коду"""
    response = client.get("/codes/search?q=7009")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    assert len(data) > 0
    
    # Проверяем, что все результаты содержат искомый код
    for result in data:
        assert "7009" in result["code"]


def test_search_by_russian_title(client: TestClient, sample_hs_codes):
    """Тест поиска по русскому названию"""
    response = client.get("/codes/search?q=зеркала")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    assert len(data) > 0
    
    # Проверяем, что в результатах есть зеркала
    found_mirrors = False
    for result in data:
        if "зеркал" in result["title_ru"].lower():
            found_mirrors = True
            break
    assert found_mirrors


def test_search_by_english_title(client: TestClient, sample_hs_codes):
    """Тест поиска по английскому названию"""
    response = client.get("/codes/search?q=glass")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    assert len(data) > 0


def test_search_by_material(client: TestClient, sample_hs_codes):
    """Тест поиска по материалу"""
    response = client.get("/codes/search?q=резина")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    assert len(data) > 0
    
    # Проверяем, что в результатах есть резиновые изделия
    found_rubber = False
    for result in data:
        if "резин" in result["title_ru"].lower():
            found_rubber = True
            break
    assert found_rubber


def test_search_empty_query(client: TestClient, sample_hs_codes):
    """Тест поиска с пустым запросом"""
    response = client.get("/codes/search?q=")
    
    assert response.status_code == 200
    data = response.json()
    
    # Пустой запрос должен возвращать пустой массив или ограниченный набор
    assert isinstance(data, list)


def test_search_nonexistent_code(client: TestClient, sample_hs_codes):
    """Тест поиска несуществующего кода"""
    response = client.get("/codes/search?q=9999.99.9999")
    
    assert response.status_code == 200
    data = response.json()
    
    # Несуществующий код должен возвращать пустой массив
    assert isinstance(data, list)
    assert len(data) == 0


def test_search_case_insensitive(client: TestClient, sample_hs_codes):
    """Тест поиска без учета регистра"""
    response_lower = client.get("/codes/search?q=зеркала")
    response_upper = client.get("/codes/search?q=ЗЕРКАЛА")
    
    assert response_lower.status_code == 200
    assert response_upper.status_code == 200
    
    data_lower = response_lower.json()
    data_upper = response_upper.json()
    
    # Результаты должны быть одинаковыми
    assert len(data_lower) == len(data_upper)


def test_search_limit_results(client: TestClient, sample_hs_codes):
    """Тест ограничения количества результатов"""
    response = client.get("/codes/search?q=изделия")
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем, что количество результатов не превышает лимит
    assert len(data) <= 50


def test_search_result_structure(client: TestClient, sample_hs_codes):
    """Тест структуры результатов поиска"""
    response = client.get("/codes/search?q=7009")
    
    assert response.status_code == 200
    data = response.json()
    
    assert len(data) > 0
    
    # Проверяем структуру каждого результата
    for result in data:
        assert "code" in result
        assert "title_ru" in result
        assert "chapter" in result or result["chapter"] is None
        assert "heading" in result or result["heading"] is None
        assert "subheading" in result or result["subheading"] is None
        
        # Проверяем типы данных
        assert isinstance(result["code"], str)
        assert isinstance(result["title_ru"], str)


def test_search_special_characters(client: TestClient, sample_hs_codes):
    """Тест поиска со специальными символами"""
    response = client.get("/codes/search?q=телефон%20мобильный")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    # Должны найтись мобильные телефоны
    found_phones = any("телефон" in result["title_ru"].lower() for result in data)
    assert found_phones








