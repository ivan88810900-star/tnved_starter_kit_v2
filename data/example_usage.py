#!/usr/bin/env python3
"""
Пример использования скрипта загрузки данных
"""
import sys
from pathlib import Path

# Добавляем текущую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from download_sources import DataDownloader


def example_basic_usage():
    """Базовое использование"""
    print("=== Базовое использование ===")
    
    downloader = DataDownloader()
    
    # Показать список наборов данных
    print("\n1. Список доступных наборов:")
    downloader.list_datasets()
    
    # Загрузить все данные
    print("\n2. Загрузка всех данных:")
    success = downloader.download_all()
    
    if success:
        print("✅ Все данные загружены успешно!")
    else:
        print("⚠️ Некоторые данные не удалось загрузить")


def example_specific_dataset():
    """Загрузка конкретного набора данных"""
    print("\n=== Загрузка конкретного набора ===")
    
    downloader = DataDownloader()
    
    # Загрузить только дерево ТН ВЭД
    datasets = downloader.config.get('datasets', {})
    if 'tnved_tree' in datasets:
        print("Загружаем дерево ТН ВЭД...")
        success = downloader.download_dataset('tnved_tree', datasets['tnved_tree'])
        if success:
            downloader.save_updated_config()
            print("✅ Дерево ТН ВЭД загружено!")
        else:
            print("❌ Ошибка загрузки дерева ТН ВЭД")


def example_verification():
    """Проверка целостности файлов"""
    print("\n=== Проверка целостности ===")
    
    downloader = DataDownloader()
    
    # Проверить целостность всех файлов
    downloader.verify_checksums()


def example_custom_config():
    """Использование с пользовательской конфигурацией"""
    print("\n=== Пользовательская конфигурация ===")
    
    # Создать тестовую конфигурацию
    test_config = {
        'allowed_domains': ['example.com'],
        'datasets': {
            'test_dataset': {
                'name': 'Тестовый набор',
                'authority': 'Тест',
                'version': '2025-01-01',
                'urls': ['https://example.com/test.xlsx'],
                'file_type': 'XLSX',
                'save_as': 'test_2025-01-01.xlsx',
                'checksum': ''
            }
        }
    }
    
    # Сохранить тестовую конфигурацию
    import yaml
    with open('test_sources.yml', 'w', encoding='utf-8') as f:
        yaml.dump(test_config, f, default_flow_style=False, allow_unicode=True)
    
    # Использовать тестовую конфигурацию
    downloader = DataDownloader('test_sources.yml')
    print("Тестовая конфигурация создана: test_sources.yml")
    
    # Очистить тестовый файл
    Path('test_sources.yml').unlink(missing_ok=True)


def example_error_handling():
    """Обработка ошибок"""
    print("\n=== Обработка ошибок ===")
    
    try:
        # Попытка загрузить с несуществующей конфигурацией
        downloader = DataDownloader('nonexistent.yml')
    except SystemExit:
        print("✅ Корректно обработана ошибка отсутствия файла")
    
    try:
        # Попытка загрузить с неразрешенного домена
        downloader = DataDownloader()
        
        # Создать тестовый URL с неразрешенного домена
        test_url = "https://untrusted-site.com/data.xlsx"
        is_allowed = downloader.is_domain_allowed(test_url)
        
        if not is_allowed:
            print("✅ Корректно заблокирован неразрешенный домен")
        
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")


def main():
    """Главная функция с примерами"""
    print("🚀 Примеры использования скрипта загрузки данных TN VED Pro")
    print("=" * 60)
    
    # Запуск примеров
    example_basic_usage()
    example_specific_dataset()
    example_verification()
    example_custom_config()
    example_error_handling()
    
    print("\n" + "=" * 60)
    print("✅ Все примеры выполнены!")
    print("\nДля реального использования:")
    print("1. Отредактируйте data/sources.yml с актуальными URL")
    print("2. Запустите: python data/download_sources.py")
    print("3. Проверьте целостность: python data/download_sources.py --verify")


if __name__ == "__main__":
    main()
















