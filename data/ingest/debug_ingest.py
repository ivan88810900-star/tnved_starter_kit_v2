#!/usr/bin/env python3
"""
Отладочный скрипт для проверки ingest.py
"""
import os
import sys
import yaml
import logging

# Добавляем путь к backend для импорта моделей
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from app.db import SessionLocal, init_db
from app.models import HSCode, Note, DataSource, TariffRate, NTMMeasure, EcoRate

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_sources_config(config_path: str):
    """Загружает конфигурацию источников данных"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки конфигурации {config_path}: {e}")
        return {}

def validate_data_paths(sources):
    """Проверяет существование путей к данным"""
    missing_paths = []
    
    for source_name, source_config in sources.items():
        local_path = source_config.get('local_path', '')
        print(f"Проверяем источник: {source_name}")
        print(f"  local_path: {local_path}")
        print(f"  local_path существует: {os.path.exists(local_path) if local_path else 'Нет пути'}")
        
        if local_path and not os.path.exists(local_path):
            missing_paths.append(f"{source_name}: {local_path}")
        elif local_path:
            # Проверяем, что в директории есть файлы
            files = [f for f in os.listdir(local_path) if os.path.isfile(os.path.join(local_path, f))]
            print(f"  файлов в директории: {len(files)}")
            if not files:
                missing_paths.append(f"{source_name}: директория пуста - {local_path}")
    
    return missing_paths

def main():
    """Основная функция"""
    config_path = "../sources_updated.yml"
    
    print(f"Загружаем конфигурацию: {config_path}")
    print(f"Файл существует: {os.path.exists(config_path)}")
    
    # Загружаем конфигурацию
    sources = load_sources_config(config_path)
    print(f"Конфигурация загружена: {sources is not None}")
    print(f"Ключи в конфигурации: {list(sources.keys())}")
    
    if 'datasets' in sources:
        datasets = sources['datasets']
        print(f"Наборы данных: {list(datasets.keys())}")
        
        # Фильтруем только tariff_cet
        only_sources = ['tariff_cet']
        filtered_sources = {k: v for k, v in datasets.items() if k in only_sources}
        print(f"Отфильтрованные источники: {list(filtered_sources.keys())}")
        
        if filtered_sources:
            print("Проверяем пути к данным...")
            missing_paths = validate_data_paths(filtered_sources)
            
            if missing_paths:
                print("❌ Найдены отсутствующие пути:")
                for path in missing_paths:
                    print(f"  - {path}")
            else:
                print("✅ Все пути к данным найдены")
        else:
            print("❌ Нет источников для обработки")
    else:
        print("❌ datasets не найден в конфигурации")

if __name__ == "__main__":
    main()
















