#!/usr/bin/env python3
"""
Тест регулярных выражений для кодов ТН ВЭД
"""
import re

def test_regex_patterns():
    """Тестирует различные регулярные выражения"""
    print("🧪 Тестирование регулярных выражений для кодов ТН ВЭД")
    
    test_lines = [
        "1401 10 000 0 – бамбук – 9",
        "1401 20 000 0 – ротанг – 13",
        "1401 90 000 0 – прочие – 13",
        "1404 20 000 0 – хлопковый линт – 5",
        "1404 90 000 1 – – материалы растительного – 13",
        "1404 90 000 8 – – прочие – 871С)",
    ]
    
    patterns = [
        (r'(\d{4}\s+\d{2}\s+\d{3}\s+\d{1})', "4+2+3+1 (строгий)"),
        (r'(\d{4}\s*\d{2}\s*\d{3}\s*\d{1})', "4+2+3+1 (гибкий)"),
        (r'(\d{4}\s+\d{2}\s+\d{2}\s+\d{2})', "4+2+2+2 (строгий)"),
        (r'(\d{4}\s*\d{2}\s*\d{2}\s*\d{2})', "4+2+2+2 (гибкий)"),
        (r'(\d{4}\s+\d{2}\s+\d{3}\s+\d{1})', "4+2+3+1 (очень строгий)"),
        (r'(\d{4}\s*\d{2}\s*\d{3}\s*\d{1})', "4+2+3+1 (очень гибкий)"),
    ]
    
    for line in test_lines:
        print(f"\n📝 Тест строки: '{line}'")
        
        for pattern, description in patterns:
            matches = re.findall(pattern, line)
            status = "✅" if matches else "❌"
            print(f"  {status} {description}: {matches}")
            
            if matches:
                # Тестируем нормализацию
                for match in matches:
                    normalized = normalize_hs_code(match)
                    print(f"    Нормализованный: {match} -> {normalized}")

def normalize_hs_code(code: str) -> str:
    """Нормализует код ТН ВЭД до 10 цифр"""
    if not code:
        return None
    
    # Убираем все пробелы, точки, дефисы
    cleaned = re.sub(r'[\s\.\-]', '', code)
    
    # Оставляем только цифры
    digits_only = re.sub(r'[^\d]', '', cleaned)
    
    # Проверяем, что код содержит ровно 10 цифр
    if len(digits_only) == 10 and digits_only.isdigit():
        return digits_only
    
    return None

def main():
    """Главная функция"""
    print("🚀 Тест регулярных выражений")
    print("=" * 60)
    
    test_regex_patterns()
    
    print("\n" + "=" * 60)
    print("✅ Тест завершен")

if __name__ == "__main__":
    main()
