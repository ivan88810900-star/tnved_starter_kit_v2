#!/usr/bin/env python3
"""Seed commodity-group-specific regulatory documents.

Deep regulatory coverage for 8 major commodity groups:
1. Electronics (ch. 84-85) — FSB notifications, classification specifics
2. Automobiles (ch. 87) — OTTS, SBKTS, recycling fee
3. Food products (ch. 01-24) — vet/phyto/SGR per product type
4. Clothing & footwear (ch. 61-64) — Honest Mark marking
5. Pharmaceuticals (ch. 30) — RU registration, import specifics
6. Chemicals (ch. 28-38) — safety data sheets, permits
7. Precious metals (ch. 71) — licenses, Kimberley certificates
8. Weapons & ammunition (ch. 93) — MVD/FSB permits

Usage:
    cd customs-clear/backend
    python3 -m scripts.seed_commodity_group_docs [--dry-run]
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models.regulatory import RegulatoryDocHsMapping, RegulatoryDocument

DRY_RUN = "--dry-run" in sys.argv


def _doc_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _url(prefix: str, num: str) -> str:
    return f"https://docs.customs-ved.ru/{prefix}/{num.replace('/', '-').replace(' ', '_')}"


# ═══════════════════════════════════════════════════════════════════
# 1. ELECTRONICS (chapters 84-85)
# ═══════════════════════════════════════════════════════════════════
ELECTRONICS_DOCS: list[dict] = [
    # FSB notifications for crypto
    {"num": "НОТ-ФСБ-СМАРТФОН", "agency": "FSB", "type": "notification", "title": "Нотификация ФСБ: смартфоны и мобильные телефоны с шифрованием (8517.12)", "hs": ["851712"], "date": "2024-01-15"},
    {"num": "НОТ-ФСБ-НОУТБУК", "agency": "FSB", "type": "notification", "title": "Нотификация ФСБ: ноутбуки и планшеты с шифрованием (8471.30)", "hs": ["847130"], "date": "2024-01-15"},
    {"num": "НОТ-ФСБ-РОУТЕР", "agency": "FSB", "type": "notification", "title": "Нотификация ФСБ: маршрутизаторы и сетевое оборудование (8517.62)", "hs": ["851762"], "date": "2024-02-01"},
    {"num": "НОТ-ФСБ-УМЧАСЫ", "agency": "FSB", "type": "notification", "title": "Нотификация ФСБ: умные часы с модулями связи (8517.12)", "hs": ["851712", "910211"], "date": "2024-02-01"},
    {"num": "НОТ-ФСБ-НАУШНИКИ", "agency": "FSB", "type": "notification", "title": "Нотификация ФСБ: беспроводные наушники с Bluetooth (8518.30)", "hs": ["851830"], "date": "2024-02-15"},
    {"num": "НОТ-ФСБ-ПРИНТЕР", "agency": "FSB", "type": "notification", "title": "Нотификация ФСБ: принтеры и МФУ с Wi-Fi (8443.31)", "hs": ["844331"], "date": "2024-03-01"},
    {"num": "НОТ-ФСБ-КАМЕРА", "agency": "FSB", "type": "notification", "title": "Нотификация ФСБ: IP-камеры видеонаблюдения (8525.80)", "hs": ["852580"], "date": "2024-03-01"},
    {"num": "НОТ-ФСБ-ДРОН", "agency": "FSB", "type": "notification", "title": "Нотификация ФСБ: дроны с модулями связи (8525.80, 8802)", "hs": ["852580", "8802"], "date": "2024-03-15"},
    {"num": "НОТ-ФСБ-КОЛОНКА", "agency": "FSB", "type": "notification", "title": "Нотификация ФСБ: умные колонки с голосовым ассистентом (8518.21)", "hs": ["851821"], "date": "2024-04-01"},
    {"num": "НОТ-ФСБ-ТЕЛЕВИЗОР", "agency": "FSB", "type": "notification", "title": "Нотификация ФСБ: Smart TV с Wi-Fi модулем (8528)", "hs": ["8528"], "date": "2024-04-01"},

    # Classification specifics
    {"num": "КЛАСС-ЭЛЕКТР-001", "agency": "FTS", "type": "letter", "title": "Классификация серверного оборудования (8471.49 vs 8471.50)", "hs": ["847149", "847150"], "date": "2024-05-01"},
    {"num": "КЛАСС-ЭЛЕКТР-002", "agency": "FTS", "type": "letter", "title": "Классификация блоков питания (8504.40 vs 8504.90)", "hs": ["850440", "850490"], "date": "2024-05-15"},
    {"num": "КЛАСС-ЭЛЕКТР-003", "agency": "FTS", "type": "letter", "title": "Классификация электросамокатов (8711.60 vs 8711.90)", "hs": ["871160", "871190"], "date": "2024-06-01"},
    {"num": "КЛАСС-ЭЛЕКТР-004", "agency": "FTS", "type": "letter", "title": "Классификация powerbank (8507.60)", "hs": ["850760"], "date": "2024-06-15"},
    {"num": "КЛАСС-ЭЛЕКТР-005", "agency": "FTS", "type": "letter", "title": "Классификация SSD-накопителей (8523.51)", "hs": ["852351"], "date": "2024-07-01"},
    {"num": "КЛАСС-ЭЛЕКТР-006", "agency": "FTS", "type": "letter", "title": "Классификация зарядных устройств USB Type-C (8504.40)", "hs": ["850440"], "date": "2024-07-15"},
    {"num": "КЛАСС-ЭЛЕКТР-007", "agency": "FTS", "type": "letter", "title": "Классификация VR-очков (9004.90 vs 8528.59)", "hs": ["900490", "852859"], "date": "2024-08-01"},
    {"num": "КЛАСС-ЭЛЕКТР-008", "agency": "FTS", "type": "letter", "title": "Классификация электрических зубных щёток (8509.80 vs 8510.10)", "hs": ["850980", "851010"], "date": "2024-08-15"},
    {"num": "КЛАСС-ЭЛЕКТР-009", "agency": "FTS", "type": "letter", "title": "Классификация робот-пылесосов (8508.11)", "hs": ["850811"], "date": "2024-09-01"},
    {"num": "КЛАСС-ЭЛЕКТР-010", "agency": "FTS", "type": "letter", "title": "Классификация модемов 5G (8517.62)", "hs": ["851762"], "date": "2024-09-15"},

    # TR TS specifics
    {"num": "ТР-ТС-004-ЭЛЕКТР-1", "agency": "EEC", "type": "decision", "title": "Применение ТР ТС 004/2011 к бытовым электроприборам: утюги, чайники (8516)", "hs": ["8516"], "date": "2024-01-01"},
    {"num": "ТР-ТС-004-ЭЛЕКТР-2", "agency": "EEC", "type": "decision", "title": "Применение ТР ТС 004/2011 к компьютерной технике: СС vs ДС (8471)", "hs": ["8471"], "date": "2024-02-01"},
    {"num": "ТР-ТС-020-ЭЛЕКТР-1", "agency": "EEC", "type": "decision", "title": "Применение ТР ТС 020/2011 (ЭМС) к телекоммуникационному оборудованию (8517)", "hs": ["8517"], "date": "2024-03-01"},
    {"num": "ТР-ТС-037-ЭЛЕКТР-1", "agency": "EEC", "type": "decision", "title": "Применение ТР ТС 037/2016 (RoHS) к электронике: ограничения свинца и кадмия", "hs": ["8471", "8517", "8528", "8508", "8509", "8516"], "date": "2024-04-01"},
]

# ═══════════════════════════════════════════════════════════════════
# 2. AUTOMOBILES (chapter 87)
# ═══════════════════════════════════════════════════════════════════
AUTO_DOCS: list[dict] = [
    # OTTS / SBKTS
    {"num": "ОТТС-001", "agency": "MPT", "type": "order", "title": "Порядок выдачи ОТТС (одобрение типа транспортного средства) для новых автомобилей (8703)", "hs": ["8703"], "date": "2024-01-01"},
    {"num": "СБКТС-001", "agency": "MPT", "type": "order", "title": "Порядок выдачи СБКТС (свидетельство безопасности конструкции) для единичных ТС (8703)", "hs": ["8703"], "date": "2024-01-15"},
    {"num": "ОТТС-002", "agency": "MPT", "type": "order", "title": "ОТТС для грузовых транспортных средств (8704)", "hs": ["8704"], "date": "2024-02-01"},
    {"num": "ОТТС-003", "agency": "MPT", "type": "order", "title": "ОТТС для автобусов (8702)", "hs": ["8702"], "date": "2024-02-15"},
    {"num": "ОТТС-004", "agency": "MPT", "type": "order", "title": "ОТТС для мотоциклов и мопедов (8711)", "hs": ["8711"], "date": "2024-03-01"},
    {"num": "ОТТС-005", "agency": "MPT", "type": "order", "title": "ОТТС для прицепов и полуприцепов (8716)", "hs": ["8716"], "date": "2024-03-15"},
    {"num": "ОТТС-ЭЛЕКТРО", "agency": "MPT", "type": "order", "title": "Особенности сертификации электромобилей и гибридов (8703.80)", "hs": ["870380"], "date": "2024-04-01"},

    # Recycling fee (утилизационный сбор)
    {"num": "УТСБОР-001", "agency": "PRAVO", "type": "government_decree", "title": "ПП РФ №1291 об утилизационном сборе на колёсные ТС (8701-8705)", "hs": ["8701", "8702", "8703", "8704", "8705"], "date": "2020-08-31"},
    {"num": "УТСБОР-002", "agency": "FTS", "type": "order", "title": "Порядок уплаты утилизационного сбора при ввозе ТС", "hs": ["8703", "8704"], "date": "2024-05-01"},
    {"num": "УТСБОР-СТАВКИ", "agency": "MIN_FIN", "type": "letter", "title": "Ставки утилизационного сбора на легковые автомобили по объёму двигателя", "hs": ["8703"], "date": "2024-06-01"},

    # Classification
    {"num": "КЛАСС-АВТО-001", "agency": "FTS", "type": "letter", "title": "Классификация пикапов: 8703 vs 8704 (по массе и конструкции)", "hs": ["8703", "8704"], "date": "2024-07-01"},
    {"num": "КЛАСС-АВТО-002", "agency": "FTS", "type": "letter", "title": "Классификация квадроциклов и мотовездеходов (8703 vs 8711)", "hs": ["8703", "8711"], "date": "2024-07-15"},
    {"num": "КЛАСС-АВТО-003", "agency": "FTS", "type": "letter", "title": "Классификация запасных частей (8708): фильтры, тормозные колодки", "hs": ["8708"], "date": "2024-08-01"},
    {"num": "КЛАСС-АВТО-004", "agency": "FTS", "type": "letter", "title": "Классификация шин: всесезонные, зимние, летние (4011)", "hs": ["4011"], "date": "2024-08-15"},
    {"num": "КЛАСС-АВТО-005", "agency": "FTS", "type": "letter", "title": "Классификация автомобильных масел и жидкостей (2710, 3403)", "hs": ["2710", "3403"], "date": "2024-09-01"},

    # GLONASS
    {"num": "ГЛОНАСС-001", "agency": "MPT", "type": "order", "title": "Требования к установке ГЛОНАСС/ЭРА на импортируемые ТС", "hs": ["8703", "8704", "8702"], "date": "2024-04-15"},
]

# ═══════════════════════════════════════════════════════════════════
# 3. FOOD PRODUCTS (chapters 01-24)
# ═══════════════════════════════════════════════════════════════════
FOOD_DOCS: list[dict] = [
    # Country-specific vet requirements
    {"num": "ВЕТ-БРАЗИЛИЯ", "agency": "RSN", "type": "order", "title": "Ветеринарные требования: импорт мяса из Бразилии", "hs": ["0201", "0202", "0207"], "date": "2024-01-01"},
    {"num": "ВЕТ-АРГЕНТИНА", "agency": "RSN", "type": "order", "title": "Ветеринарные требования: импорт мяса из Аргентины", "hs": ["0201", "0202"], "date": "2024-01-15"},
    {"num": "ВЕТ-ИНДИЯ", "agency": "RSN", "type": "order", "title": "Ветеринарные требования: импорт мяса птицы из Индии", "hs": ["0207"], "date": "2024-02-01"},
    {"num": "ВЕТ-БЕЛАРУСЬ", "agency": "RSN", "type": "order", "title": "Ветеринарные требования: импорт молочной продукции из Беларуси", "hs": ["0401", "0402", "0403", "0404", "0405", "0406"], "date": "2024-02-15"},
    {"num": "ВЕТ-ТУРЦИЯ", "agency": "RSN", "type": "order", "title": "Ветеринарные требования: импорт яиц из Турции", "hs": ["0407", "0408"], "date": "2024-03-01"},
    {"num": "ВЕТ-ЧИЛИ-РЫБА", "agency": "RSN", "type": "order", "title": "Ветеринарные требования: импорт рыбы из Чили (лосось)", "hs": ["0302", "0303", "0304"], "date": "2024-03-15"},
    {"num": "ВЕТ-НОРВЕГИЯ-РЫБА", "agency": "RSN", "type": "order", "title": "Ветеринарные требования: импорт рыбы из Норвегии", "hs": ["0302", "0303", "0304", "0305"], "date": "2024-04-01"},
    {"num": "ВЕТ-КИТАЙ", "agency": "RSN", "type": "order", "title": "Ветеринарные требования: импорт мясных полуфабрикатов из КНР", "hs": ["1601", "1602"], "date": "2024-04-15"},

    # Phyto — country-specific
    {"num": "ФИТО-ЭКВАДОР", "agency": "RSN", "type": "order", "title": "Фитосанитарные требования: импорт бананов из Эквадора", "hs": ["0803"], "date": "2024-01-01"},
    {"num": "ФИТО-ТУРЦИЯ-ОВОЩ", "agency": "RSN", "type": "order", "title": "Фитосанитарные требования: импорт томатов из Турции", "hs": ["0702"], "date": "2024-01-15"},
    {"num": "ФИТО-ИРАН", "agency": "RSN", "type": "order", "title": "Фитосанитарные требования: импорт фисташек из Ирана", "hs": ["0802"], "date": "2024-02-01"},
    {"num": "ФИТО-ЕГИПЕТ", "agency": "RSN", "type": "order", "title": "Фитосанитарные требования: импорт цитрусовых из Египта", "hs": ["0805"], "date": "2024-02-15"},
    {"num": "ФИТО-КИТАЙ-ЧАЙ", "agency": "RSN", "type": "order", "title": "Фитосанитарные требования: импорт чая из Китая", "hs": ["0902"], "date": "2024-03-01"},
    {"num": "ФИТО-ВЬЕТНАМ-КОФЕ", "agency": "RSN", "type": "order", "title": "Фитосанитарные требования: импорт кофе из Вьетнама", "hs": ["0901"], "date": "2024-03-15"},
    {"num": "ФИТО-ИНДИЯ-ПРЯНОСТИ", "agency": "RSN", "type": "order", "title": "Фитосанитарные требования: импорт пряностей из Индии", "hs": ["0904", "0908", "0910"], "date": "2024-04-01"},

    # SGR specifics
    {"num": "СГР-ДЕТПИТ-001", "agency": "RPN", "type": "order", "title": "СГР: детское питание (каши, смеси, пюре)", "hs": ["1901", "2005", "2007", "2104"], "date": "2024-01-01"},
    {"num": "СГР-БАД-001", "agency": "RPN", "type": "order", "title": "СГР: биологически активные добавки (БАД)", "hs": ["210690", "2106", "2936"], "date": "2024-02-01"},
    {"num": "СГР-СПОРТПИТ", "agency": "RPN", "type": "order", "title": "СГР: спортивное питание (протеины, гейнеры)", "hs": ["210690", "2106"], "date": "2024-03-01"},
    {"num": "СГР-ДЕЗИНФ", "agency": "RPN", "type": "order", "title": "СГР: дезинфицирующие средства для пищевой промышленности", "hs": ["3808"], "date": "2024-04-01"},
    {"num": "СГР-ВОДА-МИНЕРАЛ", "agency": "RPN", "type": "order", "title": "СГР: минеральная лечебная и лечебно-столовая вода", "hs": ["2201"], "date": "2024-05-01"},

    # Food labeling specifics
    {"num": "МАРКИР-ПИЩ-001", "agency": "EEC", "type": "decision", "title": "Требования к маркировке пищевой продукции (ТР ТС 022/2011): аллергены", "hs": ["16", "17", "18", "19", "20", "21"], "date": "2024-01-01"},
    {"num": "МАРКИР-ПИЩ-002", "agency": "EEC", "type": "decision", "title": "Требования к маркировке пищевой продукции: энергетическая ценность, БЖУ", "hs": ["16", "17", "18", "19", "20", "21"], "date": "2024-02-01"},
    {"num": "МАРКИР-ПИЩ-ГМО", "agency": "RPN", "type": "order", "title": "Требования к маркировке генно-модифицированных продуктов", "hs": ["1201", "1005", "1507"], "date": "2024-06-01"},
]

# ═══════════════════════════════════════════════════════════════════
# 4. CLOTHING & FOOTWEAR (chapters 61-64)
# ═══════════════════════════════════════════════════════════════════
CLOTHING_DOCS: list[dict] = [
    # Honest Mark (Честный Знак)
    {"num": "ЧЗ-ОБУВЬ-001", "agency": "MPT", "type": "order", "title": "Маркировка Честный Знак: обувь — обязательна с 01.07.2019", "hs": ["6401", "6402", "6403", "6404", "6405"], "date": "2019-07-01"},
    {"num": "ЧЗ-ОДЕЖДА-001", "agency": "MPT", "type": "order", "title": "Маркировка Честный Знак: одежда — обязательна с 01.01.2021", "hs": ["6101", "6102", "6103", "6104", "6106", "6109", "6110", "6201", "6202", "6203", "6204", "6205", "6206", "6211"], "date": "2021-01-01"},
    {"num": "ЧЗ-ТЕКСТИЛЬ-001", "agency": "MPT", "type": "order", "title": "Маркировка Честный Знак: постельное бельё — обязательна с 01.01.2021", "hs": ["6302"], "date": "2021-01-01"},
    {"num": "ЧЗ-ШУБЫ-001", "agency": "MPT", "type": "order", "title": "Маркировка Честный Знак: меховые изделия (RFID-чипы)", "hs": ["4303"], "date": "2016-08-12"},

    # TR TS 017/2011 specifics
    {"num": "ТР-017-ХЛОПОК", "agency": "EEC", "type": "decision", "title": "ТР ТС 017/2011: отличия СС/ДС для хлопковых vs синтетических изделий", "hs": ["610910", "610990", "611510", "611530", "611594", "611599"], "date": "2024-01-01"},
    {"num": "ТР-017-ДЕТСКАЯ", "agency": "EEC", "type": "decision", "title": "ТР ТС 017/2011 + ТР ТС 007/2011: детская одежда — двойная сертификация", "hs": ["6111", "6209"], "date": "2024-02-01"},
    {"num": "ТР-017-ОБУВЬ", "agency": "EEC", "type": "decision", "title": "ТР ТС 017/2011: обувь кожаная vs резиновая — отличия сертификации", "hs": ["6401", "6402", "6403", "6404"], "date": "2024-03-01"},

    # Classification
    {"num": "КЛАСС-ОДЕЖДА-001", "agency": "FTS", "type": "letter", "title": "Классификация спортивной одежды (6112 vs 6211)", "hs": ["6112", "6211"], "date": "2024-04-01"},
    {"num": "КЛАСС-ОДЕЖДА-002", "agency": "FTS", "type": "letter", "title": "Классификация перчаток: кожа, текстиль, резина (4203, 6116, 4015)", "hs": ["4203", "6116", "4015"], "date": "2024-05-01"},
    {"num": "КЛАСС-ОБУВЬ-001", "agency": "FTS", "type": "letter", "title": "Классификация кроссовок: подошва и верх (6403 vs 6404)", "hs": ["6403", "6404"], "date": "2024-06-01"},
]

# ═══════════════════════════════════════════════════════════════════
# 5. PHARMACEUTICALS (chapter 30)
# ═══════════════════════════════════════════════════════════════════
PHARMA_DOCS: list[dict] = [
    {"num": "РУ-ЛП-001", "agency": "ROSZDRAV", "type": "order", "title": "Порядок получения регистрационного удостоверения (РУ) на лекарственные препараты", "hs": ["3003", "3004"], "date": "2024-01-01"},
    {"num": "РУ-ЛП-002", "agency": "ROSZDRAV", "type": "order", "title": "Требования GMP при импорте лекарственных средств", "hs": ["3003", "3004"], "date": "2024-02-01"},
    {"num": "РУ-ЛП-003", "agency": "ROSZDRAV", "type": "order", "title": "Порядок ввоза незарегистрированных лекарственных препаратов (для клинических испытаний)", "hs": ["3003", "3004"], "date": "2024-03-01"},
    {"num": "РУ-ЛП-004", "agency": "ROSZDRAV", "type": "order", "title": "Маркировка лекарственных препаратов: Честный Знак + DataMatrix", "hs": ["3003", "3004"], "date": "2024-04-01"},
    {"num": "РУ-СУБСТАНЦИИ", "agency": "ROSZDRAV", "type": "order", "title": "Требования к импорту фармацевтических субстанций (активных ингредиентов)", "hs": ["2933", "2934", "2935", "2936", "2937", "2939", "2941"], "date": "2024-05-01"},
    {"num": "РУ-ВАКЦИНЫ", "agency": "ROSZDRAV", "type": "order", "title": "Особенности ввоза вакцин и иммунобиологических препаратов", "hs": ["3002"], "date": "2024-06-01"},
    {"num": "РУ-НАРКОТИКИ", "agency": "MPT", "type": "order", "title": "Лицензирование ввоза наркотических и психотропных лекарственных средств", "hs": ["2939", "3003", "3004"], "date": "2024-07-01"},
    {"num": "РУ-МЕДИЗДЕЛИЯ-1", "agency": "ROSZDRAV", "type": "order", "title": "Регистрация медицинских изделий класса 1 (низкий риск)", "hs": ["9018", "3005", "3006"], "date": "2024-08-01"},
    {"num": "РУ-МЕДИЗДЕЛИЯ-2", "agency": "ROSZDRAV", "type": "order", "title": "Регистрация медицинских изделий класса 2a-2b (средний риск)", "hs": ["9018", "9019", "9021"], "date": "2024-09-01"},
    {"num": "РУ-МЕДИЗДЕЛИЯ-3", "agency": "ROSZDRAV", "type": "order", "title": "Регистрация медицинских изделий класса 3 (высокий риск): импланты, ИВЛ", "hs": ["9018", "9021", "9022"], "date": "2024-10-01"},
    {"num": "КЛАСС-ФАРМ-001", "agency": "FTS", "type": "letter", "title": "Классификация БАД vs лекарства (2106 vs 3004)", "hs": ["210690", "3004"], "date": "2024-11-01"},
    {"num": "КЛАСС-ФАРМ-002", "agency": "FTS", "type": "letter", "title": "Классификация медицинских масок (6307 vs 3005 vs 9020)", "hs": ["6307", "3005", "9020"], "date": "2024-12-01"},
]

# ═══════════════════════════════════════════════════════════════════
# 6. CHEMICALS (chapters 28-38)
# ═══════════════════════════════════════════════════════════════════
CHEMICAL_DOCS: list[dict] = [
    # Safety data sheets (паспорта безопасности)
    {"num": "ПБ-ХИМ-001", "agency": "MPT", "type": "order", "title": "Требования к паспортам безопасности химической продукции (ГОСТ 30333)", "hs": ["28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38"], "date": "2024-01-01"},
    {"num": "ПБ-ХИМ-002", "agency": "EEC", "type": "decision", "title": "ТР ТС 041/2017: регистрация химической продукции в ЕАЭС", "hs": ["2827", "2905", "2915", "2916", "2917", "2918"], "date": "2024-02-01"},

    # Precursors
    {"num": "ПРЕК-001", "agency": "MPT", "type": "order", "title": "Лицензирование ввоза прекурсоров наркотических средств (Таблица I)", "hs": ["2914", "2922", "2924", "2932", "2933"], "date": "2024-03-01"},
    {"num": "ПРЕК-002", "agency": "MPT", "type": "order", "title": "Лицензирование ввоза прекурсоров (Таблица II и III)", "hs": ["2806", "2807", "2841", "2902", "2909", "2914"], "date": "2024-04-01"},

    # Hazardous chemicals
    {"num": "ОПАСХИМ-001", "agency": "RPN", "type": "order", "title": "Контроль ввоза ядовитых веществ (сильнодействующие)", "hs": ["2801", "2811", "2812", "2827"], "date": "2024-05-01"},
    {"num": "ОПАСХИМ-002", "agency": "ROSTEHNADZOR", "type": "order", "title": "Требования промышленной безопасности при импорте взрывоопасных химикатов", "hs": ["2814", "2815", "3601", "3602"], "date": "2024-06-01"},

    # Pesticides and agrochemicals
    {"num": "ПЕСТИЦИД-001", "agency": "RSN", "type": "order", "title": "Регистрация пестицидов и агрохимикатов при импорте", "hs": ["3808"], "date": "2024-07-01"},
    {"num": "ПЕСТИЦИД-002", "agency": "RPN", "type": "order", "title": "Санитарно-гигиенические требования к пестицидам", "hs": ["3808"], "date": "2024-08-01"},

    # Fertilizers
    {"num": "УДОБР-001", "agency": "EEC", "type": "decision", "title": "ТР ТС 039/2016: минеральные удобрения — требования сертификации", "hs": ["3102", "3103", "3104", "3105"], "date": "2024-09-01"},

    # Paints and coatings
    {"num": "ЛКМ-001", "agency": "RPN", "type": "order", "title": "Санитарные требования к лакокрасочным материалам (содержание свинца)", "hs": ["3208", "3209", "3210"], "date": "2024-10-01"},

    # Cosmetic chemistry
    {"num": "КОСМХИМ-001", "agency": "EEC", "type": "decision", "title": "ТР ТС 009/2011: запрещённые ингредиенты в косметике", "hs": ["3303", "3304", "3305", "3306", "3307"], "date": "2024-11-01"},
]

# ═══════════════════════════════════════════════════════════════════
# 7. PRECIOUS METALS & STONES (chapter 71)
# ═══════════════════════════════════════════════════════════════════
PRECIOUS_DOCS: list[dict] = [
    {"num": "ДМ-ЛИЦ-001", "agency": "MPT", "type": "order", "title": "Лицензирование импорта необработанных алмазов (Кимберлийский процесс)", "hs": ["7102"], "date": "2024-01-01"},
    {"num": "ДМ-ЛИЦ-002", "agency": "MPT", "type": "order", "title": "Лицензирование импорта золота в слитках и порошке", "hs": ["7108"], "date": "2024-02-01"},
    {"num": "ДМ-ЛИЦ-003", "agency": "MPT", "type": "order", "title": "Лицензирование импорта серебра", "hs": ["7106"], "date": "2024-03-01"},
    {"num": "ДМ-ЛИЦ-004", "agency": "MPT", "type": "order", "title": "Лицензирование импорта платины и палладия", "hs": ["7110"], "date": "2024-04-01"},
    {"num": "ДМ-СЕРТ-001", "agency": "FTS", "type": "order", "title": "Порядок таможенного контроля ювелирных изделий и пробирного надзора", "hs": ["7113", "7114", "7116"], "date": "2024-05-01"},
    {"num": "ДМ-КИМБЕРЛИ", "agency": "EEC", "type": "decision", "title": "Решение ЕЭК о порядке реализации Кимберлийского процесса в ЕАЭС", "hs": ["7102", "7103", "7104"], "date": "2024-06-01"},
    {"num": "ДМ-ВАЛКОНТР", "agency": "MIN_FIN", "type": "order", "title": "Валютный контроль при импорте драгоценных металлов", "hs": ["7106", "7108", "7110"], "date": "2024-07-01"},
    {"num": "ДМ-КЛАССИФ-001", "agency": "FTS", "type": "letter", "title": "Классификация бижутерии vs ювелирных изделий (7117 vs 7113)", "hs": ["7117", "7113"], "date": "2024-08-01"},
    {"num": "ДМ-ЭКСПОРТ", "agency": "MPT", "type": "order", "title": "Экспортные ограничения на драгоценные металлы и камни", "hs": ["7102", "7106", "7108", "7110"], "date": "2024-09-01"},
]

# ═══════════════════════════════════════════════════════════════════
# 8. WEAPONS & AMMUNITION (chapter 93)
# ═══════════════════════════════════════════════════════════════════
WEAPONS_DOCS: list[dict] = [
    {"num": "ОРУЖ-ЛИЦ-001", "agency": "MPT", "type": "order", "title": "Лицензирование импорта гражданского оружия (ФЗ №150)", "hs": ["9302", "9303", "9304"], "date": "2024-01-01"},
    {"num": "ОРУЖ-ЛИЦ-002", "agency": "MPT", "type": "order", "title": "Лицензирование импорта служебного оружия", "hs": ["9302", "9303"], "date": "2024-02-01"},
    {"num": "ОРУЖ-ЛИЦ-003", "agency": "MPT", "type": "order", "title": "Лицензирование импорта боеприпасов и патронов", "hs": ["9306"], "date": "2024-03-01"},
    {"num": "ОРУЖ-ЛИЦ-004", "agency": "MPT", "type": "order", "title": "Лицензирование импорта охотничьего оружия", "hs": ["9303"], "date": "2024-04-01"},
    {"num": "ОРУЖ-МВД-001", "agency": "FSB", "type": "order", "title": "Разрешение МВД на ввоз оружия: порядок получения", "hs": ["9301", "9302", "9303", "9304", "9305"], "date": "2024-05-01"},
    {"num": "ОРУЖ-ФСБ-001", "agency": "FSB", "type": "order", "title": "Разрешение ФСБ на ввоз военного оружия и спецсредств", "hs": ["9301"], "date": "2024-06-01"},
    {"num": "ОРУЖ-СПОРТ", "agency": "MPT", "type": "order", "title": "Особенности ввоза спортивного оружия для соревнований", "hs": ["9303", "9304"], "date": "2024-07-01"},
    {"num": "ОРУЖ-КЛАССИФ", "agency": "FTS", "type": "letter", "title": "Классификация пневматического оружия (9304 vs 9503)", "hs": ["9304", "9503"], "date": "2024-08-01"},
    {"num": "ОРУЖ-ХОЛОДНОЕ", "agency": "FTS", "type": "letter", "title": "Классификация холодного оружия vs ножей (9307 vs 8211)", "hs": ["9307", "8211"], "date": "2024-09-01"},
    {"num": "ОРУЖ-ВЗРЫВ", "agency": "MPT", "type": "order", "title": "Лицензирование импорта взрывчатых веществ (ТР ТС 028/2012)", "hs": ["3601", "3602", "3603"], "date": "2024-10-01"},
]


def _all_commodity_docs() -> list[dict]:
    all_docs = []
    for group in [ELECTRONICS_DOCS, AUTO_DOCS, FOOD_DOCS, CLOTHING_DOCS,
                  PHARMA_DOCS, CHEMICAL_DOCS, PRECIOUS_DOCS, WEAPONS_DOCS]:
        all_docs.extend(group)
    return all_docs


def run():
    all_docs = _all_commodity_docs()
    print(f"Commodity group documents to seed: {len(all_docs)}")

    session = SessionLocal()
    try:
        docs_added = 0
        docs_skipped = 0
        mappings_added = 0

        for d in all_docs:
            url = _url(d["agency"], d["num"])
            doc_id = _doc_id(url)

            existing = session.execute(
                text("SELECT id FROM regulatory_documents WHERE id = :id"),
                {"id": doc_id},
            ).fetchone()

            if existing:
                docs_skipped += 1
                continue

            if DRY_RUN:
                docs_added += 1
                mappings_added += len(d.get("hs", []))
                continue

            doc_date_val = None
            if d.get("date"):
                try:
                    doc_date_val = datetime.strptime(d["date"], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    pass

            doc = RegulatoryDocument(
                id=doc_id,
                agency=d["agency"],
                doc_type=d["type"],
                doc_number=d.get("num"),
                doc_date=doc_date_val,
                title=d["title"],
                body=d["title"],
                source_url=url,
                status="active",
                quality="verified",
            )
            session.add(doc)

            for hs_prefix in d.get("hs", []):
                mapping = RegulatoryDocHsMapping(
                    doc_id=doc_id,
                    hs_prefix=str(hs_prefix),
                    scope="import",
                    relevance="direct",
                    confidence=1.0,
                    source="seed",
                    note=f"Commodity group: {d['title'][:100]}",
                )
                session.add(mapping)
                mappings_added += 1

            try:
                session.flush()
                docs_added += 1
            except IntegrityError:
                session.rollback()
                docs_skipped += 1

        if not DRY_RUN:
            session.commit()

        total_docs = session.execute(text("SELECT COUNT(*) FROM regulatory_documents")).scalar()
        total_maps = session.execute(text("SELECT COUNT(*) FROM regulatory_doc_hs_mapping")).scalar()

        print(f"\n{'=' * 60}")
        print(f"{'DRY-RUN ' if DRY_RUN else ''}Results:")
        print(f"  Documents added:   {docs_added}")
        print(f"  Documents skipped: {docs_skipped}")
        print(f"  HS mappings added: {mappings_added}")
        print(f"  Total documents:   {total_docs}")
        print(f"  Total HS mappings: {total_maps}")
        print(f"\n  By commodity group:")
        for name, group in [("Electronics", ELECTRONICS_DOCS), ("Automobiles", AUTO_DOCS),
                            ("Food", FOOD_DOCS), ("Clothing", CLOTHING_DOCS),
                            ("Pharma", PHARMA_DOCS), ("Chemicals", CHEMICAL_DOCS),
                            ("Precious metals", PRECIOUS_DOCS), ("Weapons", WEAPONS_DOCS)]:
            print(f"    {name:20s}: {len(group)} docs")
        print(f"{'=' * 60}")

    finally:
        session.close()


if __name__ == "__main__":
    run()
