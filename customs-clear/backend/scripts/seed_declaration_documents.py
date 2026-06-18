#!/usr/bin/env python3
"""Seed declaration_documents — required documents for customs declaration.

Categories:
  - general: общие документы (для всех товаров)
  - transport: транспортные документы
  - commercial: коммерческие документы
  - conformity: документы соответствия (сертификаты, декларации)
  - special: специальные (лицензии, разрешения)
  - origin: документы о происхождении
  - payment: платёжные документы

Usage:
    cd customs-clear/backend
    python3 -m scripts.seed_declaration_documents [--dry-run]
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text
from app.db import SessionLocal, engine, Base

DRY_RUN = "--dry-run" in sys.argv

# ═══════════════════════════════════════════════════════════════════
# Universal documents (apply to all HS codes via prefix "")
# ═══════════════════════════════════════════════════════════════════
UNIVERSAL = [
    {"type": "ДТ", "name": "Декларация на товары (форма ДТ)", "mandatory": True,
     "cat": "general", "legal": "ТК ЕАЭС ст. 104, 105; Решение КТС от 20.05.2010 №257"},
    {"type": "КТС", "name": "Корректировка таможенной стоимости (КТС-1, КТС-2)", "mandatory": False,
     "cat": "general", "legal": "ТК ЕАЭС ст. 313",
     "cond": "При корректировке таможенной стоимости"},
    {"type": "ДТС", "name": "Декларация таможенной стоимости (ДТС-1 или ДТС-2)", "mandatory": True,
     "cat": "general", "legal": "ТК ЕАЭС ст. 105 п. 4; Решение КТС от 20.09.2010 №376"},
    {"type": "invoice", "name": "Инвойс (коммерческий счёт)", "mandatory": True,
     "cat": "commercial", "legal": "ТК ЕАЭС ст. 108 п. 1"},
    {"type": "contract", "name": "Внешнеторговый контракт (договор купли-продажи)", "mandatory": True,
     "cat": "commercial", "legal": "ТК ЕАЭС ст. 108 п. 1"},
    {"type": "packing_list", "name": "Упаковочный лист", "mandatory": True,
     "cat": "commercial", "legal": "ТК ЕАЭС ст. 108"},
    {"type": "CMR", "name": "Международная товарно-транспортная накладная (CMR)", "mandatory": False,
     "cat": "transport", "legal": "Конвенция CMR 1956, ТК ЕАЭС ст. 108",
     "cond": "При автоперевозке"},
    {"type": "AWB", "name": "Авиагрузовая накладная (AWB/HAWB)", "mandatory": False,
     "cat": "transport", "legal": "Варшавская конвенция, ТК ЕАЭС ст. 108",
     "cond": "При авиаперевозке"},
    {"type": "B/L", "name": "Коносамент (Bill of Lading)", "mandatory": False,
     "cat": "transport", "legal": "Гаагские правила, ТК ЕАЭС ст. 108",
     "cond": "При морской перевозке"},
    {"type": "railway", "name": "Железнодорожная накладная СМГС/ЦИМ", "mandatory": False,
     "cat": "transport", "legal": "СМГС/ЦИМ, ТК ЕАЭС ст. 108",
     "cond": "При ж/д перевозке"},
    {"type": "insurance", "name": "Страховой полис/сертификат на груз", "mandatory": False,
     "cat": "commercial", "legal": "ТК ЕАЭС ст. 108",
     "cond": "При страховании груза (для подтверждения стоимости)"},
    {"type": "passport_tx", "name": "Паспорт сделки / контракт на учёте в банке", "mandatory": False,
     "cat": "payment", "legal": "Инструкция ЦБ РФ №181-И",
     "cond": "При сумме контракта ≥ 3 млн руб (импорт)"},
    {"type": "payment_order", "name": "Платёжное поручение на уплату таможенных платежей", "mandatory": True,
     "cat": "payment", "legal": "ТК ЕАЭС ст. 60, 61"},
    {"type": "origin_cert", "name": "Сертификат о происхождении товара (форма СТ-1/А/EAV)", "mandatory": False,
     "cat": "origin", "legal": "Правила определения происхождения товаров ЕАЭС",
     "cond": "При применении тарифных преференций"},
    {"type": "TIN", "name": "ИНН / свидетельство о постановке на учёт", "mandatory": True,
     "cat": "general", "legal": "ТК ЕАЭС ст. 108"},
]

# ═══════════════════════════════════════════════════════════════════
# Category-specific documents (by HS prefix)
# ═══════════════════════════════════════════════════════════════════
SPECIFIC = [
    # ─── Продовольствие (01-24) ───
    {"hs": "02", "type": "vet_cert", "name": "Ветеринарный сертификат", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 034/2013, Решение КТС от 18.06.2010 №317"},
    {"hs": "02", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 034/2013)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 034/2013 «О безопасности мяса и мясной продукции»"},
    {"hs": "03", "type": "vet_cert", "name": "Ветеринарный сертификат на рыбу и морепродукты", "mandatory": True,
     "cat": "conformity", "legal": "ТР ЕАЭС 040/2016"},
    {"hs": "04", "type": "vet_cert", "name": "Ветеринарный сертификат (молочная продукция)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 033/2013 «О безопасности молока и молочной продукции»"},
    {"hs": "04", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 033/2013)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 033/2013"},
    {"hs": "08", "type": "phyto_cert", "name": "Фитосанитарный сертификат", "mandatory": True,
     "cat": "conformity", "legal": "ФЗ от 15.07.2000 №99-ФЗ «О карантине растений»"},
    {"hs": "10", "type": "phyto_cert", "name": "Фитосанитарный сертификат (зерно)", "mandatory": True,
     "cat": "conformity", "legal": "ФЗ от 15.07.2000 №99-ФЗ"},
    {"hs": "16", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 021/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 021/2011 «О безопасности пищевой продукции»"},
    {"hs": "19", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 021/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 021/2011"},
    {"hs": "20", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 021/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 021/2011"},
    {"hs": "22", "type": "license_alc", "name": "Лицензия на импорт алкогольной продукции", "mandatory": False,
     "cat": "special", "legal": "ФЗ от 22.11.1995 №171-ФЗ",
     "cond": "Для алкогольной продукции крепостью > 0.5%"},
    {"hs": "22", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 021/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 021/2011"},

    # ─── Химия, фармацевтика (28-40) ───
    {"hs": "30", "type": "reg_cert", "name": "Регистрационное удостоверение лекарственного средства", "mandatory": True,
     "cat": "special", "legal": "ФЗ от 12.04.2010 №61-ФЗ «Об обращении лекарственных средств»"},
    {"hs": "30", "type": "GMP_cert", "name": "Сертификат GMP (надлежащая производственная практика)", "mandatory": True,
     "cat": "conformity", "legal": "ФЗ от 12.04.2010 №61-ФЗ, Решение Совета ЕЭК от 03.11.2016 №78"},
    {"hs": "33", "type": "SGR", "name": "Свидетельство о государственной регистрации (СГР)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 009/2011 «О безопасности парфюмерно-косметической продукции»"},
    {"hs": "33", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 009/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 009/2011"},
    {"hs": "38", "type": "MSDS", "name": "Паспорт безопасности химической продукции (SDS/MSDS)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 030/2012, ГОСТ 30333-2007"},

    # ─── Текстиль (50-63) ───
    {"hs": "61", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 017/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 017/2011 «О безопасности продукции лёгкой промышленности»"},
    {"hs": "62", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 017/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 017/2011"},
    {"hs": "63", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 017/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 017/2011"},

    # ─── Детские товары (9503, 9504) ───
    {"hs": "9503", "type": "cert_conform", "name": "Сертификат соответствия (ТР ТС 008/2011 «О безопасности игрушек»)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 008/2011"},
    {"hs": "9503", "type": "SGR", "name": "Свидетельство о государственной регистрации (для детей до 3 лет)", "mandatory": False,
     "cat": "conformity", "legal": "ТР ТС 007/2011 «О безопасности продукции для детей»",
     "cond": "Для товаров, предназначенных для детей до 3 лет"},

    # ─── Электроника (84-85) ───
    {"hs": "84", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 004/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 004/2011 «О безопасности низковольтного оборудования»"},
    {"hs": "84", "type": "cert_emc", "name": "Сертификат ЭМС (ТР ТС 020/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 020/2011 «Электромагнитная совместимость»"},
    {"hs": "85", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 004/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 004/2011"},
    {"hs": "85", "type": "cert_emc", "name": "Сертификат ЭМС (ТР ТС 020/2011)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 020/2011"},
    {"hs": "8517", "type": "notification_crypto", "name": "Нотификация ФСБ о ввозе шифровального оборудования", "mandatory": False,
     "cat": "special", "legal": "ПП РФ от 16.04.2012 №313, Решение КТС от 21.04.2015 №30",
     "cond": "При наличии криптографических функций"},
    {"hs": "8517", "type": "cert_radio", "name": "Декларация о соответствии (ТР ЕАЭС 037/2016 радио)", "mandatory": False,
     "cat": "conformity", "legal": "ТР ЕАЭС 037/2016",
     "cond": "При наличии радиопередатчика (WiFi, Bluetooth, LTE)"},

    # ─── Транспортные средства (87) ───
    {"hs": "87", "type": "OTTC", "name": "Одобрение типа ТС (ОТТС) или СБКТС", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 018/2011 «О безопасности колёсных транспортных средств»"},
    {"hs": "87", "type": "ERA_GLONASS", "name": "Подтверждение оснащения ЭРА-ГЛОНАСС", "mandatory": False,
     "cat": "conformity", "legal": "ТР ТС 018/2011",
     "cond": "Для категорий M и N (легковые, грузовые)"},
    {"hs": "87", "type": "recycling_fee", "name": "Подтверждение уплаты утилизационного сбора", "mandatory": True,
     "cat": "payment", "legal": "ФЗ от 24.06.1998 №89-ФЗ, ПП РФ от 26.12.2013 №1291"},

    # ─── Медицинские изделия (90) ───
    {"hs": "9018", "type": "reg_med", "name": "Регистрационное удостоверение Росздравнадзора", "mandatory": True,
     "cat": "special", "legal": "ФЗ от 21.11.2011 №323-ФЗ, ПП РФ от 27.12.2012 №1416"},
    {"hs": "9019", "type": "reg_med", "name": "Регистрационное удостоверение медизделия", "mandatory": True,
     "cat": "special", "legal": "ПП РФ от 27.12.2012 №1416"},

    # ─── Оружие (93) ───
    {"hs": "93", "type": "license_weapon", "name": "Лицензия на ввоз оружия (Росгвардия)", "mandatory": True,
     "cat": "special", "legal": "ФЗ от 13.12.1996 №150-ФЗ «Об оружии»"},
    {"hs": "93", "type": "end_user_cert", "name": "Сертификат конечного пользователя", "mandatory": True,
     "cat": "special", "legal": "ФЗ от 19.07.1998 №114-ФЗ"},

    # ─── Драгоценные камни/металлы (71) ───
    {"hs": "71", "type": "cert_gohran", "name": "Заключение Гохрана / Пробирной палаты", "mandatory": False,
     "cat": "special", "legal": "ФЗ от 26.03.1998 №41-ФЗ «О драгоценных металлах»",
     "cond": "Для драгоценных металлов и камней"},

    # ─── Мебель (94) ───
    {"hs": "94", "type": "decl_conform", "name": "Декларация о соответствии (ТР ТС 025/2012 мебель)", "mandatory": True,
     "cat": "conformity", "legal": "ТР ТС 025/2012 «О безопасности мебельной продукции»"},

    # ─── Строительные материалы (68-70) ───
    {"hs": "69", "type": "cert_conform", "name": "Сертификат соответствия / пожарный сертификат", "mandatory": False,
     "cat": "conformity", "legal": "ФЗ от 22.07.2008 №123-ФЗ «Технический регламент о требованиях пожарной безопасности»",
     "cond": "Для отделочных и облицовочных материалов"},
]


def seed() -> dict[str, int]:
    from app.models.tnved import DeclarationDocument
    Base.metadata.create_all(engine, tables=[DeclarationDocument.__table__])

    inserted = 0
    with SessionLocal() as db:
        for docs, hs_prefix in [(UNIVERSAL, ""), *[(None, None)]]:
            pass

        for entry in UNIVERSAL:
            exists = db.execute(
                text("SELECT 1 FROM declaration_documents WHERE hs_prefix = '' AND doc_type = :dt AND doc_name = :dn"),
                {"dt": entry["type"], "dn": entry["name"]},
            ).fetchone()
            if exists:
                continue
            row = DeclarationDocument(
                hs_prefix="",
                doc_type=entry["type"],
                doc_name=entry["name"],
                is_mandatory=entry["mandatory"],
                condition=entry.get("cond", ""),
                legal_ref=entry["legal"],
                category=entry["cat"],
            )
            db.add(row)
            inserted += 1

        for entry in SPECIFIC:
            exists = db.execute(
                text("SELECT 1 FROM declaration_documents WHERE hs_prefix = :hs AND doc_type = :dt AND doc_name = :dn"),
                {"hs": entry["hs"], "dt": entry["type"], "dn": entry["name"]},
            ).fetchone()
            if exists:
                continue
            row = DeclarationDocument(
                hs_prefix=entry["hs"],
                doc_type=entry["type"],
                doc_name=entry["name"],
                is_mandatory=entry["mandatory"],
                condition=entry.get("cond", ""),
                legal_ref=entry["legal"],
                category=entry["cat"],
            )
            db.add(row)
            inserted += 1

        if DRY_RUN:
            db.rollback()
            print(f"[DRY RUN] Would insert {inserted} declaration documents")
        else:
            db.commit()
            print(f"Inserted {inserted} declaration documents")

        total = db.execute(text("SELECT COUNT(*) FROM declaration_documents")).scalar()
        by_cat = db.execute(text(
            "SELECT category, COUNT(*) FROM declaration_documents GROUP BY category ORDER BY category"
        )).fetchall()
        print(f"Total: {total}")
        for cat, c in by_cat:
            print(f"  {cat or 'universal'}: {c}")

    return {"inserted": inserted, "total": total}


if __name__ == "__main__":
    seed()
