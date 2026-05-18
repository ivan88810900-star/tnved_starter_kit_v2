#!/usr/bin/env python3
"""
Пример использования fetch_tariff_eec.py
"""
import sys
from pathlib import Path

# Добавляем текущую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from fetch_tariff_eec import TariffEECFetcher


def example_basic_usage():
    """Базовое использование скрипта"""
    print("=== Базовое использование ===")
    
    fetcher = TariffEECFetcher()
    
    # Создаем каталоги
    fetcher.setup_directories()
    print("✅ Каталоги созданы")
    
    # Загружаем страницу (симуляция)
    print("🌐 Загружаем страницу...")
    # В реальном использовании здесь будет HTTP запрос
    
    # Симулируем HTML с PDF ссылками
    mock_html = """
    <html>
    <body>
        <a href="documents/tariff_2025.pdf">Тариф 2025</a>
        <a href="documents/rates_2025.pdf">Ставки 2025</a>
        <a href="documents/amendments_2025.pdf">Изменения 2025</a>
    </body>
    </html>
    """
    
    # Ищем PDF ссылки
    pdf_urls = fetcher.find_pdf_links(mock_html.encode())
    print(f"📄 Найдено {len(pdf_urls)} PDF файлов:")
    for i, url in enumerate(pdf_urls, 1):
        print(f"  {i}. {url}")


def example_custom_configuration():
    """Пользовательская конфигурация"""
    print("\n=== Пользовательская конфигурация ===")
    
    # Создаем fetcher с пользовательскими параметрами
    custom_url = "https://eec.eaeunion.org/custom-page/"
    fetcher = TariffEECFetcher(custom_url)
    fetcher.version = "2025-02-01"
    
    print(f"🌐 Базовый URL: {fetcher.base_url}")
    print(f"📅 Версия: {fetcher.version}")
    print(f"📁 Каталог: {fetcher.download_dir}")
    
    # Создаем каталог
    fetcher.setup_directories()
    print("✅ Пользовательский каталог создан")


def example_error_handling():
    """Обработка ошибок"""
    print("\n=== Обработка ошибок ===")
    
    fetcher = TariffEECFetcher()
    
    # Тест обработки несуществующего файла
    print("🧪 Тест обработки несуществующего файла:")
    non_existent_file = Path("non_existent_file.txt")
    try:
        sha256 = fetcher.calculate_sha256(non_existent_file)
        print("❌ Ошибка: файл не должен существовать")
    except FileNotFoundError:
        print("✅ Корректно обработана ошибка отсутствия файла")
    except Exception as e:
        print(f"⚠️ Неожиданная ошибка: {e}")
    
    # Тест обработки несуществующей конфигурации
    print("\n🧪 Тест обработки несуществующей конфигурации:")
    fetcher.sources_file = Path("non_existent_sources.yml")
    config = fetcher.load_sources_config()
    
    if config and 'allowed_domains' in config:
        print("✅ Создана новая конфигурация")
    else:
        print("❌ Ошибка создания конфигурации")


def example_domain_validation():
    """Валидация доменов"""
    print("\n=== Валидация доменов ===")
    
    fetcher = TariffEECFetcher()
    
    # Устанавливаем разрешенные домены
    fetcher.config = {
        'allowed_domains': [
            'eec.eaeunion.org',
            'www.eurasiancommission.org',
            'customs.gov.ru'
        ]
    }
    
    # Тест разрешенных доменов
    allowed_urls = [
        "https://eec.eaeunion.org/documents/tariff.pdf",
        "https://www.eurasiancommission.org/data/rates.pdf",
        "https://customs.gov.ru/files/tariff.pdf"
    ]
    
    print("✅ Разрешенные домены:")
    for url in allowed_urls:
        is_allowed = fetcher.is_domain_allowed(url)
        status = "✅" if is_allowed else "❌"
        print(f"  {status} {url}")
    
    # Тест запрещенных доменов
    forbidden_urls = [
        "https://malicious-site.com/trojan.pdf",
        "https://fake-eec.org/documents.pdf",
        "https://suspicious-domain.net/data.pdf"
    ]
    
    print("\n❌ Запрещенные домены:")
    for url in forbidden_urls:
        is_allowed = fetcher.is_domain_allowed(url)
        status = "✅" if is_allowed else "❌"
        print(f"  {status} {url}")


