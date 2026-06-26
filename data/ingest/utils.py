"""
Утилиты для обработки данных
"""
import hashlib
import os
import pandas as pd
from lxml import etree, html
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

def sha256(file_path: str) -> str:
    """Вычисляет SHA256 хеш файла"""
    hash_sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()

def sha256_bytes(data: bytes) -> str:
    """Вычисляет SHA256 хеш байтовых данных"""
    return hashlib.sha256(data).hexdigest()

def safe_read_html(file_path: str) -> Optional[html.HtmlElement]:
    """Безопасное чтение HTML файла"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return html.fromstring(content)
    except Exception as e:
        logger.error(f"Ошибка чтения HTML файла {file_path}: {e}")
        return None

def safe_read_csv(file_path: str, **kwargs) -> Optional[pd.DataFrame]:
    """Безопасное чтение CSV файла"""
    try:
        return pd.read_csv(file_path, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка чтения CSV файла {file_path}: {e}")
        return None

def safe_read_xlsx(file_path: str, **kwargs) -> Optional[pd.DataFrame]:
    """Безопасное чтение XLSX файла"""
    try:
        return pd.read_excel(file_path, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка чтения XLSX файла {file_path}: {e}")
        return None

def safe_read_xml(file_path: str) -> Optional[etree.Element]:
    """Безопасное чтение XML файла"""
    try:
        return etree.parse(file_path).getroot()
    except Exception as e:
        logger.error(f"Ошибка чтения XML файла {file_path}: {e}")
        return None

def bulk_insert(session, model_class, data_list: List[Dict[str, Any]], batch_size: int = 1000):
    """Массовая вставка данных в БД"""
    try:
        for i in range(0, len(data_list), batch_size):
            batch = data_list[i:i + batch_size]
            objects = [model_class(**item) for item in batch]
            session.bulk_save_objects(objects)
            session.commit()
            logger.info(f"Вставлено {len(batch)} записей (пакет {i//batch_size + 1})")
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка массовой вставки: {e}")
        raise

def validate_file_exists(file_path: str) -> bool:
    """Проверяет существование файла"""
    return os.path.exists(file_path) and os.path.isfile(file_path)

def get_file_size(file_path: str) -> int:
    """Возвращает размер файла в байтах"""
    return os.path.getsize(file_path)

def normalize_text(text: str) -> str:
    """Нормализует текст (убирает лишние пробелы, переносы)"""
    if not text:
        return ""
    return " ".join(text.strip().split())


