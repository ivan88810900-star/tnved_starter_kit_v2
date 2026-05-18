#!/usr/bin/env python3
"""
Детальный анализ строк в PDF файле
"""
import os
import sys
import re
import pdfplumber

def debug_pdf_lines():
    """Детальный анализ строк в PDF"""
    pdf_path = "data/raw/tariff_cet/2025-01-01/ru.14_2022_10.10.2022.pdf"
    
    print(f"📄 Детальный анализ строк: {os.path.basename(pdf_path)}")
    
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
                    lines = text.split('\n')
                    print(f"📝 Всего строк: {len(lines)}")
                    
                    # Показываем все строки с цифрами
                    print("🔍 Все строки с цифрами:")
                    for i, line in enumerate(lines):
                        if re.search(r'\d', line) and len(line.strip()) > 3:
                            print(f"  {i+1:2d}: '{line.strip()}'")
                            
                            # Проверяем различные паттерны
                            patterns = [
                                (r'\d{4}\s*\d{2}\s*\d{2}\s*\d{2}', "4+2+2+2"),
                                (r'\d{4}\s+\d{2}\s+\d{2}\s+\d{2}', "4+2+2+2 (строгий)"),
                                (r'\d{4}\s*\d{2}\s*\d{2}\s*\d{2}', "4+2+2+2 (гибкий)"),
                                (r'\d{4}\s*\d{2}\s*\d{2}\s*\d{2}', "4+2+2+2 (очень гибкий)"),
                            ]
                            
                            for pattern, description in patterns:
                                matches = re.findall(pattern, line)
                                if matches:
                                    print(f"    ✅ {description}: {matches}")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def main():
    """Главная функция"""
    print("🔍 Детальный анализ строк в PDF")
    print("=" * 60)
    
    debug_pdf_lines()
    
    print("\n" + "=" * 60)
    print("✅ Анализ завершен")

if __name__ == "__main__":
    main()
















