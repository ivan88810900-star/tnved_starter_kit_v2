"""
Парсер для таможенных тарифов
"""
import os
import re
import logging
from typing import List, Dict, Any
from utils import safe_read_html, safe_read_csv, safe_read_xlsx, normalize_text

logger = logging.getLogger(__name__)

def parse_tariff_rates(data_path: str, source_version: str = "") -> List[Dict[str, Any]]:
    """
    Парсит ставки таможенного тарифа
    """
    logger.info(f"Парсинг тарифных ставок из {data_path}")
    
    results = []
    
    for file_name in os.listdir(data_path):
        file_path = os.path.join(data_path, file_name)
        
        if file_name.endswith('.html'):
            html_data = safe_read_html(file_path)
            if html_data:
                results.extend(parse_html_tariff(html_data, source_version))
        
        elif file_name.endswith('.csv'):
            csv_data = safe_read_csv(file_path)
            if csv_data is not None:
                results.extend(parse_csv_tariff(csv_data, source_version))
        
        elif file_name.endswith(('.xlsx', '.xls')):
            xlsx_data = safe_read_xlsx(file_path)
            if xlsx_data is not None:
                results.extend(parse_xlsx_tariff(xlsx_data, source_version))
    
    logger.info(f"Найдено {len(results)} тарифных ставок")
    return results

def parse_html_tariff(html_element, source_version: str) -> List[Dict[str, Any]]:
    """Парсит HTML тарифные данные"""
    results = []
    
    # Поиск таблиц с тарифными ставками
    tables = html_element.xpath('//table[contains(@class, "tariff") or contains(@class, "rate")]')
    
    for table in tables:
        rows = table.xpath('.//tr')
        for row in rows:
            cells = row.xpath('.//td | .//th')
            if len(cells) >= 3:
                hs_code = normalize_text(cells[0].text_content())
                duty_text = normalize_text(cells[1].text_content())
                vat_text = normalize_text(cells[2].text_content())
                add_text = normalize_text(cells[3].text_content()) if len(cells) > 3 else ""
                
                if hs_code and (duty_text or vat_text):
                    results.append({
                        'hs_code': hs_code,
                        'duty': duty_text,
                        'vat': vat_text,
                        'add': add_text if add_text else None,
                        'source_version': source_version
                    })
    
    return results

def parse_csv_tariff(df, source_version: str) -> List[Dict[str, Any]]:
    """Парсит CSV тарифные данные"""
    results = []
    
    for _, row in df.iterrows():
        hs_code = str(row.get('hs_code', ''))
        duty = str(row.get('duty', ''))
        vat = str(row.get('vat', ''))
        add = str(row.get('add', ''))
        
        if hs_code and (duty or vat):
            results.append({
                'hs_code': hs_code,
                'duty': duty,
                'vat': vat,
                'add': add if add else None,
                'source_version': source_version
            })
    
    return results

def parse_xlsx_tariff(df, source_version: str) -> List[Dict[str, Any]]:
    """Парсит XLSX тарифные данные"""
    return parse_csv_tariff(df, source_version)

def parse_preferential_rates(data_path: str, source_version: str = "") -> List[Dict[str, Any]]:
    """
    Парсит преференциальные ставки
    """
    logger.info(f"Парсинг преференциальных ставок из {data_path}")
    
    results = []
    
    for file_name in os.listdir(data_path):
        file_path = os.path.join(data_path, file_name)
        
        if file_name.endswith('.html'):
            html_data = safe_read_html(file_path)
            if html_data:
                results.extend(parse_html_preferential(html_data, source_version))
        
        elif file_name.endswith('.csv'):
            csv_data = safe_read_csv(file_path)
            if csv_data is not None:
                results.extend(parse_csv_preferential(csv_data, source_version))
        
        elif file_name.endswith(('.xlsx', '.xls')):
            xlsx_data = safe_read_xlsx(file_path)
            if xlsx_data is not None:
                results.extend(parse_xlsx_preferential(xlsx_data, source_version))
    
    logger.info(f"Найдено {len(results)} преференциальных ставок")
    return results

def parse_html_preferential(html_element, source_version: str) -> List[Dict[str, Any]]:
    """Парсит HTML преференциальные данные"""
    results = []
    
    # Поиск таблиц с преференциальными ставками
    tables = html_element.xpath('//table[contains(@class, "preferential") or contains(@class, "preference")]')
    
    for table in tables:
        rows = table.xpath('.//tr')
        for row in rows:
            cells = row.xpath('.//td | .//th')
            if len(cells) >= 3:
                hs_code = normalize_text(cells[0].text_content())
                country = normalize_text(cells[1].text_content())
                rate = normalize_text(cells[2].text_content())
                
                if hs_code and country and rate:
                    results.append({
                        'hs_code': hs_code,
                        'duty': rate,  # Преференциальная ставка
                        'vat': '',     # НДС обычно не отличается
                        'add': None,
                        'source_version': source_version
                    })
    
    return results

def parse_csv_preferential(df, source_version: str) -> List[Dict[str, Any]]:
    """Парсит CSV преференциальные данные"""
    results = []
    
    for _, row in df.iterrows():
        hs_code = str(row.get('hs_code', ''))
        country = str(row.get('country', ''))
        rate = str(row.get('preferential_rate', ''))
        
        if hs_code and country and rate:
            results.append({
                'hs_code': hs_code,
                'duty': rate,
                'vat': '',
                'add': None,
                'source_version': source_version
            })
    
    return results

def parse_xlsx_preferential(df, source_version: str) -> List[Dict[str, Any]]:
    """Парсит XLSX преференциальные данные"""
    return parse_csv_preferential(df, source_version)
