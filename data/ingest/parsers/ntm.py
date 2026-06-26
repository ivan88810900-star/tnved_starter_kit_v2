"""
Парсер для нетарифных мер
"""
import os
import re
import logging
from typing import List, Dict, Any
from utils import safe_read_html, safe_read_csv, safe_read_xlsx, normalize_text

logger = logging.getLogger(__name__)

def parse_ntm_measures(data_path: str) -> List[Dict[str, Any]]:
    """
    Парсит нетарифные меры
    """
    logger.info(f"Парсинг нетарифных мер из {data_path}")
    
    results = []
    
    for file_name in os.listdir(data_path):
        file_path = os.path.join(data_path, file_name)
        
        if file_name.endswith('.html'):
            html_data = safe_read_html(file_path)
            if html_data:
                results.extend(parse_html_ntm(html_data))
        
        elif file_name.endswith('.csv'):
            csv_data = safe_read_csv(file_path)
            if csv_data is not None:
                results.extend(parse_csv_ntm(csv_data))
        
        elif file_name.endswith(('.xlsx', '.xls')):
            xlsx_data = safe_read_xlsx(file_path)
            if xlsx_data is not None:
                results.extend(parse_xlsx_ntm(xlsx_data))
    
    logger.info(f"Найдено {len(results)} нетарифных мер")
    return results

def parse_html_ntm(html_element) -> List[Dict[str, Any]]:
    """Парсит HTML нетарифные меры"""
    results = []
    
    # Поиск таблиц с нетарифными мерами
    tables = html_element.xpath('//table[contains(@class, "ntm") or contains(@class, "measure") or contains(@class, "restriction")]')
    
    for table in tables:
        rows = table.xpath('.//tr')
        for row in rows:
            cells = row.xpath('.//td | .//th')
            if len(cells) >= 3:
                hs_code_text = normalize_text(cells[0].text_content())
                title = normalize_text(cells[1].text_content())
                basis = normalize_text(cells[2].text_content())
                country = normalize_text(cells[3].text_content()) if len(cells) > 3 else ""
                notes = normalize_text(cells[4].text_content()) if len(cells) > 4 else ""
                
                # Извлекаем префикс кода
                hs_code_prefix = extract_hs_code_prefix(hs_code_text)
                
                if hs_code_prefix and title:
                    results.append({
                        'hs_code_prefix': hs_code_prefix,
                        'title': title,
                        'basis': basis,
                        'country': country if country else None,
                        'notes': notes
                    })
    
    return results

def parse_csv_ntm(df) -> List[Dict[str, Any]]:
    """Парсит CSV нетарифные меры"""
    results = []
    
    for _, row in df.iterrows():
        hs_code_text = str(row.get('hs_code', ''))
        title = str(row.get('title', ''))
        basis = str(row.get('basis', ''))
        country = str(row.get('country', ''))
        notes = str(row.get('notes', ''))
        
        hs_code_prefix = extract_hs_code_prefix(hs_code_text)
        
        if hs_code_prefix and title:
            results.append({
                'hs_code_prefix': hs_code_prefix,
                'title': title,
                'basis': basis,
                'country': country if country else None,
                'notes': notes
            })
    
    return results

def parse_xlsx_ntm(df) -> List[Dict[str, Any]]:
    """Парсит XLSX нетарифные меры"""
    return parse_csv_ntm(df)

def parse_licensing_requirements(data_path: str) -> List[Dict[str, Any]]:
    """
    Парсит требования лицензирования
    """
    logger.info(f"Парсинг требований лицензирования из {data_path}")
    
    results = []
    
    for file_name in os.listdir(data_path):
        file_path = os.path.join(data_path, file_name)
        
        if file_name.endswith('.html'):
            html_data = safe_read_html(file_path)
            if html_data:
                results.extend(parse_html_licensing(html_data))
        
        elif file_name.endswith('.csv'):
            csv_data = safe_read_csv(file_path)
            if csv_data is not None:
                results.extend(parse_csv_licensing(csv_data))
    
    logger.info(f"Найдено {len(results)} требований лицензирования")
    return results

