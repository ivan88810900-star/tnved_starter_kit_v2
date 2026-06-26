"""
Парсер для извлечения тарифных данных из PDF файлов (исправленная версия)
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

def extract_tariff_data_from_text(text: str) -> List[Dict[str, Any]]:
    """
    Извлекает тарифные данные из текста PDF
    """
    tariff_records = []
    
    # Разбиваем текст на строки
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or len(line) < 10:
            continue
        
        # Ищем код ТН ВЭД в строке
        hs_code = None
        
        # Различные паттерны для поиска кодов ТН ВЭД
        patterns = [
            r'\b(\d{2}\s*\d{2}\s*\d{2}\s*\d{2})\b',      # 12 34 56 78
            r'\b(\d{4}\s*\d{2}\s*\d{2}\s*\d{2})\b',      # 1234 56 78 90
            r'\b(\d{6}\s*\d{2}\s*\d{2})\b',              # 123456 78 90
            r'\b(\d{8}\s*\d{2})\b',                     # 12345678 90
            r'\b(\d{10})\b',                             # 1234567890
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                hs_code = normalize_hs_code(match.group(1))
                if hs_code:
                    break
        
        if not hs_code:
            continue
        
        # Извлекаем описание товара (текст после кода)
        description = line
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                description = line[match.end():].strip()
                break
        
        # Ищем ставку пошлины
        duty = "0"
        vat = None
        
        # Ищем процентные ставки
        duty_match = re.search(r'(\d+(?:\.\d+)?\s*%)', line)
        if duty_match:
            duty = duty_match.group(1)
        else:
            # Ищем числовые значения
            numbers = re.findall(r'\b(\d+(?:\.\d+)?)\b', line)
            if numbers:
                # Берем последнее число как ставку пошлины
                duty = numbers[-1]
        
        # Ищем НДС
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
                        tariff_data = extract_tariff_data_from_text(text)
                        
                        for record in tariff_data:
                            try:
                                # Создаем запись в базе данных
                                from app.models import TariffRate
                                
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
                    tariff_data = extract_tariff_data_from_text(text)
                    records.extend(tariff_data)
                    
    except Exception as e:
        logger.error(f"Ошибка обработки файла {pdf_path}: {e}")
    
    return records

def get_tariff_statistics(db_session: Session) -> Dict[str, Any]:
    """
    Возвращает статистику по тарифным данным в базе
    """
    from app.models import TariffRate
    
    total_records = db_session.query(TariffRate).count()
    
    # Группировка по версиям
    versions = db_session.query(TariffRate.source_version).distinct().all()
    version_stats = {}
    
    for version in versions:
        if version[0]:
            count = db_session.query(TariffRate).filter(
                TariffRate.source_version == version[0]
            ).count()
            version_stats[version[0]] = count
    
    return {
        'total_records': total_records,
        'versions': version_stats
    }
















