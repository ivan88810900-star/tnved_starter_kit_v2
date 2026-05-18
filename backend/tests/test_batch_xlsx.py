"""
Тесты для пакетной обработки Excel файлов
"""
import pytest
import pandas as pd
import tempfile
import os
from fastapi.testclient import TestClient


def test_batch_classify_xlsx_upload(client: TestClient, temp_excel_file):
    """Тест загрузки Excel файла для пакетной обработки"""
    with open(temp_excel_file, "rb") as f:
        files = {"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        response = client.post("/batch/classify_xlsx", files=files)
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем структуру ответа
    assert "status" in data
    assert "message" in data
    assert "results" in data or "download_url" in data


def test_batch_classify_xlsx_file_validation(client: TestClient):
    """Тест валидации файла для пакетной обработки"""
    # Тест с некорректным файлом
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as tmp_file:
        tmp_file.write(b"not an excel file")
        tmp_file.flush()
        
        with open(tmp_file.name, "rb") as f:
            files = {"file": ("test.txt", f, "text/plain")}
            response = client.post("/batch/classify_xlsx", files=files)
        
        os.unlink(tmp_file.name)
    
    # Должна быть ошибка валидации файла
    assert response.status_code in [400, 422]


def test_batch_classify_xlsx_empty_file(client: TestClient):
    """Тест обработки пустого Excel файла"""
    # Создаем пустой Excel файл
    df = pd.DataFrame()
    
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp_file:
        df.to_excel(tmp_file.name, index=False)
        
        with open(tmp_file.name, "rb") as f:
            files = {"file": ("empty.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            response = client.post("/batch/classify_xlsx", files=files)
        
        os.unlink(tmp_file.name)
    
    # Пустой файл должен обрабатываться корректно
    assert response.status_code in [200, 400]


def test_batch_classify_xlsx_correct_structure(client: TestClient):
    """Тест обработки Excel файла с правильной структурой"""
    # Создаем Excel файл с правильной структурой
    data = {
        'ID': [1, 2, 3],
        'Описание': [
            'Зеркало настенное из стекла',
            'Резиновые перчатки медицинские',
            'Мобильный телефон iPhone'
        ],
        'Характеристики': [
            'Размер 50x70 см, без рамы',
            'Одноразовые, латексные',
            '128 ГБ, черный цвет'
        ]
    }
    
    df = pd.DataFrame(data)
    
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp_file:
        df.to_excel(tmp_file.name, index=False)
        
        with open(tmp_file.name, "rb") as f:
            files = {"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            response = client.post("/batch/classify_xlsx", files=files)
        
        os.unlink(tmp_file.name)
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем структуру ответа
    assert "status" in data
    assert "message" in data


def test_batch_classify_xlsx_missing_columns(client: TestClient):
    """Тест обработки Excel файла с отсутствующими колонками"""
    # Создаем Excel файл без обязательных колонок
    data = {
        'Неправильная_колонка': [1, 2, 3],
        'Другая_колонка': ['товар1', 'товар2', 'товар3']
    }
    
    df = pd.DataFrame(data)
    
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp_file:
        df.to_excel(tmp_file.name, index=False)
        
        with open(tmp_file.name, "rb") as f:
            files = {"file": ("wrong_structure.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            response = client.post("/batch/classify_xlsx", files=files)
        
        os.unlink(tmp_file.name)
    
    # Должна быть ошибка валидации структуры
    assert response.status_code in [400, 422]


def test_batch_classify_xlsx_large_file(client: TestClient):
    """Тест обработки большого Excel файла"""
    # Создаем файл с большим количеством строк
    data = {
        'ID': list(range(1, 1001)),  # 1000 строк
        'Описание': [f'Товар номер {i}' for i in range(1, 1001)],
        'Характеристики': [f'Характеристики товара {i}' for i in range(1, 1001)]
    }
    
    df = pd.DataFrame(data)
    
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp_file:
        df.to_excel(tmp_file.name, index=False)
        
        with open(tmp_file.name, "rb") as f:
            files = {"file": ("large.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            response = client.post("/batch/classify_xlsx", files=files)
        
        os.unlink(tmp_file.name)
    
    # Большой файл должен обрабатываться или возвращать ошибку размера
    assert response.status_code in [200, 413, 422]


def test_batch_classify_xlsx_response_structure(client: TestClient, temp_excel_file):
    """Тест структуры ответа пакетной обработки"""
    with open(temp_excel_file, "rb") as f:
        files = {"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        response = client.post("/batch/classify_xlsx", files=files)
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем обязательные поля ответа
    required_fields = ["status", "message"]
    for field in required_fields:
        assert field in data
    
    # Проверяем типы данных
    assert isinstance(data["status"], str)
    assert isinstance(data["message"], str)
    
    # Проверяем возможные поля результата
    if "results" in data:
        assert isinstance(data["results"], list)
    if "download_url" in data:
        assert isinstance(data["download_url"], str)
    if "processed_count" in data:
        assert isinstance(data["processed_count"], int)


def test_batch_classify_xlsx_no_file(client: TestClient):
    """Тест запроса без файла"""
    response = client.post("/batch/classify_xlsx")
    
    # Должна быть ошибка валидации
    assert response.status_code in [400, 422]


def test_batch_classify_xlsx_wrong_content_type(client: TestClient):
    """Тест с неправильным Content-Type"""
    # Создаем Excel файл
    data = {'ID': [1], 'Описание': ['тест']}
    df = pd.DataFrame(data)
    
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp_file:
        df.to_excel(tmp_file.name, index=False)
        
        with open(tmp_file.name, "rb") as f:
            files = {"file": ("test.xlsx", f, "text/plain")}  # Неправильный Content-Type
            response = client.post("/batch/classify_xlsx", files=files)
        
        os.unlink(tmp_file.name)
    
    # Может быть ошибка валидации или успешная обработка
    assert response.status_code in [200, 400, 422]


def test_batch_classify_xlsx_round_trip(client: TestClient):
    """Тест полного цикла: загрузка -> обработка -> результат"""
    # Создаем тестовые данные
    test_data = {
        'ID': [1, 2, 3],
        'Описание': [
            'Зеркало настенное из стекла',
            'Резиновые перчатки медицинские', 
            'Мобильный телефон iPhone'
        ],
        'Характеристики': [
            'Размер 50x70 см',
            'Одноразовые',
            '128 ГБ'
        ]
    }
    
    df = pd.DataFrame(test_data)
    
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp_file:
        df.to_excel(tmp_file.name, index=False)
        
        # Загружаем файл
        with open(tmp_file.name, "rb") as f:
            files = {"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            response = client.post("/batch/classify_xlsx", files=files)
        
        os.unlink(tmp_file.name)
    
    assert response.status_code == 200
    data = response.json()
    
    # Проверяем, что обработка прошла успешно
    assert data["status"] in ["success", "completed", "processing"]
    
    # Если есть результаты, проверяем их структуру
    if "results" in data and isinstance(data["results"], list):
        for result in data["results"]:
            assert "id" in result or "ID" in result
            assert "description" in result or "Описание" in result
















