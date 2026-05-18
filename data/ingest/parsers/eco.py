"""
Парсер для экологических сборов
"""
import os
import re
import logging
from typing import List, Dict, Any
from utils import safe_read_html, safe_read_csv, safe_read_xlsx, normalize_text

logger = logging.getLogger(__name__)

def parse_eco_fee_rates(data_path: str) -> List[Dict[str, Any]]:
    """
    Парсит ставки экологического сбора
    """
    logger.info(f"Парсинг ставок экологического сбора из {data_path}")
    
    results = []
    
    for file_name in os.listdir(data_path):
        file_path = os.path.join(data_path, file_name)
        
        if file_name.endswith('.html'):
            html_data = safe_read_html(file_path)
            if html_data:
                results.extend(parse_html_eco_rates(html_data))
        
        elif file_name.endswith('.csv'):
            csv_data = safe_read_csv(file_path)
            if csv_data is not None:
                results.extend(parse_csv_eco_rates(csv_data))
        
        elif file_name.endswith(('.xlsx', '.xls')):
            xlsx_data = safe_read_xlsx(file_path)
            if xlsx_data is not None:
                results.extend(parse_xlsx_eco_rates(xlsx_data))
    
    logger.info(f"Найдено {len(results)} ставок экологического сбора")
    return results

def parse_html_eco_rates(html_element) -> List[Dict[str, Any]]:
    """Парсит HTML ставки экологического сбора"""
    results = []
    
    # Поиск таблиц со ставками
    tables = html_element.xpath('//table[contains(@class, "eco") or contains(@class, "fee") or contains(@class, "сбор")]')
    
    for table in tables:
        rows = table.xpath('.//tr')
        for row in rows:
            cells = row.xpath('.//td | .//th')
            if len(cells) >= 3:
                material = normalize_text(cells[0].text_content())
                rate_text = normalize_text(cells[1].text_content())
                basis_text = normalize_text(cells[2].text_content())
                
                # Извлекаем числовое значение ставки
                rate_per_kg = extract_rate(rate_text)
                
                if material and rate_per_kg is not None:
                    results.append({
                        'material': material,
                        'category': extract_material_category(material),
                        'rate_per_kg': rate_per_kg,
                        'basis': basis_text
                    })
    
    return results

def parse_csv_eco_rates(df) -> List[Dict[str, Any]]:
    """Парсит CSV ставки экологического сбора"""
    results = []
    
    for _, row in df.iterrows():
        material = str(row.get('material', ''))
        rate_per_kg = float(row.get('rate_per_kg', 0.0))
        basis = str(row.get('basis', ''))
        
        if material and rate_per_kg > 0:
            results.append({
                'material': material,
                'category': extract_material_category(material),
                'rate_per_kg': rate_per_kg,
                'basis': basis
            })
    
    return results

def parse_xlsx_eco_rates(df) -> List[Dict[str, Any]]:
    """Парсит XLSX ставки экологического сбора"""
    return parse_csv_eco_rates(df)

def parse_eco_categories(data_path: str) -> List[Dict[str, Any]]:
    """
    Парсит категории экологического сбора
    """
    logger.info(f"Парсинг категорий экологического сбора из {data_path}")
    
    results = []
    
    for file_name in os.listdir(data_path):
        file_path = os.path.join(data_path, file_name)
        
        if file_name.endswith('.html'):
            html_data = safe_read_html(file_path)
            if html_data:
                results.extend(parse_html_eco_categories(html_data))
        
        elif file_name.endswith('.csv'):
            csv_data = safe_read_csv(file_path)
            if csv_data is not None:
                results.extend(parse_csv_eco_categories(csv_data))
    
    logger.info(f"Найдено {len(results)} категорий экологического сбора")
    return results

def parse_html_eco_categories(html_element) -> List[Dict[str, Any]]:
    """Парсит HTML категории экологического сбора"""
    results = []
    
    # Поиск списков категорий
    category_lists = html_element.xpath('//ul[contains(@class, "category")] | //ol[contains(@class, "category")] | //div[contains(@class, "category")]')
    
    for category_list in category_lists:
        items = category_list.xpath('.//li | .//div[contains(@class, "item")]')
        for item in items:
            text = normalize_text(item.text_content())
            if text:
                results.append({
                    'material': text,
                    'category': extract_material_category(text),
                    'rate_per_kg': 0.0,  # Будет заполнено отдельно
                    'basis': extract_category_basis(item)
                })
    
    return results

def parse_csv_eco_categories(df) -> List[Dict[str, Any]]:
    """Парсит CSV категории экологического сбора"""
    results = []
    
    for _, row in df.iterrows():
        material = str(row.get('material', ''))
        category = str(row.get('category', ''))
        rate_per_kg = float(row.get('rate_per_kg', 0.0))
        basis = str(row.get('basis', ''))
        
        if material:
            results.append({
                'material': material,
                'category': category if category else extract_material_category(material),
                'rate_per_kg': rate_per_kg,
                'basis': basis
            })
    
    return results

def extract_rate(text: str) -> float:
    """Извлекает числовое значение ставки"""
    if not text:
        return None
    
    # Поиск числа в тексте (может быть с запятой или точкой)
    pattern = r'(\d+(?:[.,]\d+)?)'
    match = re.search(pattern, text)
    if match:
        # Заменяем запятую на точку для float
        rate_str = match.group(1).replace(',', '.')
        try:
            return float(rate_str)
        except ValueError:
            return None
    return None

def extract_material_category(material: str) -> str:
    """Определяет категорию материала"""
    if not material:
        return 'other'
    
    material_lower = material.lower()
    
    # Пластики и полимеры
    if any(word in material_lower for word in ['пластик', 'пластмасса', 'полимер', 'полиэтилен', 'полипропилен', 'пвх']):
        return 'plastic'
    # Бумага и картон
    elif any(word in material_lower for word in ['бумага', 'картон', 'целлюлоза']):
        return 'paper'
    # Металлы
    elif any(word in material_lower for word in ['металл', 'железо', 'алюминий', 'сталь', 'медь', 'цинк']):
        return 'metal'
    # Стекло
    elif any(word in material_lower for word in ['стекло', 'керамика']):
        return 'glass'
    # Текстиль
    elif any(word in material_lower for word in ['текстиль', 'ткань', 'хлопок', 'шерсть']):
        return 'textile'
    # Резина
    elif any(word in material_lower for word in ['резина', 'каучук']):
        return 'rubber'
    else:
        return 'other'

def extract_category_basis(item) -> str:
    """Извлекает правовое основание для категории"""
    text = item.text_content()
    
    # Поиск упоминаний нормативных актов
    patterns = [
        r'ФЗ \d+',
        r'Постановление \d+',
        r'Приказ \d+',
        r'Распоряжение \d+'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group()
    
    return ''
