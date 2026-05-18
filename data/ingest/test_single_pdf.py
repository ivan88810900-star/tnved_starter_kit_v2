#!/usr/bin/env python3
"""
Тест парсинга одного PDF файла
"""
import os
import sys
import pdfplumber
import re

# Добавляем путь к backend для импорта моделей
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from parsers.tariff_pdf import extract_tariff_data_from_text, normalize_hs_code

def test_single_pdf():
    """Тестирует парсинг одного PDF файла"""
    pdf_path = "data/raw/tariff_cet/2025-01-01/ru.14_2022_10.10.2022.pdf"
    
    print(f"📄 Тестирование файла: {os.path.basename(pdf_path)}")
    
    if not os.path.exists(pdf_path):
        print(f"❌ Файл не найден: {pdf_path}")
        return
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                print(f"\n📄 Страница {page_num + 1}:")
                
                # Извлекаем текст
                text = page.extract_text()
                if text:
                    print(f"📝 Длина текста: {len(text)} символов")
                    
                    # Показываем первые 20 строк
                    lines = text.split('\n')
                    print("📋 Первые 20 строк:")
                    for i, line in enumerate(lines[:20]):
                        if line.strip():
                            print(f"  {i+1:2d}: {line.strip()}")
                    
                    # Тестируем парсер
                    print(f"\n🔍 Тестирование парсера:")
                    records = extract_tariff_data_from_text(text)
                    print(f"📊 Найдено записей: {len(records)}")
                    
                    for i, record in enumerate(records[:5]):
                        print(f"  {i+1}. {record['hs_code']} | {record['duty']} | {record.get('vat', 'N/A')} | {record['description'][:50]}...")
                    
                    # Тестируем нормализацию кодов
                    print(f"\n🧪 Тестирование нормализации:")
                    test_codes = [
                        "1401 10 000 0",
                        "1401 20 000 0", 
                        "1401 90 000 0",
                        "1404 20 000 0",
                        "1404 90 000 0"
                    ]
                    
                    for code in test_codes:
                        normalized = normalize_hs_code(code)
                        print(f"  {code} -> {normalized}")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def main():
    """Главная функция"""
    print("🚀 Тест парсинга одного PDF файла")
    print("=" * 50)
    
    test_single_pdf()
    
    print("\n" + "=" * 50)
    print("✅ Тест завершен")

if __name__ == "__main__":
    main()
















