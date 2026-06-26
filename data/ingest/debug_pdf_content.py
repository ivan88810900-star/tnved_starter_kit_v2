#!/usr/bin/env python3
"""
Диагностический скрипт для анализа содержимого PDF файлов
"""
import os
import sys
import pdfplumber
import re
from collections import Counter

def analyze_pdf_structure(pdf_path: str, max_pages: int = 3):
    """Анализирует структуру PDF файла"""
    print(f"\n📄 Анализ файла: {os.path.basename(pdf_path)}")
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            print(f"  📊 Всего страниц: {total_pages}")
            
            # Анализируем первые несколько страниц
            for page_num in range(min(max_pages, total_pages)):
                page = pdf.pages[page_num]
                print(f"\n  📄 Страница {page_num + 1}:")
                
                # Извлекаем текст
                text = page.extract_text()
                if text:
                    lines = text.split('\n')
                    print(f"    📝 Строк текста: {len(lines)}")
                    
                    # Показываем первые 10 строк
                    print("    📋 Первые строки:")
                    for i, line in enumerate(lines[:10]):
                        if line.strip():
                            print(f"      {i+1:2d}. {line.strip()[:80]}")
                
                # Извлекаем таблицы
                tables = page.extract_tables()
                print(f"    📊 Таблиц найдено: {len(tables)}")
                
                for table_num, table in enumerate(tables[:2]):  # Первые 2 таблицы
                    if table and len(table) > 0:
                        print(f"    📋 Таблица {table_num + 1}:")
                        print(f"      Строк: {len(table)}")
                        print(f"      Колонок: {len(table[0]) if table[0] else 0}")
                        
                        # Показываем первые 5 строк таблицы
                        for i, row in enumerate(table[:5]):
                            if row:
                                row_text = ' | '.join([str(cell)[:20] if cell else '' for cell in row])
                                print(f"        {i+1}. {row_text}")
                
                # Ищем коды ТН ВЭД в тексте
                if text:
                    hs_codes = find_hs_codes_in_text(text)
                    print(f"    🔍 Кодов ТН ВЭД найдено: {len(hs_codes)}")
                    if hs_codes:
                        print(f"    📋 Примеры кодов: {hs_codes[:5]}")
    
    except Exception as e:
        print(f"  ❌ Ошибка: {e}")

def find_hs_codes_in_text(text: str) -> list:
    """Ищет коды ТН ВЭД в тексте"""
    # Различные паттерны для поиска кодов ТН ВЭД
    patterns = [
        r'\b\d{2}\s*\d{2}\s*\d{2}\s*\d{2}\b',  # 12 34 56 78
        r'\b\d{2}\.\d{2}\.\d{2}\.\d{2}\b',     # 12.34.56.78
        r'\b\d{4}\s*\d{2}\s*\d{2}\s*\d{2}\b',  # 1234 56 78 90
        r'\b\d{4}\.\d{2}\.\d{2}\.\d{2}\b',     # 1234.56.78.90
        r'\b\d{6}\s*\d{2}\s*\d{2}\b',          # 123456 78 90
        r'\b\d{6}\.\d{2}\.\d{2}\b',             # 123456.78.90
        r'\b\d{8}\s*\d{2}\b',                   # 12345678 90
        r'\b\d{8}\.\d{2}\b',                    # 12345678.90
        r'\b\d{10}\b',                          # 1234567890
    ]
    
    all_codes = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        all_codes.extend(matches)
    
    return list(set(all_codes))  # Убираем дубликаты

def analyze_multiple_pdfs(pdf_dir: str, max_files: int = 5):
    """Анализирует несколько PDF файлов"""
    print("🔍 Анализ структуры PDF файлов")
    print("=" * 60)
    
    if not os.path.exists(pdf_dir):
        print(f"❌ Директория не найдена: {pdf_dir}")
        return
    
    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf')]
    print(f"📄 Найдено {len(pdf_files)} PDF файлов")
    
    if not pdf_files:
        print("❌ PDF файлы не найдены")
        return
    
    # Анализируем первые несколько файлов
    test_files = pdf_files[:max_files]
    print(f"🔍 Анализируем {len(test_files)} файлов...")
    
    total_codes = []
    for pdf_file in test_files:
        pdf_path = os.path.join(pdf_dir, pdf_file)
        analyze_pdf_structure(pdf_path)
        
        # Собираем коды для статистики
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages[:2]:  # Первые 2 страницы
                    text = page.extract_text()
                    if text:
                        codes = find_hs_codes_in_text(text)
                        total_codes.extend(codes)
        except:
            pass
    
    # Статистика по кодам
    if total_codes:
        print(f"\n📊 Общая статистика:")
        print(f"  Всего кодов найдено: {len(total_codes)}")
        
        # Топ-10 кодов
        code_counts = Counter(total_codes)
        print(f"  Топ-10 кодов:")
        for code, count in code_counts.most_common(10):
            print(f"    {code}: {count} раз")
        
        # Анализ форматов кодов
        print(f"\n📋 Анализ форматов кодов:")
        formats = {}
        for code in total_codes:
            # Убираем пробелы и точки для анализа
            clean_code = re.sub(r'[\s\.]', '', code)
            length = len(clean_code)
            formats[length] = formats.get(length, 0) + 1
        
        for length, count in sorted(formats.items()):
            print(f"    {length} цифр: {count} кодов")

def test_regex_patterns():
    """Тестирует различные регулярные выражения"""
    print("\n🧪 Тестирование регулярных выражений")
    
    test_cases = [
        "1234 56 78 90",
        "12.34.56.78",
        "1234567890",
        "1234.56.78.90",
        "12 34 56 78 90",
        "123456 78 90",
        "12345678 90",
        "12345678.90",
        "1234567890",
        "12345678901",  # 11 цифр
        "123456789",    # 9 цифр
        "abc1234567",   # с буквами
    ]
    
    patterns = [
        (r'\b\d{2}\s*\d{2}\s*\d{2}\s*\d{2}\b', "2+2+2+2"),
        (r'\b\d{4}\s*\d{2}\s*\d{2}\s*\d{2}\b', "4+2+2+2"),
        (r'\b\d{6}\s*\d{2}\s*\d{2}\b', "6+2+2"),
        (r'\b\d{8}\s*\d{2}\b', "8+2"),
        (r'\b\d{10}\b', "10 цифр"),
    ]
    
    for test_case in test_cases:
        print(f"\n  Тест: '{test_case}'")
        for pattern, description in patterns:
            matches = re.findall(pattern, test_case)
            status = "✅" if matches else "❌"
            print(f"    {status} {description}: {matches}")

def main():
    """Главная функция"""
    print("🚀 Диагностика PDF файлов с тарифными данными")
    print("=" * 60)
    
    # Тестируем регулярные выражения
    test_regex_patterns()
    
    # Анализируем PDF файлы
    pdf_dir = "data/raw/tariff_cet/2025-01-01"
    analyze_multiple_pdfs(pdf_dir, max_files=3)
    
    print("\n" + "=" * 60)
    print("✅ Диагностика завершена")

if __name__ == "__main__":
    main()
















