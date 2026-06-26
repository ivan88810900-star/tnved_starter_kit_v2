"""
Финальный парсер для извлечения тарифных данных из PDF файлов
"""
import os
import re
import logging
from typing import List, Dict, Any, Optional
import pdfplumber
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

def normalize_hs_code(code: str) -> Optional[str]:
    """
    Нормализует код ТН ВЭД до 10 цифр
    """
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

def extract_tariff_data_final(text: str) -> List[Dict[str, Any]]:
    """
    Финальное извлечение тарифных данных из текста
    """
    tariff_records = []
    
    # Разбиваем текст на строки
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Ищем строки с кодами ТН ВЭД - правильный паттерн
        # Код ТН ВЭД: 4 цифры + пробел + 2 цифры + пробел + 3 цифры + пробел + 1 цифра
        # Но также учитываем, что могут быть разные пробелы
        hs_code_pattern = r'(\d{4}\s+\d{2}\s+\d{3}\s+\d{1})'
        match = re.search(hs_code_pattern, line)
        
        # Если не нашли, пробуем более гибкий паттерн
        if not match:
            hs_code_pattern = r'(\d{4}\s*\d{2}\s*\d{3}\s*\d{1})'
            match = re.search(hs_code_pattern, line)
        
        if match:
            hs_code = normalize_hs_code(match.group(1))
            if hs_code:
                # Извлекаем описание и ставку
                description = line[match.end():].strip()
                
                # Ищем ставку пошлины в конце строки
                duty = "0"
                # Сначала ищем десятичные числа с запятой (6,5%) и точкой (6.5%)
                decimal_match = re.search(r'(\d+[,.]\d+)\s*%?', line)
                if decimal_match:
                    # Заменяем запятую на точку для корректного парсинга
                    duty = decimal_match.group(1).replace(',', '.')
                else:
                    # Если десятичных нет, ищем обычные числа
                    numbers = re.findall(r'\b(\d+(?:\.\d+)?)\b', line)
                    if numbers:
                        # Берем последнее число как ставку пошлины
                        duty = numbers[-1]
                
                # Ищем НДС
                vat = None
                vat_match = re.search(r'НДС[:\s]*(\d+(?:\.\d+)?\s*%)', line)
                if vat_match:
                    vat = vat_match.group(1)
                
                tariff_records.append({
                    'hs_code': hs_code,
                    'duty': duty,
                    'vat': vat,
                    'description': description
                })
    
    return tariff_records

def parse_tariff_pdfs(pdf_dir: str, version: str, db_session: Session) -> int:
    """
    Парсит PDF файлы с тарифными данными и сохраняет в базу данных
    """
    logger.info(f"Парсинг тарифных PDF файлов из {pdf_dir}")
    
    if not os.path.exists(pdf_dir):
        logger.error(f"Директория не найдена: {pdf_dir}")
        return 0
    
    total_records = 0
    processed_files = 0
    
    # Получаем список PDF файлов
    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf')]
    logger.info(f"Найдено {len(pdf_files)} PDF файлов")
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(pdf_dir, pdf_file)
        logger.info(f"Обработка файла: {pdf_file}")
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                file_records = 0
                
                for page_num, page in enumerate(pdf.pages):
                    # Извлекаем текст со страницы
                    text = page.extract_text()
                    if text:
                        tariff_data = extract_tariff_data_final(text)
                        
                        for record in tariff_data:
                            try:
                                # Создаем запись в базе данных
                                from backend.app.models import TariffRate
                                
                                tariff_rate = TariffRate(
                                    hs_code=record['hs_code'],
                                    duty=record['duty'],
                                    vat=record['vat'],
                                    source_version=version
                                )
                                
                                db_session.add(tariff_rate)
                                file_records += 1
                                
                            except Exception as e:
                                logger.warning(f"Ошибка добавления записи {record['hs_code']}: {e}")
                                continue
                
                # Сохраняем изменения для файла
                try:
                    db_session.commit()
                    total_records += file_records
                    processed_files += 1
                    logger.info(f"Файл {pdf_file}: добавлено {file_records} записей")
                    
                except Exception as e:
                    logger.error(f"Ошибка сохранения данных из {pdf_file}: {e}")
                    db_session.rollback()
                    
        except Exception as e:
            logger.error(f"Ошибка обработки файла {pdf_file}: {e}")
            continue
    
    logger.info(f"Обработано файлов: {processed_files}")
    logger.info(f"Всего записей импортировано: {total_records}")
    
    return total_records

def parse_single_pdf(pdf_path: str, version: str) -> List[Dict[str, Any]]:
    """
    Парсит один PDF файл и возвращает список записей
    """
    records = []
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    tariff_data = extract_tariff_data_final(text)
                    records.extend(tariff_data)
                    
    except Exception as e:
        logger.error(f"Ошибка обработки файла {pdf_path}: {e}")
    
    return records
