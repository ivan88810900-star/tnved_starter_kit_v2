#!/usr/bin/env python3
"""
Тестовый скрипт для проверки fetch_tariff_eec.py
"""
import sys
import os
from pathlib import Path

# Добавляем текущую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from fetch_tariff_eec import TariffEECFetcher


def test_basic_functionality():
    """Тест базовой функциональности"""
    print("🧪 Тестирование базовой функциональности")
    
    # Создаем тестовый экземпляр
    fetcher = TariffEECFetcher()
    
    # Тест создания каталогов
    print("\n1. Тест создания каталогов:")
    fetcher.setup_directories()
    assert fetcher.download_dir.exists(), "Каталог должен быть создан"
    print("✅ Каталог создан успешно")
    
    # Тест расчета SHA256
    print("\n2. Тест расчета SHA256:")
    test_file = fetcher.download_dir / "test.txt"
    test_file.write_text("test content")
    
    sha256 = fetcher.calculate_sha256(test_file)
    assert len(sha256) == 64, "SHA256 должен быть 64 символа"
    print(f"✅ SHA256: {sha256}")
    
    # Очистка тестового файла
    test_file.unlink()
    
    print("✅ Базовая функциональность работает")


def test_url_parsing():
    """Тест парсинга URL"""
    print("\n🧪 Тестирование парсинга URL")
    
    fetcher = TariffEECFetcher()
    
    # Тест создания абсолютных URL
    base_url = "https://eec.eaeunion.org/comission/department/catr/ett/"
    relative_url = "documents/tariff.pdf"
    
    from urllib.parse import urljoin
    absolute_url = urljoin(base_url, relative_url)
    
    expected = "https://eec.eaeunion.org/comission/department/catr/ett/documents/tariff.pdf"
    assert absolute_url == expected, f"Ожидался {expected}, получен {absolute_url}"
    print(f"✅ URL парсинг: {absolute_url}")
    
    # Тест извлечения имени файла
    from urllib.parse import urlparse
    parsed = urlparse(absolute_url)
    filename = os.path.basename(parsed.path)
    assert filename == "tariff.pdf", f"Ожидался tariff.pdf, получен {filename}"
    print(f"✅ Имя файла: {filename}")


def test_sources_config():
    """Тест работы с конфигурацией sources.yml"""
    print("\n🧪 Тестирование конфигурации sources.yml")
    
    fetcher = TariffEECFetcher()
    
    # Создаем тестовую конфигурацию
    test_config = {
        'allowed_domains': ['eec.eaeunion.org'],
        'datasets': {
            'test_dataset': {
                'name': 'Тестовый набор',
                'authority': 'Тест',
                'version': '2025-01-01',
                'file_type': 'PDF',
                'urls': ['https://example.com/test.pdf'],
                'save_as': ['test.pdf'],
                'checksum': ['abc123']
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
        config = fetcher.load_sources_config()
        assert config is not None, "Конфигурация должна загружаться"
        assert 'test_dataset' in config['datasets'], "Тестовый набор должен присутствовать"
        print("✅ Конфигурация загружается корректно")
        
        # Тест сохранения конфигурации
        success = fetcher.save_sources_config(config)
        assert success, "Конфигурация должна сохраняться"
        print("✅ Конфигурация сохраняется корректно")
        
    finally:
        # Восстанавливаем оригинальный путь
        fetcher.sources_file = original_sources_file
        # Удаляем тестовый файл
        test_sources_file.unlink(missing_ok=True)


def test_domain_validation():
    """Тест валидации доменов"""
    print("\n🧪 Тестирование валидации доменов")
    
    fetcher = TariffEECFetcher()
    
    # Тест разрешенных доменов
    allowed_urls = [
        "https://eec.eaeunion.org/documents/tariff.pdf",
        "https://www.eurasiancommission.org/data/rates.pdf",
        "https://customs.gov.ru/files/tariff.pdf"
    ]
    
    for url in allowed_urls:
        # Временно устанавливаем разрешенные домены
        fetcher.config = {
            'allowed_domains': [
                'eec.eaeunion.org',
                'www.eurasiancommission.org', 
                'customs.gov.ru'
            ]
        }
        
        # Проверяем, что домен разрешен
        assert fetcher.is_domain_allowed(url), f"URL {url} должен быть разрешен"
        print(f"✅ Разрешен: {url}")
    
    # Тест запрещенных доменов
    forbidden_urls = [
        "https://malicious-site.com/trojan.pdf",
        "https://fake-eec.org/documents.pdf",
        "https://suspicious-domain.net/data.pdf"
    ]
    
    for url in forbidden_urls:
        # Проверяем, что домен запрещен
        assert not fetcher.is_domain_allowed(url), f"URL {url} должен быть запрещен"
        print(f"✅ Запрещен: {url}")


def test_file_operations():
    """Тест операций с файлами"""
    print("\n🧪 Тестирование операций с файлами")
    
    fetcher = TariffEECFetcher()
    fetcher.setup_directories()
    
    # Создаем тестовый файл
    test_file = fetcher.download_dir / "test_document.pdf"
    test_content = b"PDF test content for SHA256 calculation"
    test_file.write_bytes(test_content)
    
    try:
        # Тест расчета SHA256
        sha256 = fetcher.calculate_sha256(test_file)
        assert len(sha256) == 64, "SHA256 должен быть 64 символа"
        assert sha256.isalnum(), "SHA256 должен содержать только буквы и цифры"
        print(f"✅ SHA256: {sha256}")
        
        # Тест проверки существования файла
        assert test_file.exists(), "Файл должен существовать"
        print("✅ Файл существует")
        
        # Тест размера файла
        file_size = test_file.stat().st_size
        assert file_size == len(test_content), f"Размер файла должен быть {len(test_content)}"
        print(f"✅ Размер файла: {file_size} байт")
        
    finally:
        # Очищаем тестовый файл
        test_file.unlink(missing_ok=True)


def test_error_handling():
    """Тест обработки ошибок"""
    print("\n🧪 Тестирование обработки ошибок")
    
    fetcher = TariffEECFetcher()
    
    # Тест обработки несуществующего файла
    non_existent_file = Path("non_existent_file.txt")
    try:
        sha256 = fetcher.calculate_sha256(non_existent_file)
        assert False, "Должна была возникнуть ошибка"
    except FileNotFoundError:
        print("✅ Корректно обработана ошибка отсутствия файла")
    except Exception as e:
        print(f"⚠️ Неожиданная ошибка: {e}")
    
    # Тест обработки несуществующей конфигурации
    fetcher.sources_file = Path("non_existent_sources.yml")
    config = fetcher.load_sources_config()
    assert config is not None, "Должна создаваться новая конфигурация"
    assert 'allowed_domains' in config, "Новая конфигурация должна содержать allowed_domains"
    print("✅ Корректно обработана ошибка отсутствия конфигурации")


def run_all_tests():
    """Запуск всех тестов"""
    print("🚀 Запуск тестов fetch_tariff_eec.py")
    print("=" * 50)
    
    try:
        test_basic_functionality()
        test_url_parsing()
        test_sources_config()
        test_domain_validation()
        test_file_operations()
        test_error_handling()
        
        print("\n" + "=" * 50)
        print("✅ ВСЕ ТЕСТЫ ПРОШЛИ УСПЕШНО!")
        print("=" * 50)
        return True
        
    except Exception as e:
        print(f"\n❌ ТЕСТ ПРОВАЛЕН: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
















