#!/usr/bin/env python3
"""
Детальный диагностический скрипт для анализа PDF файлов
"""
import os
import sys
import pdfplumber
import re

def analyze_single_pdf_detailed(pdf_path: str):
    """Детальный анализ одного PDF файла"""
    print(f"\n📄 Детальный анализ: {os.path.basename(pdf_path)}")
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages[:2]):  # Первые 2 страницы
                print(f"\n  📄 Страница {page_num + 1}:")
                
                # Извлекаем текст
                text = page.extract_text()
                if text:
                    lines = text.split('\n')
                    print(f"    📝 Всего строк: {len(lines)}")
                    
                    # Ищем строки с цифрами
                    number_lines = []
                    for i, line in enumerate(lines):
                        if re.search(r'\d', line) and len(line.strip()) > 5:
                            number_lines.append((i, line.strip()))
                    
                    print(f"    🔢 Строк с цифрами: {len(number_lines)}")
                    
                    # Показываем первые 20 строк с цифрами
                    print("    📋 Строки с цифрами:")
                    for i, (line_num, line) in enumerate(number_lines[:20]):
                        print(f"      {line_num:2d}: {line}")
                        
                        # Ищем коды ТН ВЭД в этой строке
                        codes_found = []
                        
                        # Различные паттерны
                        patterns = [
                            (r'\b\d{2}\s*\d{2}\s*\d{2}\s*\d{2}\b', "2+2+2+2"),
                            (r'\b\d{4}\s*\d{2}\s*\d{2}\s*\d{2}\b', "4+2+2+2"),
                            (r'\b\d{6}\s*\d{2}\s*\d{2}\b', "6+2+2"),
                            (r'\b\d{8}\s*\d{2}\b', "8+2"),
                            (r'\b\d{10}\b', "10 цифр"),
                            (r'\b\d{2}\.\d{2}\.\d{2}\.\d{2}\b', "2.2.2.2"),
                            (r'\b\d{4}\.\d{2}\.\d{2}\.\d{2}\b', "4.2.2.2"),
                        ]
                        
                        for pattern, description in patterns:
                            matches = re.findall(pattern, line)
                            if matches:
                                codes_found.extend([(match, description) for match in matches])
                        
                        if codes_found:
                            print(f"        🔍 Найдены коды: {codes_found}")
                
                # Извлекаем таблицы
                tables = page.extract_tables()
                print(f"    📊 Таблиц: {len(tables)}")
                
                for table_num, table in enumerate(tables):
                    if table and len(table) > 0:
                        print(f"    📋 Таблица {table_num + 1}:")
                        print(f"      Строк: {len(table)}")
                        print(f"      Колонок: {len(table[0]) if table[0] else 0}")
                        
                        # Показываем все строки таблицы
                        for i, row in enumerate(table):
                            if row:
                                row_text = ' | '.join([str(cell)[:30] if cell else '' for cell in row])
                                print(f"        {i+1:2d}: {row_text}")
                                
                                # Ищем коды в строке таблицы
                                full_row_text = ' '.join([str(cell) if cell else '' for cell in row])
                                codes_in_row = []
                                
                                for pattern, description in patterns:
                                    matches = re.findall(pattern, full_row_text)
                                    if matches:
                                        codes_in_row.extend([(match, description) for match in matches])
                                
                                if codes_in_row:
                                    print(f"          🔍 Коды в строке: {codes_in_row}")
    
    except Exception as e:
        print(f"  ❌ Ошибка: {e}")

def main():
    """Главная функция"""
    print("🔍 Детальный анализ PDF файлов")
    print("=" * 60)
    
    pdf_dir = "data/raw/tariff_cet/2025-01-01"
    
    if not os.path.exists(pdf_dir):
        print(f"❌ Директория не найдена: {pdf_dir}")
        return
    
    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf')]
    print(f"📄 Найдено {len(pdf_files)} PDF файлов")
    
    # Анализируем первые 2 файла детально
    for pdf_file in pdf_files[:2]:
        pdf_path = os.path.join(pdf_dir, pdf_file)
        analyze_single_pdf_detailed(pdf_path)
    
    print("\n" + "=" * 60)
    print("✅ Детальный анализ завершен")

if __name__ == "__main__":
    main()
















