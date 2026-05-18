#!/usr/bin/env python3
"""
Тестовый скрипт для проверки парсера PDF тарифов
"""
import os
import sys
import logging

# Добавляем путь к backend для импорта моделей
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from app.db import SessionLocal, init_db
from parsers.tariff_pdf import parse_tariff_pdfs, normalize_hs_code, get_tariff_statistics

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_normalize_hs_code():
    """Тест нормализации кодов ТН ВЭД"""
    print("🧪 Тестирование нормализации кодов ТН ВЭД")
    
    test_cases = [
        ("1234 56 78 90", "1234567890"),
        ("1234.56.78.90", "1234567890"),
        ("1234567890", "1234567890"),
        ("1234", None),  # Слишком короткий
        ("12345678901", None),  # Слишком длинный
        ("", None),
        ("abc1234567", None),  # Содержит буквы
    ]
    
    for input_code, expected in test_cases:
        result = normalize_hs_code(input_code)
        status = "✅" if result == expected else "❌"
        print(f"  {status} '{input_code}' -> {result} (ожидалось: {expected})")

def test_pdf_parsing():
    """Тест парсинга PDF файлов"""
    print("\n🧪 Тестирование парсинга PDF файлов")
    
    # Путь к директории с PDF файлами
    pdf_dir = "data/raw/tariff_cet/2025-01-01"
    
    if not os.path.exists(pdf_dir):
        print(f"❌ Директория не найдена: {pdf_dir}")
        return
    
    # Проверяем наличие PDF файлов
    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf')]
    print(f"📄 Найдено {len(pdf_files)} PDF файлов")
    
    if not pdf_files:
        print("❌ PDF файлы не найдены")
        return
    
    # Показываем первые несколько файлов
    print("📄 Первые 5 PDF файлов:")
    for i, pdf_file in enumerate(pdf_files[:5]):
        print(f"  {i+1}. {pdf_file}")
    
    # Инициализируем базу данных
    try:
        init_db()
        session = SessionLocal()
        print("✅ База данных инициализирована")
        
        # Парсим PDF файлы (только первые 3 для теста)
        test_files = pdf_files[:3]
        print(f"\n🔍 Тестируем парсинг {len(test_files)} файлов...")
        
        total_records = 0
        for pdf_file in test_files:
            pdf_path = os.path.join(pdf_dir, pdf_file)
            print(f"\n📄 Обработка: {pdf_file}")
            
            try:
                # Парсим один файл
                from parsers.tariff_pdf import parse_single_pdf
                records = parse_single_pdf(pdf_path, "2025-01-01")
                
                print(f"  📊 Найдено записей: {len(records)}")
                total_records += len(records)
                
                # Показываем первые несколько записей
                if records:
                    print("  📝 Первые записи:")
                    for i, record in enumerate(records[:3]):
                        print(f"    {i+1}. {record['hs_code']} | {record['duty']} | {record.get('vat', 'N/A')}")
                
            except Exception as e:
                print(f"  ❌ Ошибка обработки {pdf_file}: {e}")
        
        print(f"\n📊 Всего записей найдено: {total_records}")
        
        # Получаем статистику
        stats = get_tariff_statistics(session)
        print(f"📈 Статистика базы данных:")
        print(f"  Всего записей: {stats['total_records']}")
        print(f"  Версии: {stats['versions']}")
        
        session.close()
        
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")

def main():
    """Главная функция"""
    print("🚀 Тестирование парсера PDF тарифов")
    print("=" * 50)
    
    # Тест нормализации кодов
    test_normalize_hs_code()
    
    # Тест парсинга PDF
    test_pdf_parsing()
    
    print("\n" + "=" * 50)
    print("✅ Тестирование завершено")

if __name__ == "__main__":
    main()
