def example_file_operations():
    """Операции с файлами"""
    print("\n=== Операции с файлами ===")
    
    fetcher = TariffEECFetcher()
    fetcher.setup_directories()
    
    # Создаем тестовый файл
    test_file = fetcher.download_dir / "test_document.pdf"
    test_content = b"PDF test content for SHA256 calculation"
    test_file.write_bytes(test_content)
    
    try:
        # Тест расчета SHA256
        print("🧪 Тест расчета SHA256:")
        sha256 = fetcher.calculate_sha256(test_file)
        print(f"  SHA256: {sha256}")
        print(f"  Длина: {len(sha256)} символов")
        print(f"  Формат: {'✅' if sha256.isalnum() else '❌'}")
        
        # Тест размера файла
        print("\n🧪 Тест размера файла:")
        file_size = test_file.stat().st_size
        expected_size = len(test_content)
        print(f"  Размер файла: {file_size} байт")
        print(f"  Ожидаемый размер: {expected_size} байт")
        print(f"  Совпадение: {'✅' if file_size == expected_size else '❌'}")
        
        # Тест существования файла
        print("\n🧪 Тест существования файла:")
        exists = test_file.exists()
        print(f"  Файл существует: {'✅' if exists else '❌'}")
        
    finally:
        # Очищаем тестовый файл
        test_file.unlink(missing_ok=True)
        print("🧹 Тестовый файл удален")


def example_sources_config():
    """Работа с конфигурацией sources.yml"""
    print("\n=== Работа с конфигурацией ===")
    
    fetcher = TariffEECFetcher()
    
    # Создаем тестовую конфигурацию
    test_config = {
        'allowed_domains': [
            'eec.eaeunion.org',
            'www.eurasiancommission.org',
            'customs.gov.ru'
        ],
        'datasets': {
            'test_dataset': {
                'name': 'Тестовый набор данных',
                'authority': 'Тестовая организация',
                'version': '2025-01-01',
                'file_type': 'PDF',
                'urls': ['https://example.com/test.pdf'],
                'save_as': ['test.pdf'],
                'checksum': ['abc123def456']
            }
        }
    }
    
    # Сохраняем тестовую конфигурацию
    import yaml
    test_sources_file = Path("test_sources.yml")
    with open(test_sources_file, 'w', encoding='utf-8') as f:
        yaml.safe_dump(test_config, f, default_flow_style=False, allow_unicode=True)
    
    # Временно заменяем путь к конфигурации
    original_sources_file = fetcher.sources_file
    fetcher.sources_file = test_sources_file
    
    try:
        # Тест загрузки конфигурации
        print("🧪 Тест загрузки конфигурации:")
        config = fetcher.load_sources_config()
        if config and 'test_dataset' in config.get('datasets', {}):
            print("  ✅ Конфигурация загружена корректно")
        else:
            print("  ❌ Ошибка загрузки конфигурации")
        
        # Тест сохранения конфигурации
        print("\n🧪 Тест сохранения конфигурации:")
        success = fetcher.save_sources_config(config)
        print(f"  Результат: {'✅' if success else '❌'}")
        
        # Тест обновления конфигурации
        print("\n🧪 Тест обновления конфигурации:")
        mock_downloaded_files = [
            {
                'url': 'https://eec.eaeunion.org/documents/tariff.pdf',
                'filename': 'tariff.pdf',
                'size': 1024000,
                'sha256': 'a1b2c3d4e5f6789abcdef0123456789abcdef0123456789abcdef0123456789'
            }
        ]
        
        success = fetcher.update_sources_config(mock_downloaded_files)
        print(f"  Результат: {'✅' if success else '❌'}")
        
    finally:
        # Восстанавливаем оригинальный путь
        fetcher.sources_file = original_sources_file
        # Удаляем тестовый файл
        test_sources_file.unlink(missing_ok=True)
        print("🧹 Тестовая конфигурация удалена")


def main():
    """Главная функция с примерами"""
    print("🚀 Примеры использования fetch_tariff_eec.py")
    print("=" * 60)
    
    # Запуск примеров
    example_basic_usage()
    example_custom_configuration()
    example_error_handling()
    example_domain_validation()
    example_file_operations()
    example_sources_config()
    
    print("\n" + "=" * 60)
    print("✅ Все примеры выполнены!")
    print("\nДля реального использования:")
    print("1. Установите зависимости: pip install requests beautifulsoup4 pyyaml")
    print("2. Запустите: python data/ingest/fetch_tariff_eec.py")
    print("3. Проверьте результат: ls -la data/raw/tariff_cet/2025-01-01/")


if __name__ == "__main__":
    main()
















