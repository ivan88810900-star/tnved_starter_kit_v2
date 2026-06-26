#!/usr/bin/env python3
"""
Тест финального парсера PDF
"""
import os
import sys
import re
import pdfplumber

# Добавляем путь к backend для импорта моделей
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from parsers.tariff_pdf_final import extract_tariff_data_final, normalize_hs_code

def test_final_parser():
    """Тестирует финальный парсер"""
    pdf_path = "data/raw/tariff_cet/2025-01-01/ru.14_2022_10.10.2022.pdf"
    
    print(f"📄 Тестирование финального парсера: {os.path.basename(pdf_path)}")
    
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
                    
                    # Показываем строки с кодами ТН ВЭД
                    lines = text.split('\n')
                    print("🔍 Строки с кодами ТН ВЭД:")
                    for i, line in enumerate(lines):
                        if re.search(r'\d{4}\s+\d{2}\s+\d{2}\s+\d{2}', line):
                            print(f"  {i+1:2d}: '{line.strip()}'")
                    
                    # Тестируем парсер
                    print(f"\n🔍 Тестирование финального парсера:")
                    records = extract_tariff_data_final(text)
                    print(f"📊 Найдено записей: {len(records)}")
                    
                    for i, record in enumerate(records):
                        print(f"  {i+1}. {record['hs_code']} | {record['duty']} | {record.get('vat', 'N/A')} | {record['description'][:50]}...")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def main():
    """Главная функция"""
    print("🚀 Тест финального парсера PDF")
    print("=" * 50)
    
    test_final_parser()
    
    print("\n" + "=" * 50)
    print("✅ Тест завершен")

if __name__ == "__main__":
    main()
















