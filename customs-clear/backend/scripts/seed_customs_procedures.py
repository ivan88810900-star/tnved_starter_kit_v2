#!/usr/bin/env python3
"""Seed customs_procedures with all major customs procedure codes.

Russian customs procedures follow the 4-character code system:
  - First 2 chars: procedure direction (ИМ=import, ЭК=export, ТТ=transit, etc.)
  - Last 2 digits: specific sub-procedure

Based on:
  - ТК ЕАЭС (Таможенный кодекс ЕАЭС) от 11.04.2017
  - Приказ ФТС России от 24.08.2018 № 1330
  - ФЗ-289 «О таможенном регулировании в РФ»

Usage:
    cd customs-clear/backend
    python3 -m scripts.seed_customs_procedures [--dry-run]
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
# Customs procedures definitions
# ═══════════════════════════════════════════════════════════════════
PROCEDURES = [
    # ─── IMPORT PROCEDURES ───
    {
        "procedure_code": "ИМ40",
        "name_ru": "Выпуск для внутреннего потребления",
        "direction": "import",
        "description": (
            "Основная процедура импорта. Товары приобретают статус товаров ЕАЭС "
            "после уплаты всех таможенных платежей и соблюдения запретов/ограничений. "
            "Товары свободно обращаются на территории ЕАЭС."
        ),
        "legal_ref": "ТК ЕАЭС ст. 134-139",
        "duty_applies": True,
        "vat_applies": True,
        "excise_applies": True,
        "customs_fee_applies": True,
        "time_limit_months": None,
        "documents_required": (
            "ДТ (декларация на товары); инвойс; транспортные документы; "
            "упаковочный лист; сертификат происхождения; контракт ВЭД; "
            "разрешительные документы (при наличии ограничений)"
        ),
        "conditions": "Уплата ввозной пошлины, НДС, акциза (при наличии), таможенного сбора",
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ИМ51",
        "name_ru": "Переработка на таможенной территории",
        "direction": "import",
        "description": (
            "Иностранные товары ввозятся для переработки (ремонт, сборка, обработка) "
            "с последующим вывозом продуктов переработки. Пошлина и НДС не уплачиваются "
            "при условии вывоза продуктов переработки в установленный срок."
        ),
        "legal_ref": "ТК ЕАЭС ст. 163-175",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": 36,
        "documents_required": (
            "ДТ; разрешение ФТС на переработку; контракт на переработку; "
            "нормы выхода продуктов переработки; обеспечение уплаты платежей"
        ),
        "conditions": (
            "Необходимо разрешение таможенного органа. Продукты переработки "
            "должны быть вывезены или помещены под иную процедуру в срок до 3 лет."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ИМ53",
        "name_ru": "Временный ввоз (допуск)",
        "direction": "import",
        "description": (
            "Иностранные товары ввозятся на ограниченный срок с полным или частичным "
            "освобождением от пошлин/налогов. Товары должны быть возвращены или "
            "помещены под иную процедуру. При частичном освобождении: 3% в месяц "
            "от суммы пошлин, которая подлежала бы уплате при ИМ40."
        ),
        "legal_ref": "ТК ЕАЭС ст. 219-229",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": 24,
        "documents_required": (
            "ДТ; обязательство об обратном вывозе; обеспечение уплаты платежей; "
            "документы, подтверждающие цель ввоза"
        ),
        "conditions": (
            "Полное освобождение: выставочные экспонаты, контейнеры, образцы, "
            "профессиональное оборудование. Частичное: 3%/мес от полной суммы платежей."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ИМ70",
        "name_ru": "Таможенный склад",
        "direction": "import",
        "description": (
            "Иностранные товары хранятся на таможенном складе без уплаты пошлин "
            "и налогов до 3 лет. По истечении срока товары помещаются под иную "
            "процедуру (ИМ40, ЭК10, реэкспорт и др.)."
        ),
        "legal_ref": "ТК ЕАЭС ст. 155-162",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": 36,
        "documents_required": (
            "ДТ; договор хранения с владельцем склада; документы на товар; "
            "транспортные документы"
        ),
        "conditions": (
            "Товары хранятся в неизменном виде. Допускаются операции по сохранению: "
            "осмотр, измерение, перемещение, инвентаризация."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ИМ78",
        "name_ru": "Уничтожение",
        "direction": "import",
        "description": (
            "Иностранные товары уничтожаются под таможенным контролем без уплаты "
            "ввозных пошлин и налогов. Применяется к товарам, утратившим "
            "потребительские свойства или запрещённым к обороту."
        ),
        "legal_ref": "ТК ЕАЭС ст. 242-247",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": None,
        "documents_required": (
            "ДТ; заключение о непригодности; акт уничтожения; "
            "разрешение уполномоченного органа"
        ),
        "conditions": (
            "Не допускается для: культурных ценностей, животных/растений из СИТЕС, "
            "товаров, принятых в залог. Отходы уничтожения помещаются под ИМ40."
        ),
        "hs_restrictions": "Запрещено: глава 97 (культурные ценности), позиции СИТЕС",
    },
    {
        "procedure_code": "ИМ90",
        "name_ru": "Отказ в пользу государства",
        "direction": "import",
        "description": (
            "Иностранные товары безвозмездно передаются в собственность государства — "
            "члена ЕАЭС без уплаты пошлин и налогов."
        ),
        "legal_ref": "ТК ЕАЭС ст. 248-252",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": False,
        "time_limit_months": None,
        "documents_required": (
            "ДТ; заявление об отказе в пользу государства; "
            "документы, подтверждающие право распоряжения товарами"
        ),
        "conditions": (
            "Расходы на уничтожение/утилизацию несёт декларант. "
            "Не допускается для товаров, запрещённых к обороту."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ИМ91",
        "name_ru": "Переработка для внутреннего потребления",
        "direction": "import",
        "description": (
            "Товары перерабатываются на территории ЕАЭС с уплатой пошлин по ставкам, "
            "применимым к продуктам переработки (а не к исходным товарам). "
            "Выгодно когда ставка на готовый продукт ниже."
        ),
        "legal_ref": "ТК ЕАЭС ст. 188-196",
        "duty_applies": True,
        "vat_applies": True,
        "excise_applies": True,
        "customs_fee_applies": True,
        "time_limit_months": 12,
        "documents_required": (
            "ДТ; разрешение ФТС на переработку; контракт; "
            "нормы выхода продуктов переработки"
        ),
        "conditions": (
            "Пошлина начисляется по ставке для продукта переработки. "
            "Перечень товаров устанавливается Комиссией ЕАЭС."
        ),
        "hs_restrictions": "Перечень товаров утверждается Решением Комиссии ЕАЭС",
    },
    {
        "procedure_code": "ИМ93",
        "name_ru": "Свободная таможенная зона (СТЗ)",
        "direction": "import",
        "description": (
            "Товары размещаются на территории СЭЗ/ОЭЗ без уплаты пошлин и налогов. "
            "При вывозе за пределы зоны помещаются под соответствующую процедуру."
        ),
        "legal_ref": "ТК ЕАЭС ст. 201-211",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": None,
        "documents_required": (
            "ДТ; соглашение о ведении деятельности в СЭЗ; "
            "регистрация в реестре резидентов ОЭЗ"
        ),
        "conditions": (
            "Действует на территории особых экономических зон. "
            "При выпуске в свободное обращение — платежи по ИМ40."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ИМ96",
        "name_ru": "Свободный склад",
        "direction": "import",
        "description": (
            "Товары хранятся и используются на свободном складе без уплаты "
            "пошлин и налогов. Допускаются операции по переработке."
        ),
        "legal_ref": "ТК ЕАЭС ст. 211-218",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": None,
        "documents_required": (
            "ДТ; лицензия на владение свободным складом; "
            "учётная документация склада"
        ),
        "conditions": "Владелец склада должен иметь лицензию ФТС",
        "hs_restrictions": "",
    },
    # ─── EXPORT PROCEDURES ───
    {
        "procedure_code": "ЭК10",
        "name_ru": "Экспорт",
        "direction": "export",
        "description": (
            "Основная процедура экспорта. Товары ЕАЭС вывозятся за пределы "
            "таможенной территории для постоянного нахождения. "
            "Вывозная пошлина уплачивается (при наличии). НДС по ставке 0%."
        ),
        "legal_ref": "ТК ЕАЭС ст. 140-143",
        "duty_applies": True,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": None,
        "documents_required": (
            "ДТ; контракт ВЭД; инвойс; транспортные документы; "
            "разрешительные документы (при ограничениях на вывоз); "
            "сертификат происхождения (при необходимости)"
        ),
        "conditions": (
            "Экспортные пошлины применяются к ограниченному перечню товаров "
            "(нефть, газ, лес, зерно и др.). НДС 0% подтверждается в течение 180 дней."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ЭК21",
        "name_ru": "Временный вывоз",
        "direction": "export",
        "description": (
            "Товары ЕАЭС временно вывозятся за пределы таможенной территории "
            "с освобождением от вывозных пошлин. Обязательство обратного ввоза."
        ),
        "legal_ref": "ТК ЕАЭС ст. 230-237",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": 24,
        "documents_required": (
            "ДТ; обязательство об обратном ввозе; обоснование временного вывоза"
        ),
        "conditions": (
            "Выставочные экспонаты, профессиональное оборудование, "
            "транспортные средства, товары для ремонта за рубежом."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ЭК23",
        "name_ru": "Переработка вне таможенной территории",
        "direction": "export",
        "description": (
            "Товары ЕАЭС вывозятся для переработки за рубежом (ремонт, модернизация) "
            "с последующим ввозом продуктов переработки. Пошлина — только "
            "на стоимость переработки."
        ),
        "legal_ref": "ТК ЕАЭС ст. 176-187",
        "duty_applies": True,
        "vat_applies": True,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": 24,
        "documents_required": (
            "ДТ; разрешение ФТС на переработку; контракт на переработку; "
            "нормы выхода; идентификация товаров в продуктах переработки"
        ),
        "conditions": (
            "Пошлина при обратном ввозе: только на стоимость переработки "
            "(разницу между стоимостью продуктов и исходных товаров). "
            "Для гарантийного ремонта — полное освобождение."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ЭК31",
        "name_ru": "Реэкспорт",
        "direction": "export",
        "description": (
            "Иностранные товары (ранее ввезённые) вывозятся обратно за пределы "
            "таможенной территории ЕАЭС. Возврат ранее уплаченных пошлин и налогов."
        ),
        "legal_ref": "ТК ЕАЭС ст. 238-241",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": None,
        "documents_required": (
            "ДТ; документы, подтверждающие иностранное происхождение; "
            "подтверждение уплаченных ранее платежей (для возврата)"
        ),
        "conditions": (
            "Применяется при возврате некачественных товаров, ошибочных поставок, "
            "товаров на временном хранении. Ранее уплаченные пошлины возвращаются."
        ),
        "hs_restrictions": "",
    },
    # ─── TRANSIT PROCEDURES ───
    {
        "procedure_code": "ТТ80",
        "name_ru": "Таможенный транзит",
        "direction": "transit",
        "description": (
            "Товары перемещаются по таможенной территории ЕАЭС от таможни "
            "отправления к таможне назначения без уплаты пошлин и налогов. "
            "Используется для транзита через территорию РФ."
        ),
        "legal_ref": "ТК ЕАЭС ст. 142-154",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": None,
        "documents_required": (
            "Транзитная декларация; транспортные документы; обеспечение уплаты "
            "таможенных платежей; пломбирование транспортных средств"
        ),
        "conditions": (
            "Срок транзита: до 30 дней (авто/жд) или определяется маршрутом. "
            "Обязательное обеспечение уплаты платежей (банковская гарантия, залог)."
        ),
        "hs_restrictions": "",
    },
    # ─── SPECIAL PROCEDURES ───
    {
        "procedure_code": "ИМ60",
        "name_ru": "Реимпорт",
        "direction": "import",
        "description": (
            "Ранее вывезенные товары ЕАЭС возвращаются на таможенную территорию "
            "без уплаты ввозных пошлин и налогов. Условие: товары не подвергались "
            "операциям кроме нормального износа."
        ),
        "legal_ref": "ТК ЕАЭС ст. 235-237",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": None,
        "documents_required": (
            "ДТ; ДТ на первоначальный вывоз; документы, подтверждающие "
            "идентичность товаров; подтверждение отсутствия переработки"
        ),
        "conditions": (
            "Товары должны быть ввезены обратно в течение 3 лет с момента вывоза. "
            "При возврате НДС при экспорте — необходимо вернуть возмещённый НДС."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ДП00",
        "name_ru": "Декларирование припасов",
        "direction": "special",
        "description": (
            "Припасы (топливо, продовольствие, расходные материалы) для морских "
            "и воздушных судов. Освобождение от пошлин и налогов."
        ),
        "legal_ref": "ТК ЕАЭС ст. 279-281",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": False,
        "time_limit_months": None,
        "documents_required": (
            "Декларация на припасы; генеральная декларация судна; "
            "накладные на бортовое питание"
        ),
        "conditions": "Только для снабжения морских/воздушных судов",
        "hs_restrictions": "27 (топливо), 01-24 (продовольствие)",
    },
    {
        "procedure_code": "БТ00",
        "name_ru": "Беспошлинная торговля (Duty Free)",
        "direction": "special",
        "description": (
            "Товары реализуются в магазинах беспошлинной торговли без уплаты "
            "ввозных пошлин, НДС и акциза. Только для выезжающих за пределы ЕАЭС."
        ),
        "legal_ref": "ТК ЕАЭС ст. 243-247",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": None,
        "documents_required": (
            "ДТ; реестр владельцев магазинов DF; учётная документация; "
            "отчётность о реализации"
        ),
        "conditions": (
            "Магазин должен находиться в зоне таможенного контроля (аэропорт, "
            "пункт пропуска). Владелец — в реестре ФТС."
        ),
        "hs_restrictions": "",
    },
    # ─── POSTAL / EXPRESS ───
    {
        "procedure_code": "ТД00",
        "name_ru": "Таможенное декларирование товаров для личного пользования",
        "direction": "import",
        "description": (
            "Упрощённый порядок таможенного оформления товаров, перемещаемых "
            "физическими лицами для личных нужд. Нормы беспошлинного ввоза: "
            "до 200 EUR/31 кг (с 01.04.2025)."
        ),
        "legal_ref": "ТК ЕАЭС ст. 256-270; Решение ЕЭК № 107 от 20.12.2017",
        "duty_applies": True,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": False,
        "time_limit_months": None,
        "documents_required": (
            "Пассажирская таможенная декларация; паспорт; чеки/инвойсы"
        ),
        "conditions": (
            "Сверх нормы: единая ставка 15% но не менее 2 EUR/кг. "
            "Для МПО: до 200 EUR беспошлинно, свыше — 15%."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ЭД00",
        "name_ru": "Электронное декларирование (общий)",
        "direction": "import",
        "description": (
            "Стандартная электронная подача ДТ через систему АИСТ/ЕАИС. "
            "Обязательный способ подачи с 2014 года. Автовыпуск — до 4 часов."
        ),
        "legal_ref": "ФЗ-289 ст. 104-106; Приказ ФТС № 1761 от 17.09.2013",
        "duty_applies": True,
        "vat_applies": True,
        "excise_applies": True,
        "customs_fee_applies": True,
        "time_limit_months": None,
        "documents_required": (
            "Электронная ДТ; ЭЦП декларанта; прикреплённые скан-копии "
            "документов; ЕЛС (единый лицевой счёт)"
        ),
        "conditions": "Обязательное подключение к системе ЕАИС ТО",
        "hs_restrictions": "",
    },
    # ─── ADDITIONAL IMPORTANT CODES ───
    {
        "procedure_code": "ИМ41",
        "name_ru": "Условный выпуск (льготы/тарифные преференции)",
        "direction": "import",
        "description": (
            "Выпуск товаров с предоставлением льгот по уплате пошлин/налогов "
            "при условии целевого использования. При нарушении условий — "
            "доплата полной суммы платежей + пени."
        ),
        "legal_ref": "ТК ЕАЭС ст. 126-128",
        "duty_applies": True,
        "vat_applies": True,
        "excise_applies": True,
        "customs_fee_applies": True,
        "time_limit_months": 60,
        "documents_required": (
            "ДТ; документы, подтверждающие право на льготу; "
            "обязательство о целевом использовании; обеспечение"
        ),
        "conditions": (
            "Товары не подлежат передаче третьим лицам, продаже, сдаче в аренду "
            "без разрешения таможенного органа. Срок ограничения: 5 лет."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ИМ77",
        "name_ru": "Специальная таможенная процедура",
        "direction": "import",
        "description": (
            "Применяется для отдельных категорий товаров: дипломатическая почта, "
            "товары для международных организаций, гуманитарная помощь, "
            "товары для устранения последствий ЧС."
        ),
        "legal_ref": "ТК ЕАЭС ст. 253-255",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": False,
        "time_limit_months": None,
        "documents_required": (
            "ДТ; документы международной организации / МИД; "
            "подтверждение гуманитарного характера груза"
        ),
        "conditions": (
            "Ограниченный перечень: дипломатические грузы, военная техника по "
            "межправительственным соглашениям, гуманитарная помощь."
        ),
        "hs_restrictions": "",
    },
    {
        "procedure_code": "ИМ94",
        "name_ru": "Свободная таможенная зона (Калининград/Владивосток)",
        "direction": "import",
        "description": (
            "Специальная процедура для ОЭЗ в Калининградской области "
            "и порта Владивосток. Расширенные льготы по пошлинам и НДС "
            "для резидентов."
        ),
        "legal_ref": "ФЗ-16 от 10.01.2006; ФЗ-212 от 13.07.2015",
        "duty_applies": False,
        "vat_applies": False,
        "excise_applies": False,
        "customs_fee_applies": True,
        "time_limit_months": None,
        "documents_required": (
            "ДТ; свидетельство резидента ОЭЗ; инвестиционное соглашение"
        ),
        "conditions": (
            "Только для резидентов ОЭЗ. При выпуске для свободного обращения — "
            "применяются ставки для продуктов переработки."
        ),
        "hs_restrictions": "",
    },
]


def seed() -> dict[str, int]:
    from app.models.tnved import CustomsProcedure
    Base.metadata.create_all(engine, tables=[CustomsProcedure.__table__])

    inserted = 0
    with SessionLocal() as db:
        for proc in PROCEDURES:
            exists = db.execute(
                text("SELECT 1 FROM customs_procedures WHERE procedure_code = :code"),
                {"code": proc["procedure_code"]},
            ).fetchone()
            if exists:
                continue
            row = CustomsProcedure(**proc)
            db.add(row)
            inserted += 1

        if DRY_RUN:
            db.rollback()
            print(f"[DRY RUN] Would insert {inserted} customs procedures")
        else:
            db.commit()
            print(f"Inserted {inserted} customs procedures")

        total = db.execute(text("SELECT COUNT(*) FROM customs_procedures")).scalar()
        by_dir = db.execute(text(
            "SELECT direction, COUNT(*) FROM customs_procedures GROUP BY direction ORDER BY direction"
        )).fetchall()
        print(f"Total procedures: {total}")
        for d, c in by_dir:
            print(f"  {d:10s}: {c}")

    return {"inserted": inserted, "total": total}


if __name__ == "__main__":
    seed()