def parse_html_licensing(html_element) -> List[Dict[str, Any]]:
    """Парсит HTML требования лицензирования"""
    results = []
    
    # Поиск блоков с требованиями лицензирования
    license_blocks = html_element.xpath('//div[contains(@class, "license") or contains(@class, "permit") or contains(@class, "разрешение")]')
    
    for block in license_blocks:
        hs_code_text = extract_hs_code_from_block(block)
        title = extract_license_title(block)
        basis = extract_license_basis(block)
        country = extract_country_from_context(block)
        notes = extract_license_notes(block)
        
        hs_code_prefix = extract_hs_code_prefix(hs_code_text)
        
        if hs_code_prefix and title:
            results.append({
                'hs_code_prefix': hs_code_prefix,
                'title': title,
                'basis': basis,
                'country': country if country else None,
                'notes': notes
            })
    
    return results

def parse_csv_licensing(df) -> List[Dict[str, Any]]:
    """Парсит CSV требования лицензирования"""
    results = []
    
    for _, row in df.iterrows():
        hs_code_text = str(row.get('hs_code', ''))
        title = str(row.get('title', ''))
        basis = str(row.get('basis', ''))
        country = str(row.get('country', ''))
        notes = str(row.get('notes', ''))
        
        hs_code_prefix = extract_hs_code_prefix(hs_code_text)
        
        if hs_code_prefix and title:
            results.append({
                'hs_code_prefix': hs_code_prefix,
                'title': title,
                'basis': basis,
                'country': country if country else None,
                'notes': notes
            })
    
    return results

def extract_hs_code_prefix(hs_code_text: str) -> str:
    """Извлекает префикс кода ТН ВЭД (2, 4 или 6 знаков)"""
    if not hs_code_text:
        return ''
    
    # Очищаем код от точек и пробелов
    clean_code = re.sub(r'[.\s]', '', hs_code_text)
    
    # Возвращаем префикс в зависимости от длины
    if len(clean_code) >= 6:
        return clean_code[:6]  # 6 знаков
    elif len(clean_code) >= 4:
        return clean_code[:4]  # 4 знака
    elif len(clean_code) >= 2:
        return clean_code[:2]  # 2 знака
    else:
        return clean_code

def extract_hs_code_from_block(block) -> str:
    """Извлекает код ТН ВЭД из блока"""
    text = block.text_content()
    # Поиск различных форматов кодов
    patterns = [
        r'\b\d{2}\.\d{2}\.\d{2}\.\d{2}\b',  # 12.34.56.78
        r'\b\d{2}\.\d{2}\.\d{2}\b',         # 12.34.56
        r'\b\d{2}\.\d{2}\b',                # 12.34
        r'\b\d{2}\b',                       # 12
        r'\b\d{4}\b',                       # 1234
        r'\b\d{6}\b'                        # 123456
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group()
    
    return ''

def extract_license_title(block) -> str:
    """Извлекает название лицензии"""
    # Поиск заголовков или выделенного текста
    headers = block.xpath('.//h1 | .//h2 | .//h3 | .//strong | .//b')
    if headers:
        return normalize_text(headers[0].text_content())
    
    # Если нет заголовков, берем первую строку
    text = block.text_content()
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if line and len(line) > 10:  # Минимальная длина для названия
            return normalize_text(line)
    
    return ''

def extract_license_basis(block) -> str:
    """Извлекает правовое основание"""
    text = block.text_content()
    
    # Поиск упоминаний нормативных актов
    patterns = [
        r'ТР ТС \d+/\d+',
        r'ТР ЕАЭС \d+/\d+',
        r'ФЗ \d+',
        r'Постановление \d+',
        r'Приказ \d+'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group()
    
    return ''

def extract_country_from_context(block) -> str:
    """Извлекает страну из контекста блока"""
    text = block.text_content()
    
    # Поиск упоминаний стран
    countries = ['Россия', 'РФ', 'Беларусь', 'Казахстан', 'Армения', 'Кыргызстан']
    for country in countries:
        if country in text:
            return country
    
    return ''

def extract_license_notes(block) -> str:
    """Извлекает примечания к лицензии"""
    # Ищем блоки с дополнительной информацией
    note_elements = block.xpath('.//p[contains(@class, "note")] | .//div[contains(@class, "note")]')
    if note_elements:
        return normalize_text(note_elements[0].text_content())
    
    return ''
