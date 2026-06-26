#!/usr/bin/env python3
"""Seed import_restrictions with bans, quotas, sanctions, dual-use controls.

Restriction types:
  - ban: полный запрет ввоза
  - quota: количественное ограничение
  - sanction: санкционное ограничение
  - dual_use: товары двойного назначения (экспортный контроль)
  - licensing: лицензирование ввоза

Usage:
    cd customs-clear/backend
    python3 -m scripts.seed_import_restrictions [--dry-run]
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
# Import restriction entries
# ═══════════════════════════════════════════════════════════════════
RESTRICTIONS = [
    # ─── BANS: полные запреты ───
    {"hs": "0207", "type": "ban", "country": "US", "sev": "block",
     "desc": "Запрет на ввоз мяса птицы из США (ПП РФ от 07.08.2014 №778)",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0201", "type": "ban", "country": "US", "sev": "block",
     "desc": "Запрет на ввоз говядины из США",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0202", "type": "ban", "country": "US", "sev": "block",
     "desc": "Запрет на ввоз мяса замороженного из США",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0203", "type": "ban", "country": "US", "sev": "block",
     "desc": "Запрет на ввоз свинины из США",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0401", "type": "ban", "country": "EU", "sev": "block",
     "desc": "Запрет на ввоз молочной продукции из стран ЕС (контрсанкции)",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0402", "type": "ban", "country": "EU", "sev": "block",
     "desc": "Запрет на ввоз сгущённого молока из стран ЕС",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0406", "type": "ban", "country": "EU", "sev": "block",
     "desc": "Запрет на ввоз сыров и творога из стран ЕС",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0406", "type": "ban", "country": "US", "sev": "block",
     "desc": "Запрет на ввоз сыров и творога из США",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0302", "type": "ban", "country": "NO", "sev": "block",
     "desc": "Запрет на ввоз рыбы из Норвегии (контрсанкции)",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0303", "type": "ban", "country": "NO", "sev": "block",
     "desc": "Запрет на ввоз замороженной рыбы из Норвегии",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0804", "type": "ban", "country": "EU", "sev": "block",
     "desc": "Запрет на ввоз фруктов (инжир, цитрусовые) из стран ЕС",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0808", "type": "ban", "country": "EU", "sev": "block",
     "desc": "Запрет на ввоз яблок и груш из стран ЕС",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0701", "type": "ban", "country": "EU", "sev": "block",
     "desc": "Запрет на ввоз картофеля из стран ЕС",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0702", "type": "ban", "country": "EU", "sev": "block",
     "desc": "Запрет на ввоз томатов из стран ЕС",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},

    # ─── Контрсанкции: Австралия, Канада ───
    {"hs": "0201", "type": "ban", "country": "AU", "sev": "block",
     "desc": "Запрет на ввоз говядины из Австралии (контрсанкции)",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0201", "type": "ban", "country": "CA", "sev": "block",
     "desc": "Запрет на ввоз говядины из Канады (контрсанкции)",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0406", "type": "ban", "country": "AU", "sev": "block",
     "desc": "Запрет на ввоз сыров из Австралии",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},
    {"hs": "0406", "type": "ban", "country": "CA", "sev": "block",
     "desc": "Запрет на ввоз сыров из Канады",
     "legal": "ПП РФ от 07.08.2014 №778", "from": "2014-08-07"},

    # ─── DUAL-USE: товары двойного назначения ───
    {"hs": "8401", "type": "dual_use", "country": "ALL", "sev": "block",
     "desc": "Ядерные реакторы и их части — контроль двойного назначения",
     "legal": "Указ Президента РФ от 14.01.2003 №36, Wassenaar Arrangement",
     "from": "2003-01-14"},
    {"hs": "8402", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Котлы паровые и водогрейные — потенциально двойного назначения",
     "legal": "Решение Коллегии ЕЭК, Wassenaar", "from": "2010-01-01"},
    {"hs": "8456", "type": "dual_use", "country": "ALL", "sev": "block",
     "desc": "Станки для обработки металла лазером — экспортный контроль",
     "legal": "Указ Президента РФ от 14.01.2003 №36", "from": "2003-01-14"},
    {"hs": "8457", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Обрабатывающие центры, станки многоцелевые — контроль точности ≤2μm",
     "legal": "Wassenaar ML22, Указ Президента РФ №36", "from": "2003-01-14"},
    {"hs": "8462", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Прессы гидравлические >35МН — двойное назначение",
     "legal": "Wassenaar Arrangement", "from": "2010-01-01"},
    {"hs": "8479", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Изостатические прессы — контроль двойного назначения",
     "legal": "Wassenaar ML18, Указ Президента РФ №36", "from": "2003-01-14"},
    {"hs": "2844", "type": "dual_use", "country": "ALL", "sev": "block",
     "desc": "Радиоактивные элементы и изотопы — контроль ядерных материалов",
     "legal": "ФЗ от 21.11.1995 №170-ФЗ, НСГ", "from": "1995-11-21"},
    {"hs": "2845", "type": "dual_use", "country": "ALL", "sev": "block",
     "desc": "Изотопы (кроме 2844) — контроль ядерных материалов",
     "legal": "ФЗ от 21.11.1995 №170-ФЗ", "from": "1995-11-21"},
    {"hs": "8471", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Высокопроизводительные ЭВМ — контроль при >29 TFLOPS",
     "legal": "Wassenaar 4.A.3, Указ Президента РФ №36", "from": "2003-01-14"},
    {"hs": "8525", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Камеры ИК-диапазона, тепловизоры — контроль двойного назначения",
     "legal": "Wassenaar 6.A.2, Указ Президента РФ №36", "from": "2003-01-14"},
    {"hs": "8526", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Радарные системы — контроль при определённых характеристиках",
     "legal": "Wassenaar 6.A.1", "from": "2010-01-01"},
    {"hs": "8543", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Генераторы импульсов, электромагнитное оборудование — контроль",
     "legal": "Wassenaar 3.A.2", "from": "2010-01-01"},
    {"hs": "9005", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Оптические приборы, бинокли — контроль при ночном видении",
     "legal": "Wassenaar 6.A.2", "from": "2010-01-01"},
    {"hs": "9013", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Лазерные устройства высокой мощности — двойное назначение",
     "legal": "Wassenaar 6.A.5, Указ Президента РФ №36", "from": "2003-01-14"},
    {"hs": "9014", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Навигационные приборы (инерциальные, гироскопы) — контроль точности",
     "legal": "Wassenaar 7.A.3", "from": "2010-01-01"},
    {"hs": "9015", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Геодезические инструменты точного позиционирования",
     "legal": "Wassenaar 7.A", "from": "2010-01-01"},
    {"hs": "9027", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Масс-спектрометры, хроматографы — контроль при определённой чувствительности",
     "legal": "Wassenaar 3.B, Австралийская группа", "from": "2010-01-01"},
    {"hs": "3002", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Вакцины, токсины, патогены — биологический контроль",
     "legal": "Австралийская группа, КБТО", "from": "2010-01-01"},
    {"hs": "2903", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Прекурсоры химического оружия (некоторые галогенпроизводные)",
     "legal": "КЗХО, Австралийская группа", "from": "1997-04-29"},
    {"hs": "2904", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Сульфопроизводные углеводородов — контроль прекурсоров",
     "legal": "КЗХО список 2,3", "from": "1997-04-29"},
    {"hs": "2931", "type": "dual_use", "country": "ALL", "sev": "block",
     "desc": "Фосфорорганические соединения — прекурсоры ХО (список 1-2 КЗХО)",
     "legal": "КЗХО, ФЗ от 05.11.1997 №138-ФЗ", "from": "1997-04-29"},
    {"hs": "7601", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Алюминий необработанный высокой чистоты — контроль для аэрокосмической отрасли",
     "legal": "Wassenaar 1.C.2", "from": "2010-01-01"},
    {"hs": "8112", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Бериллий, германий, гафний и изделия — контроль ядерных/ракетных технологий",
     "legal": "РКРТ, НСГ, Wassenaar", "from": "2010-01-01"},

    # ─── LICENSING: лицензирование ввоза ───
    {"hs": "9302", "type": "licensing", "country": "ALL", "sev": "block",
     "desc": "Оружие (револьверы, пистолеты) — лицензия МВД/Росгвардия",
     "legal": "ФЗ от 13.12.1996 №150-ФЗ «Об оружии»", "from": "1996-12-13"},
    {"hs": "9303", "type": "licensing", "country": "ALL", "sev": "block",
     "desc": "Огнестрельное оружие — лицензия Росгвардия",
     "legal": "ФЗ от 13.12.1996 №150-ФЗ «Об оружии»", "from": "1996-12-13"},
    {"hs": "9304", "type": "licensing", "country": "ALL", "sev": "warning",
     "desc": "Пневматическое оружие >7.5 Дж — лицензирование",
     "legal": "ФЗ от 13.12.1996 №150-ФЗ", "from": "1996-12-13"},
    {"hs": "9306", "type": "licensing", "country": "ALL", "sev": "block",
     "desc": "Боеприпасы — лицензия Росгвардия",
     "legal": "ФЗ от 13.12.1996 №150-ФЗ", "from": "1996-12-13"},
    {"hs": "3003", "type": "licensing", "country": "ALL", "sev": "warning",
     "desc": "Лекарственные средства (незарегистрированные) — регистрационное удостоверение Минздрав",
     "legal": "ФЗ от 12.04.2010 №61-ФЗ «Об обращении лекарственных средств»", "from": "2010-04-12"},
    {"hs": "3004", "type": "licensing", "country": "ALL", "sev": "warning",
     "desc": "Лекарственные средства (расфасованные) — лицензирование фармдеятельности",
     "legal": "ФЗ от 12.04.2010 №61-ФЗ", "from": "2010-04-12"},
    {"hs": "2933", "type": "licensing", "country": "ALL", "sev": "block",
     "desc": "Прекурсоры наркотических средств — лицензия ФСКН",
     "legal": "ФЗ от 08.01.1998 №3-ФЗ «О наркотических средствах»", "from": "1998-01-08"},
    {"hs": "2939", "type": "licensing", "country": "ALL", "sev": "block",
     "desc": "Алкалоиды (эфедрин, псевдоэфедрин) — контроль прекурсоров",
     "legal": "ФЗ от 08.01.1998 №3-ФЗ, Постановление Правительства РФ №681", "from": "1998-01-08"},
    {"hs": "3601", "type": "licensing", "country": "ALL", "sev": "block",
     "desc": "Порох, взрывчатые вещества — лицензирование ввоза",
     "legal": "ФЗ от 13.12.1996 №150-ФЗ, ФЗ от 21.07.1997 №116-ФЗ", "from": "1996-12-13"},
    {"hs": "3602", "type": "licensing", "country": "ALL", "sev": "block",
     "desc": "Детонаторы, капсюли — лицензирование",
     "legal": "ФЗ от 21.07.1997 №116-ФЗ", "from": "1997-07-21"},
    {"hs": "3604", "type": "licensing", "country": "ALL", "sev": "warning",
     "desc": "Пиротехника (классов выше III) — лицензирование",
     "legal": "ТР ТС 006/2011, ПП РФ от 06.02.2021 №128", "from": "2011-01-01"},
    {"hs": "8710", "type": "licensing", "country": "ALL", "sev": "block",
     "desc": "Танки и бронемашины — лицензирование военной техники",
     "legal": "ФЗ от 19.07.1998 №114-ФЗ «О военно-техническом сотрудничестве»", "from": "1998-07-19"},
    {"hs": "8802", "type": "licensing", "country": "ALL", "sev": "warning",
     "desc": "Летательные аппараты — сертификация лётной годности",
     "legal": "Воздушный кодекс РФ, ФАП", "from": "1997-03-19"},
    {"hs": "2709", "type": "licensing", "country": "ALL", "sev": "warning",
     "desc": "Нефть сырая — тарифное квотирование/лицензирование",
     "legal": "ФЗ от 08.12.2003 №164-ФЗ «Об основах госрегулирования ВТД»", "from": "2003-12-08"},

    # ─── SANCTIONS: товарные санкции ───
    {"hs": "7106", "type": "sanction", "country": "ALL", "sev": "warning",
     "desc": "Серебро — ограничения при происхождении из подсанкционных юрисдикций",
     "legal": "Решения Совета ЕЭК, Указы Президента РФ", "from": "2022-03-01"},
    {"hs": "7108", "type": "sanction", "country": "ALL", "sev": "warning",
     "desc": "Золото — контроль происхождения, возможны ограничения оборота",
     "legal": "ФЗ от 26.03.1998 №41-ФЗ «О драгоценных металлах»", "from": "1998-03-26"},
    {"hs": "7110", "type": "sanction", "country": "ALL", "sev": "warning",
     "desc": "Платина — контроль оборота драгоценных металлов",
     "legal": "ФЗ от 26.03.1998 №41-ФЗ", "from": "1998-03-26"},

    # ─── QUOTAS: количественные ограничения ───
    {"hs": "0201", "type": "quota", "country": "ALL", "sev": "warning",
     "desc": "Тарифная квота на говядину (ТК ЕАЭС): 570 тыс. тонн/год",
     "legal": "Решение Коллегии ЕЭК, ТК ЕАЭС", "from": "2020-01-01"},
    {"hs": "0203", "type": "quota", "country": "ALL", "sev": "warning",
     "desc": "Тарифная квота на свинину (ТК ЕАЭС): 430 тыс. тонн/год",
     "legal": "Решение Коллегии ЕЭК", "from": "2020-01-01"},
    {"hs": "0207", "type": "quota", "country": "ALL", "sev": "warning",
     "desc": "Тарифная квота на мясо птицы: 350 тыс. тонн/год",
     "legal": "Решение Коллегии ЕЭК", "from": "2020-01-01"},
    {"hs": "1006", "type": "quota", "country": "ALL", "sev": "warning",
     "desc": "Тарифная квота на рис: 10 тыс. тонн/год (внеквотная ставка выше)",
     "legal": "Решение Коллегии ЕЭК", "from": "2020-01-01"},
    {"hs": "1701", "type": "quota", "country": "ALL", "sev": "warning",
     "desc": "Тарифная квота на сахар: квотные ставки ЕТТ ЕАЭС",
     "legal": "Решение Коллегии ЕЭК", "from": "2020-01-01"},
    {"hs": "1003", "type": "quota", "country": "ALL", "sev": "warning",
     "desc": "Тарифная квота на ячмень",
     "legal": "Решение Коллегии ЕЭК", "from": "2020-01-01"},
    {"hs": "0402", "type": "quota", "country": "ALL", "sev": "warning",
     "desc": "Тарифная квота на молочную сыворотку/концентраты",
     "legal": "Решение Коллегии ЕЭК", "from": "2020-01-01"},

    # ─── Дополнительные dual-use высокие технологии ───
    {"hs": "8541", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Полупроводники, микросхемы — контроль при определённых характеристиках",
     "legal": "Wassenaar 3.A.1, Указ Президента РФ №36", "from": "2003-01-14"},
    {"hs": "8542", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Интегральные схемы — контроль при военном/ядерном применении",
     "legal": "Wassenaar 3.A.1", "from": "2010-01-01"},
    {"hs": "8517", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Криптографическое оборудование связи — контроль ФСБ/уведомление",
     "legal": "ПП РФ от 16.04.2012 №313, Wassenaar 5.A.2", "from": "2012-04-16"},
    {"hs": "9030", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Осциллографы >1ГГц, анализаторы спектра — контроль",
     "legal": "Wassenaar 3.A", "from": "2010-01-01"},
    {"hs": "9031", "type": "dual_use", "country": "ALL", "sev": "warning",
     "desc": "Координатно-измерительные машины, 3D-сканеры высокой точности",
     "legal": "Wassenaar 2.B.6", "from": "2010-01-01"},

    # ─── Запреты на озоноразрушающие вещества ───
    {"hs": "2903", "type": "ban", "country": "ALL", "sev": "block",
     "desc": "Хлорфторуглероды (ХФУ) — запрет по Монреальскому протоколу",
     "legal": "Монреальский протокол 1987, ПП РФ от 24.03.2014 №228", "from": "2010-01-01"},

    # ─── Отходы (Базельская конвенция) ───
    {"hs": "3915", "type": "licensing", "country": "ALL", "sev": "warning",
     "desc": "Отходы пластмасс — контроль трансграничного перемещения отходов",
     "legal": "Базельская конвенция, ФЗ от 24.06.1998 №89-ФЗ", "from": "1998-06-24"},
    {"hs": "7204", "type": "licensing", "country": "ALL", "sev": "warning",
     "desc": "Лом чёрных металлов — лицензирование при трансграничном перемещении",
     "legal": "ФЗ от 24.06.1998 №89-ФЗ, Решение Коллегии ЕЭК", "from": "2010-01-01"},
    {"hs": "7404", "type": "licensing", "country": "ALL", "sev": "warning",
     "desc": "Лом меди — контроль вывоза/ввоза вторичного сырья",
     "legal": "Решение Коллегии ЕЭК", "from": "2010-01-01"},

    # ─── Биологическая безопасность ───
    {"hs": "0106", "type": "licensing", "country": "ALL", "sev": "warning",
     "desc": "Живые животные (СИТЕС) — разрешение Росприроднадзора",
     "legal": "Конвенция СИТЕС, ПП РФ от 13.09.2012 №923", "from": "1976-01-01"},
    {"hs": "0602", "type": "licensing", "country": "ALL", "sev": "warning",
     "desc": "Живые растения, луковицы — фитосанитарный контроль, СИТЕС для редких видов",
     "legal": "СИТЕС, ФЗ от 15.07.2000 №99-ФЗ «О карантине растений»", "from": "2000-07-15"},
]


def seed() -> dict[str, int]:
    from app.models.tnved import ImportRestriction
    Base.metadata.create_all(engine, tables=[ImportRestriction.__table__])

    inserted = 0
    with SessionLocal() as db:
        for r in RESTRICTIONS:
            exists = db.execute(
                text(
                    "SELECT 1 FROM import_restrictions "
                    "WHERE hs_prefix = :hs AND restriction_type = :rt AND country_code = :cc "
                    "AND legal_ref = :lr"
                ),
                {"hs": r["hs"], "rt": r["type"], "cc": r["country"], "lr": r["legal"]},
            ).fetchone()
            if exists:
                continue
            row = ImportRestriction(
                hs_prefix=r["hs"],
                restriction_type=r["type"],
                country_code=r["country"],
                description=r["desc"],
                legal_ref=r["legal"],
                effective_from=r.get("from", ""),
                effective_to=r.get("to", ""),
                severity=r["sev"],
                source_url=r.get("url", ""),
            )
            db.add(row)
            inserted += 1

        if DRY_RUN:
            db.rollback()
            print(f"[DRY RUN] Would insert {inserted} import restrictions")
        else:
            db.commit()
            print(f"Inserted {inserted} import restrictions")

        total = db.execute(text("SELECT COUNT(*) FROM import_restrictions")).scalar()
        by_type = db.execute(text(
            "SELECT restriction_type, COUNT(*) FROM import_restrictions GROUP BY restriction_type ORDER BY restriction_type"
        )).fetchall()
        print(f"Total: {total}")
        for t, c in by_type:
            print(f"  {t}: {c}")

    return {"inserted": inserted, "total": total}


if __name__ == "__main__":
    seed()
