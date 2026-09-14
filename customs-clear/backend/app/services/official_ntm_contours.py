"""Официальные нетарифные контуры, без подключения к broker enforcement.

Контур намеренно вычисляется без БД: источники и правила версионируются вместе с кодом.
Advisory-показ включён по умолчанию с explicit-false kill switch. Совпадение по одному
коду ``из`` никогда не становится обязательным документом без подтверждающей
характеристики товара и не участвует в enforcement.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .hs_matching import normalize_hs_code
from .official_export_control import evaluate_export_control_requirement
from .official_ntm_exact_applicability import (
    evaluate_official_ntm_exact_applicability,
)

OFFICIAL_NTM_SOURCE_KIND = "official_ntm_contours"
OFFICIAL_NTM_SOURCE_LABEL = "Официальные перечни ЕЭК / РФ"

DECISION_30_URL = "https://eec.eaeunion.org/comission/department/catr/nontariff/30.php"
DECISION_30_UNIFIED_LIST_URL = "https://eec.eaeunion.org/comission/department/catr/nontariff/ep.new.php"
DECISION_30_216_URL = "https://eec.eaeunion.org/upload/files/catr/EP.pdf/2.16.pdf"
DECISION_30_219_URL = "https://eec.eaeunion.org/upload/files/catr/EP.pdf/2.19_137.pdf"
PP_2425_URL = "https://publication.pravo.gov.ru/document/0001202112300200"
DECISION_299_LIST_URL = "https://eec.eaeunion.org/upload/medialibrary/f52/EdpertovarovEEU.pdf"
DECISION_317_LIST_URL = "https://eec.eaeunion.org/upload/medialibrary/89f/Pr.1-Edinyy-perechen-tov.pdf"
DECISION_318_LIST_URL = "https://eec.eaeunion.org/upload/medialibrary/60f/x9vhmm3gi76102uwhqlv7iffol64r6lo/Perechen-produktsii.pdf"
DECISION_157_REQUIREMENTS_URL = "https://eec.eaeunion.org/upload/medialibrary/e83/ne3jhyoymc2i57nx91wzn5fihnoi28ap/EKFT-v-red.-Resh.-_80.pdf"
TR_TS_007_URL = "https://eec.eaeunion.org/comission/department/deptexreg/tr/bezopDeti.php"
TR_TS_015_URL = "https://eec.eaeunion.org/comission/department/deptexreg/tr/bezpoZerna.php"
TR_GENERAL_URL = "https://eec.eaeunion.org/comission/department/deptexreg/tr/TR_general.php"
TR_TS_026_URL = TR_GENERAL_URL
TR_EAEU_036_URL = "https://eec.eaeunion.org/comission/department/deptexreg/tr/TR_EEU_036.php"
TR_EAEU_050_URL = "https://eec.eaeunion.org/comission/department/deptexreg/tr/TR_EAEU_050.php"
TR_EAEU_051_URL = "https://eec.eaeunion.org/comission/department/deptexreg/tr/TR_EAEU_051.php"
TR_EAEU_052_URL = "https://eec.eaeunion.org/comission/department/deptexreg/tr/TR_EAEU_052.php"

# Индекс 30 базовых разделов приложений 1 и 2 Единого перечня. Квотные меры
# 2.27/3.1/3.2 требуют отдельных года, происхождения и объёма и сюда не входят.
# Это индекс нормативных контуров, а не утверждение применимости по одному коду.
DECISION_30_SECTIONS: tuple[dict[str, str], ...] = (
    {"section": "1.1", "direction": "both", "kind": "prohibition", "title": "Озоноразрушающие вещества и продукция с ними"},
    {"section": "1.2", "direction": "import", "kind": "prohibition", "title": "Опасные отходы, запрещённые к ввозу"},
    {"section": "1.3", "direction": "both", "kind": "prohibition", "title": "Запрещённая информация на носителях"},
    {"section": "1.4", "direction": "import", "kind": "prohibition", "title": "Запрещённые средства защиты растений и стойкие загрязнители"},
    {"section": "1.6", "direction": "both", "kind": "prohibition", "title": "Запрещённые виды оружия и патронов"},
    {"section": "1.7", "direction": "import", "kind": "prohibition", "title": "Запрещённые орудия добычи водных биоресурсов"},
    {"section": "1.8", "direction": "import", "kind": "prohibition", "title": "Изделия из гренландского тюленя"},
    {"section": "1.9", "direction": "export", "kind": "prohibition", "title": "Живые соболи"},
    {"section": "1.12", "direction": "export", "kind": "prohibition", "title": "Киты, дельфины и морские свиньи"},
    {"section": "2.1", "direction": "both", "kind": "permit", "title": "Озоноразрушающие вещества"},
    {"section": "2.2", "direction": "import", "kind": "permit", "title": "Средства защиты растений (пестициды)"},
    {"section": "2.3", "direction": "both", "kind": "permit", "title": "Опасные отходы"},
    {"section": "2.4", "direction": "export", "kind": "permit", "title": "Минералогические и палеонтологические коллекции"},
    {"section": "2.6", "direction": "export", "kind": "permit", "title": "Дикие животные, растения и лекарственное сырьё"},
    {"section": "2.7", "direction": "both", "kind": "permit", "title": "Виды CITES"},
    {"section": "2.8", "direction": "export", "kind": "permit", "title": "Краснокнижные виды"},
    {"section": "2.9", "direction": "both", "kind": "permit", "title": "Драгоценные камни"},
    {"section": "2.10", "direction": "both", "kind": "permit", "title": "Драгоценные металлы и сырьё с ними"},
    {"section": "2.11", "direction": "export", "kind": "permit", "title": "Виды минерального сырья"},
    {"section": "2.12", "direction": "both", "kind": "permit", "title": "Наркотические и психотропные вещества, прекурсоры"},
    {"section": "2.13", "direction": "import", "kind": "permit", "title": "Ядовитые вещества"},
    {"section": "2.14", "direction": "import", "kind": "permit", "title": "Лекарственные средства"},
    {"section": "2.16", "direction": "import", "kind": "permit", "title": "Радиоэлектронные и высокочастотные устройства"},
    {"section": "2.17", "direction": "both", "kind": "permit", "title": "Средства негласного получения информации"},
    {"section": "2.19", "direction": "both", "kind": "permit", "title": "Шифровальные (криптографические) средства"},
    {"section": "2.20", "direction": "export", "kind": "permit", "title": "Культурные и архивные ценности"},
    {"section": "2.21", "direction": "both", "kind": "permit", "title": "Органы, ткани, кровь и биоматериалы человека"},
    {"section": "2.22", "direction": "both", "kind": "permit", "title": "Служебное и гражданское оружие"},
    {"section": "2.23", "direction": "export", "kind": "permit", "title": "Информация о недрах"},
    {"section": "2.30", "direction": "import", "kind": "permit", "title": "Стойкие загрязнители для лабораторных исследований"},
)

# Код здесь является только первичным фильтром. Все правила остаются advisory;
# совпадение кода и свободного текста не подтверждает юридическую применимость.
_DECISION_30_SPECIAL_RULES: tuple[dict[str, Any], ...] = (
    {"section": "1.1", "prefixes": ("2903", "3827", "3907", "3921", "8415", "8418", "8419", "8424", "8479"), "markers": ("озоноразруш", "фреон", "хладон", "хладагент", "холодиль", "морозиль", "кондиционер", "тепловой насос", "огнетушител", "полиол"), "permit_type": "ЗАПРЕТ"},
    {"section": "1.2", "prefixes": ("2524", "2618", "2619", "2620", "2621", "2710", "2805", "3825", "4013", "4017", "7001", "7204", "7404", "7503", "7602", "7802", "7902", "8549"), "markers": ("отход", "лом", "шлам", "зола", "шлак", "отработан"), "permit_type": "ЗАПРЕТ"},
    {"section": "1.3", "prefixes": ("3706", "4901", "4902", "4908", "4909", "4910", "4911", "8523"), "markers": ("экстремист", "террорист", "порнограф"), "permit_type": "ЗАПРЕТ"},
    {"section": "1.4", "prefixes": ("2903", "2910", "2914", "2920", "3808", "3824"), "markers": ("стойкий органический загрязнитель", "запрещенный пестицид", "запрещённый пестицид"), "permit_type": "ЗАПРЕТ"},
    {"section": "1.6", "prefixes": ("9301", "9302", "9303", "9304", "9305", "9306"), "markers": ("оруж", "патрон", "боеприпас"), "permit_type": "ЗАПРЕТ"},
    {"section": "1.7", "prefixes": ("5608",), "markers": ("сеть рыболов", "орудие лова", "электролов"), "permit_type": "ЗАПРЕТ"},
    {"section": "1.8", "prefixes": ("4301", "4302", "4303"), "markers": ("гренландск", "тюлен"), "permit_type": "ЗАПРЕТ"},
    {"section": "1.9", "prefixes": ("0106",), "markers": ("соболь", "соболи"), "permit_type": "ЗАПРЕТ"},
    {"section": "1.12", "prefixes": ("0106",), "markers": ("кит", "дельфин", "морская свинья"), "permit_type": "ЗАПРЕТ"},
    {"section": "2.1", "prefixes": ("2903", "3827", "3907", "3921", "8415", "8418", "8419", "8424", "8479"), "markers": ("озоноразруш", "фреон", "хладон", "хладагент"), "permit_type": "ЛЗ"},
    {"section": "2.2", "prefixes": ("3808",), "exclude_prefixes": ("380894",), "exclude_markers": ("липкая лента", "клейкая лента", "ловчий пояс"), "markers": ("пестицид", "гербицид", "фунгицид", "инсектицид", "средство защиты растений"), "permit_type": "ЛЗ"},
    {"section": "2.3", "prefixes": ("2524", "2618", "2619", "2620", "2621", "2710", "2805", "3825", "4013", "4017", "7001", "7204", "7404", "7503", "7602", "7802", "7902", "8549"), "markers": ("отход", "лом", "шлам", "зола", "шлак", "отработан"), "permit_type": "ЛЗ"},
    {"section": "2.4", "prefixes": ("0506", "9705"), "markers": ("коллекц", "палеонтолог", "ископаем", "минералог"), "permit_type": "ЛЗ"},
    {"section": "2.6", "prefixes": ("01", "0301", "0306", "0307", "0308", "0511", "0802", "0811", "1211", "1212", "1302"), "exclude_markers": ("соболь", "соболи"), "markers": ("дикораст", "дикое живот", "лекарственное сырье", "лекарственное сырьё", "дикий вид"), "permit_type": "ЛЗ"},
    {"section": "2.7", "prefixes": ("01", "03", "06", "12", "41", "42", "43", "44", "96"), "markers": ("cites", "ситес", "находящ", "редкий вид"), "permit_type": "CITES"},
    {"section": "2.8", "prefixes": ("01", "06", "12"), "markers": ("красная книга", "краснокниж"), "permit_type": "ЛЗ"},
    {"section": "2.9", "prefixes": ("7102", "7103", "7104", "7105", "7116"), "markers": ("алмаз", "бриллиант", "драгоценный камень", "драгоценные камни"), "permit_type": "ЛЗ"},
    {"section": "2.10", "prefixes": ("2616", "7106", "7108", "7110", "7112"), "markers": ("золото", "серебро", "платин", "драгоценный металл", "драгоценные металлы"), "permit_type": "ЛЗ"},
    {"section": "2.11", "prefixes": ("2530900001", "7103100001", "7103100008"), "markers": ("янтар", "нефрит", "необработанный камень", "необработанные камни", "драгоценный камень"), "permit_type": "ЛЗ"},
    {"section": "2.12", "prefixes": ("28", "29", "30"), "markers": ("наркот", "психотроп", "прекурсор"), "permit_type": "ЛЗ"},
    {"section": "2.13", "prefixes": ("28", "29"), "markers": ("ядовит", "сильнодейств"), "permit_type": "ЛЗ"},
    {"section": "2.14", "prefixes": ("3001", "3002", "3003", "3004", "3005", "3006"), "markers": ("лекарствен", "фармацевт", "медикамент", "вакцин"), "permit_type": "РУ"},
    {"section": "2.17", "prefixes": ("8301", "8471", "8505", "8517", "8518", "8519", "8521", "8523", "8525", "8526", "8527", "8529", "9002", "9006", "9019", "9022"), "markers": ("негласн", "скрыт", "перехват", "прослуш", "миниатюрн", "замаскирован"), "permit_type": "ЛЗ"},
    {"section": "2.20", "prefixes": ("42", "44", "46", "49", "57", "58", "69", "70", "80", "81", "82", "83", "86", "87", "88", "89", "92", "93", "94", "95", "96", "97"), "markers": ("культурн", "антиквариат", "архив", "картина", "икона", "старинн", "коллекц", "рукопис", "археолог", "историческ"), "permit_type": "ЛЗ"},
    {"section": "2.21", "prefixes": ("0511", "3001", "3002"), "markers": ("орган человека", "ткань человека", "кровь человека", "биоматериал"), "permit_type": "ЛЗ"},
    {"section": "2.22", "prefixes": ("9301", "9302", "9303", "9304", "9305", "9306", "9307"), "markers": ("оруж", "патрон", "боеприпас", "холодное оружие"), "permit_type": "ЛЗ"},
    {"section": "2.23", "prefixes": ("4901", "4911", "8523"), "match_without_code": True, "markers": ("недра", "геологическ", "месторожд", "керн"), "permit_type": "ЛЗ"},
    {"section": "2.30", "prefixes": ("2903", "2910", "2914", "2920", "3808", "3824"), "markers": ("эталон", "лабораторн", "исследован"), "permit_type": "ЛЗ"},
)

# 20 строк раздела 2.16. Дубликаты 8526/8527 между пунктами сохранены в источнике,
# но runtime использует уникальные диапазоны.
DECISION_30_SECTION_216_RANGES = (
    "8419", "8514", "8540", "8543", "9018", "9027",
    "8470", "8471", "8517", "8518", "8519", "8521", "8525", "8526",
    "8527", "8528", "8531", "90", "8526", "8527",
)

# 113 строк раздела 2.19; повторяющиеся диапазоны относятся к разным видам товара.
DECISION_30_SECTION_219_RANGES = tuple("""
844331 8443321009 8443323000 8443991000 8470100000 8471300000
8471300000 8471410000 8471490000 8471500000 8471900000 8473302008
8471705000 8471709800 8471800000 8473211000 8473219000 8473302008
8473308000 8517110000 8517130000 8517140000 8517180000 8517610001
8517610002 8517610008 851762000 8517693900 8517699000 851779000
8523293101 8523293102 852329330 852329390 8523492500 8523493100
8523493900 8523494500 8523499101 8523499300 8523519101 8523519300
852352 8523599101 8523599300 8523809101 8523809300 370400 370500
3706 482110 4901100000 4901990000 4911990000 8523210000 8523293101
8523293102 852329330 852329390 8523492500 8523493100 8523493900
8523494500 8523499101 8523499300 8523519101 8523519300 852352
8523599101 8523599300 8523809101 8523809300 8525500000 852560000
8529902002 852990650 8529909600 8526912000 8526918000 852692000
852990650 8529909600 851762000 8528711500 852990650 8529909600
8542319010 8542319090 8542329000 8543708000 8543900000 370400
370500 3706 482110 4901100000 4901990000 4911990000 852329310
852329330 852329390 8523299000 8523494500 8523495100 8523495900
8523499300 8523499900 8523519300 8523519900 8523599300 8523599900
8523809300 8523809900
""".split())

# Объединение двух официальных разделов содержит ровно 93 уникальных диапазона.
DECISION_30_UNIQUE_RANGES = tuple(sorted(
    set(DECISION_30_SECTION_216_RANGES) | set(DECISION_30_SECTION_219_RANGES),
    key=lambda value: (len(value), value),
))

OFFICIAL_NTM_FAMILIES: tuple[dict[str, str], ...] = (
    {"family": "technical_conformity", "label": "Технические регламенты и оценка соответствия"},
    {"family": "sanitary_registration", "label": "Санитарные меры и СГР"},
    {"family": "veterinary_control", "label": "Ветеринарный контроль"},
    {"family": "phytosanitary_control", "label": "Фитосанитарный контроль"},
    {"family": "radio_frequency", "label": "Радиоэлектронные и высокочастотные устройства"},
    {"family": "cryptography", "label": "Шифровальные (криптографические) средства"},
    {"family": "licensing", "label": "Лицензирование и разрешительный порядок"},
    {"family": "prohibitions_restrictions", "label": "Запреты и иные ограничения"},
    {"family": "export_control_dual_use", "label": "Экспортный контроль и товары двойного назначения"},
)

# Активные товарные позиции табличной части раздела II Единого перечня к
# Решению КТС №299. Большинство строк содержит оговорку «из», поэтому код
# используется только как кандидат для ручной проверки назначения товара.
DECISION_299_SGR_RANGES: tuple[str, ...] = tuple("""
0305 0306 0307 0308 1604 1605 2104 2505 2508 2512000000 2828 2829
2915 2916 2917 2918 2919 2920 2921 2922 2923 2924 2925 2926 2927000000
2929 2930 2931 2932 2933 293500 3202 3204 3205000000 3206 3207 3208
3209 321000 3212 3214 3307 340220 340290 3403 3405400000 3506 3802
3808 3809 381400 3820000000 3824 3901 3902 3903 3904 3905 3906
3907 3908 3909 3910 3911 3912 3913 3914000000 3917 3919 3920 3924
3925100000 3926 4014 480300 4805 4810 4811 4818 482320000 482370
5903 5906 5910000000 5911200000 5911400000 6307 7306 7307 7411
7412 8413 851240000 851610 902910000 9603210000 961900 4812000000
""".split())

# Единый перечень товаров, подлежащих ветеринарному контролю, к Решению
# Комиссии Таможенного союза №317. В основной набор вынесены позиции, где
# животное происхождение следует уже из товарной позиции; условные строки
# (корма, ветпрепараты, бывшее в употреблении оборудование) проверяются ниже
# одновременно по коду и назначению из наименования.
DECISION_317_VET_GENERAL_RANGES: tuple[str, ...] = tuple("""
0101 0102 0103 0104 0105 0106
0201 0202 0203 0204 0205 0206 0207 0208 0209 0210
0301 0302 0303 0304 0305 0306 0307 0308 0309
0401 0402 0403 0404 0405 0406 0407 0408 0409 0410
0502 0504 0505 0506 0507 0510 0511
1501 1502 1503 1504 1505 1506
1601 1602 1603 1604 1605 2301
4101 4102 4103 4206 4301 5101 5102 5103
""".split())

_VET_FEED_MARKERS = ("корм", "фураж", "для животных", "feed")
_VET_ANIMAL_PRODUCT_MARKERS = (
    "животн", "молок", "молоч", "мяс", "рыб", "яич", "яйц", "мороженое",
)
_VET_MEDICAL_MARKERS = (
    "ветеринар", "ветпрепарат", "вакцин", "диагност", "микроорганизм",
    "биологическ", "дезинфиц", "фермент", "пептон",
)
_VET_USED_MARKERS = ("бывш", "употреблен", "употреблён", "использованн")
_VET_EQUIPMENT_MARKERS = (
    "животн", "птиц", "пчел", "инкубатор", "стойл", "клетк", "перевозк",
    "разведен", "разведён", "содержан",
)

_DECISION_317_VET_CONDITIONAL_RULES: tuple[dict[str, Any], ...] = (
    {
        "prefixes": (
            "0713109001", "0713500000", "1001", "1002", "1003", "1004", "1005",
            "1201", "1208", "1211", "1212", "1213", "1214", "1301",
            "2302", "2303", "2304", "2306", "2308", "2309",
        ),
        "marker_groups": (_VET_FEED_MARKERS,),
        "scope": "кормовое назначение",
    },
    {
        "prefixes": ("1516", "1518", "1521", "1901", "1902", "1904", "20", "2102", "2104", "2105", "2106"),
        "marker_groups": (_VET_ANIMAL_PRODUCT_MARKERS,),
        "scope": "компоненты животного происхождения",
    },
    {
        "prefixes": ("29", "30", "3101", "3501", "3502", "3503", "3504", "3507", "3808", "3821", "3822"),
        "marker_groups": (_VET_MEDICAL_MARKERS,),
        "scope": "ветеринарное/биологическое назначение",
    },
    {
        "prefixes": ("9508", "9705"),
        "marker_groups": (_VET_EQUIPMENT_MARKERS,),
        "scope": "живые животные или зоологические коллекции",
    },
    {
        "prefixes": ("3923", "3926", "4415", "4416", "4421", "7020", "7309", "7310", "7326", "7616", "8436", "8606", "8609", "8716"),
        "marker_groups": (_VET_USED_MARKERS, _VET_EQUIPMENT_MARKERS),
        "scope": "бывшее в употреблении оборудование для животных",
    },
)

# Высокий риск: фитосанитарный сертификат является возможным документом только
# после проверки кода вместе с наименованием и исключениями. Намеренно нет
# широких 0712, 08 или 09: они смешивают высокий и низкий риск.
DECISION_318_PHYTO_HIGH_RISK_RANGES: tuple[str, ...] = tuple("""
0106410008 0106490001
0601 0602 0603 0604
0701 0702 0703 0704 0705 0706 0707 0708 0709 0712901100 0713 0714
0801 0802 0803 0804 0805 0806 0807 0808 0809 0810 0813
090111 090112
1001 1002 1003 1004 1005 1006 1007 1008
1101 1102 1103 1104 1106100000 1107
1201 1202 1203 1204 1205 1206 1207 1208 1209 1211 1212 1213 1214
1401 1404 1801 1802 2302 2304 2305 2306 2530900009 2703000000
300249 300259 3101
4401 4403 4404 4406 4407 4409 4415 441840
970522 970529
""".split())

# Низкий риск включён в официальный перечень карантинной продукции, но ввозится
# и перемещается без фитосанитарного сертификата. Упаковка и степень переработки
# всё равно требуют проверки по примечаниям перечня.
DECISION_318_PHYTO_LOW_RISK_RANGES: tuple[str, ...] = tuple("""
0505 0506 0712 090121 090122 0902 0903 0904 0905 0906 0907 0908 0909 0910
1903 2103 2308 2309 2401 3203 4101 4102 4103 4408 4416 4418
4601 4602 4808 4819 5001 5003 5101 5102 5103 5201 5202
5301 5302 5303 5304 5305
""".split())

_RADIO_MARKERS = (
    "радио", "передат", "приемник", "приёмник", "wifi", "wi-fi", "bluetooth",
    "gsm", "lte", "5g", "nfc", "gps", "беспровод", "высокочастот",
)
_CRYPTO_MARKERS = (
    "шифр", "крипт", "vpn", "tls", "aes", "защищенн", "защищённ",
)
_TABLEWARE_MARKERS = (
    "посуда", "тарел", "чашк", "кружк", "блюдц", "миска", "кастрюл",
    "сковород", "столовый прибор", "столовые прибор", "ложк", "вилк", "нож",
)
_CHILD_MARKERS = ("детск", "для детей", "младен", "baby", "ребен", "ребён")
_ADULT_MARKERS = ("для взрослых", "взрослая", "взрослый")

# Код является первичным фильтром: эти регламенты зависят от назначения и
# характеристик товара. Строки остаются advisory и не участвуют в enforcement.
_TECHNICAL_CHARACTERISTIC_RULES: tuple[dict[str, Any], ...] = (
    {
        "tr_ts": "007/2011",
        "prefixes": ("3304", "3305", "3306", "3307", "4202", "4818", "4820", "4903", "6107", "6108", "6111", "6207", "6208", "6209", "6401", "6402", "6403", "6404", "6405", "6505"),
        "markers": _CHILD_MARKERS,
        "permit_type": "ДС/СС/СГР",
        "title": "Продукция для детей и подростков",
        "source_url": TR_TS_007_URL,
    },
    {
        "tr_ts": "015/2011",
        "prefixes": ("1001", "1002", "1003", "1004", "1005", "1006", "1007", "1008"),
        "markers": ("зерно", "пшениц", "рожь", "ячмень", "овес", "овёс", "кукуруз", "рис", "сорго", "гречих", "просо"),
        "permit_type": "ДС",
        "title": "Зерно",
        "source_url": TR_TS_015_URL,
    },
    {
        "tr_ts": "026/2012",
        "prefixes": ("8903", "8906"),
        "markers": ("маломерн", "катер", "яхт", "моторная лодка", "прогулочное судно"),
        "permit_type": "ДС/СС",
        "title": "Маломерные суда",
        "source_url": TR_TS_026_URL,
    },
    {
        "tr_ts": "036/2016",
        "prefixes": ("2711",),
        "markers": ("сжиженн", "пропан", "бутан", "углеводородный газ", "углеводородного газа"),
        "permit_type": "ДС",
        "title": "Сжиженные углеводородные газы для использования как топливо",
        "source_url": TR_EAEU_036_URL,
    },
    {
        "tr_ts": "050/2021",
        "prefixes": ("3926", "4015", "6210", "6307", "8424", "8531", "9020"),
        "markers": ("гражданск", "чрезвычайн", "аварийн", "спасательн", "пожарн", "противогаз", "защитный костюм", "защитная одежда"),
        "permit_type": "ДС/СС",
        "title": "Продукция для гражданской обороны и защиты от чрезвычайных ситуаций",
        "source_url": TR_EAEU_050_URL,
    },
    {
        "tr_ts": "051/2021",
        "prefixes": ("0207", "160231", "160232", "160239"),
        "markers": ("птиц", "кур", "индей", "утк", "гус", "перепел", "цесарк"),
        "permit_type": "ДС",
        "title": "Мясо птицы и продукция его переработки",
        "source_url": TR_EAEU_051_URL,
    },
    {
        "tr_ts": "052/2021",
        "prefixes": ("8605",),
        "markers": ("метрополитен", "вагон метро", "подвижной состав метро"),
        "permit_type": "СС",
        "title": "Подвижной состав метрополитена",
        "source_url": TR_EAEU_052_URL,
    },
)

_TABLEWARE_RULES: tuple[dict[str, Any], ...] = (
    {"prefixes": ("6911", "6912"), "material": ("керами", "фарфор", "фаянс"),
     "standards": ("ГОСТ 28390-89", "ГОСТ 28391-89")},
    {"prefixes": ("7323",), "material": ("сталь", "стальн", "нержав", "эмалир"),
     "standards": ("ГОСТ 24788-2018", "ГОСТ 27002-2020")},
    {"prefixes": ("7615",), "material": ("алюмин",), "standards": ("ГОСТ 17151-81",)},
    {"prefixes": ("8211", "8215"), "material": ("сталь", "металл", "нержав"),
     "standards": ("ГОСТ 27002-2020",)},
    {"prefixes": ("7013",), "material": ("стекл", "хруст"), "standards": ("ГОСТ 30407-2019",)},
    {"prefixes": ("3924",), "material": ("пласт", "полимер"), "standards": ("ГОСТ Р 50962-96",)},
)


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def is_official_ntm_advisory_enabled() -> bool:
    raw = os.environ.get("NTM_V2_OFFICIAL_FULL_ADVISORY_ENABLED")
    # Ivan approved the advisory-only rollout on 2026-08-15. Keep an explicit
    # operational kill switch; this does not enable broker enforcement.
    if raw is None or not raw.strip():
        return True
    if raw.strip().lower() in {"0", "false", "no", "off"}:
        return False
    return _env_truthy("NTM_V2_OFFICIAL_FULL_ADVISORY_ENABLED")


def should_apply_official_ntm_advisory(explicit: bool | None = None) -> bool:
    return explicit if explicit is not None else is_official_ntm_advisory_enabled()


def _matches_any_prefix(code: str, ranges: tuple[str, ...]) -> str | None:
    matches = [prefix for prefix in set(ranges) if code.startswith(prefix)]
    return max(matches, key=len) if matches else None


def _contains_any(description: str, markers: tuple[str, ...]) -> bool:
    desc = (description or "").lower()
    return any(marker in desc for marker in markers)


def _contains_all_marker_groups(
    description: str,
    marker_groups: tuple[tuple[str, ...], ...],
) -> bool:
    return all(_contains_any(description, group) for group in marker_groups)


def _advisory_row(**values: Any) -> dict[str, Any]:
    return {
        "source": OFFICIAL_NTM_SOURCE_KIND,
        "source_label": OFFICIAL_NTM_SOURCE_LABEL,
        "used_for_missing_check": False,
        "requires_manual_review": True,
        **values,
    }


def _section_meta(section: str) -> dict[str, str]:
    return next(item for item in DECISION_30_SECTIONS if item["section"] == section)


def _decision_30_special_requirements(code: str, description: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rule in _DECISION_30_SPECIAL_RULES:
        matched = _matches_any_prefix(code, rule["prefixes"])
        description_matched = _contains_any(description, rule["markers"])
        if _matches_any_prefix(code, rule.get("exclude_prefixes", ())):
            continue
        if _contains_any(description, rule.get("exclude_markers", ())):
            continue
        if not matched and not (rule.get("match_without_code") and description_matched):
            continue
        meta = _section_meta(str(rule["section"]))
        family = "prohibitions_restrictions" if meta["kind"] == "prohibition" else "licensing"
        rows.append(_advisory_row(
            family=family,
            permit_type=rule["permit_type"],
            tr_ts=None,
            applicability="needs_clarification",
            hs_prefix=matched,
            direction=meta["direction"],
            section=meta["section"],
            rule_name=f"Раздел {meta['section']} Единого перечня — {meta['title']}",
            reason=(
                "Код и наименование дают advisory-кандидата. Нужны точная строка перечня, состав/назначение и все исключения положения."
                if matched and description_matched else
                "Код или наименование является первичным фильтром. Для вывода нужны точная строка перечня, состав, назначение и направление перемещения."
            ),
            note=f"Решение Коллегии ЕЭК №30, раздел {meta['section']}",
            source_url=DECISION_30_UNIFIED_LIST_URL,
        ))
    return rows


def _decision_30_requirements(code: str, description: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    radio_scope = _matches_any_prefix(code, DECISION_30_SECTION_216_RANGES)
    radio_description = _contains_any(description, _RADIO_MARKERS)
    if radio_scope or radio_description:
        rows.append(_advisory_row(
            family="radio_frequency",
            permit_type="РЭВЧУ",
            tr_ts=None,
            applicability="needs_clarification",
            hs_prefix=radio_scope,
            direction="import",
            section="2.16",
            rule_name="Раздел 2.16 Единого перечня — РЭС и ВЧУ",
            reason=(
                "Описание указывает на встроенное РЭС/ВЧУ. Раздел 2.16 применяется независимо от кода готового товара; нужны частоты, мощность, назначение и проверка реестра исключений."
                if radio_description and not radio_scope else
                "Код и/или описание дают advisory-кандидата. Нужны сведения о передатчике/приёмнике, частотах, мощности, назначении и исключениях реестра."
            ),
            note="Решение Коллегии ЕЭК №30, раздел 2.16",
            source_url=DECISION_30_216_URL,
        ))
    crypto_scope = _matches_any_prefix(code, DECISION_30_SECTION_219_RANGES)
    if crypto_scope:
        rows.append(_advisory_row(
            family="cryptography",
            permit_type="НФ/ЛЗ",
            tr_ts=None,
            applicability="needs_clarification",
            hs_prefix=crypto_scope,
            direction="both",
            section="2.19",
            rule_name="Раздел 2.19 Единого перечня — криптографические средства",
            reason=(
                "Код и описание дают advisory-кандидата; форму документа определяют криптографические характеристики, назначение, реестр нотификаций и исключения."
                if _contains_any(description, _CRYPTO_MARKERS) else
                "Код входит в диапазон «из». Нужны сведения о криптографических функциях, назначении, реестре нотификаций и исключениях."
            ),
            note="Решение Коллегии ЕЭК №30, раздел 2.19",
            source_url=DECISION_30_219_URL,
        ))
    return rows


def _tableware_requirements(code: str, description: str) -> list[dict[str, Any]]:
    desc = (description or "").lower()
    if not _contains_any(desc, _TABLEWARE_MARKERS):
        return []
    rule = next((r for r in _TABLEWARE_RULES if _matches_any_prefix(code, r["prefixes"])), None)
    if not rule:
        return []
    material_confirmed = any(marker in desc for marker in rule["material"])
    child = _contains_any(desc, _CHILD_MARKERS)
    adult = _contains_any(desc, _ADULT_MARKERS)
    standards = ", ".join(rule["standards"])
    if child:
        return [_advisory_row(
            family="technical_conformity",
            permit_type="ДС/СГР",
            tr_ts="007/2011",
            applicability="needs_clarification",
            hs_prefix=_matches_any_prefix(code, rule["prefixes"]),
            rule_name="Посуда и столовые приборы для детей",
            reason="Нужно уточнить возраст, назначение, материал и схему оценки соответствия по ТР ТС 007/2011.",
            note=f"Стандарты для требований/испытаний: {standards}. ГОСТ не заменяет основание обязательной оценки.",
            source_url=TR_TS_007_URL,
        )]
    return [_advisory_row(
        family="technical_conformity",
        permit_type="ДС",
        tr_ts=None,
        applicability="needs_clarification",
        hs_prefix=_matches_any_prefix(code, rule["prefixes"]),
        rule_name="Посуда и столовые приборы для взрослых (национальный контур РФ)",
        reason=(
            "Код, вид, материал и назначение для взрослых совпали с advisory-контуром; требуется сверка точной позиции ПП РФ №2425 и исключений."
            if material_confirmed and adult else
            "Код и вид товара совпали, но нужно подтвердить материал, назначение для взрослых и отсутствие детского/декоративного исключения."
        ),
        note=f"ПП РФ №2425. Стандарты для требований/испытаний: {standards}; сам ГОСТ не создаёт обязанность оформить ДС.",
        source_url=PP_2425_URL,
    )]


def _technical_characteristic_requirements(code: str, description: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rule in _TECHNICAL_CHARACTERISTIC_RULES:
        matched = _matches_any_prefix(code, rule["prefixes"])
        if not matched:
            continue
        confirmed = _contains_any(description, rule["markers"])
        rows.append(_advisory_row(
            family="technical_conformity",
            permit_type=rule["permit_type"],
            tr_ts=rule["tr_ts"],
            applicability="needs_clarification",
            hs_prefix=matched,
            direction="import",
            rule_name=f"ТР ТС/ЕАЭС {rule['tr_ts']} — {rule['title']}",
            reason=(
                "Код и описание дают advisory-кандидата; точную форму оценки определяют вид товара, назначение и официальный перечень продукции."
                if confirmed else
                "Код является первичным фильтром. Нужны назначение, вид товара и характеристики для проверки официального перечня продукции."
            ),
            note="Advisory-контур: не используется для статуса и missing-check до загрузки точного перечня на уровне 10 знаков.",
            source_url=rule["source_url"],
        ))
    return rows


def _sanitary_registration_requirements(code: str, description: str) -> list[dict[str, Any]]:
    matched = _matches_any_prefix(code, DECISION_299_SGR_RANGES)
    if not matched:
        return []
    return [_advisory_row(
        family="sanitary_registration",
        permit_type="СГР",
        tr_ts=None,
        applicability="needs_clarification",
        hs_prefix=matched,
        direction="import",
        rule_name="Раздел II Единого перечня — продукция, подлежащая государственной регистрации",
        reason=(
            "Код входит в табличную часть раздела II. Нужны сведения о назначении, составе, "
            "области применения, первом ввозе и применимых исключениях/технических регламентах."
        ),
        note="Решение Комиссии Таможенного союза №299 от 28.05.2010; большинство позиций имеет условие «из» и определяется также по документам изготовителя.",
        source_url=DECISION_299_LIST_URL,
    )]


def _veterinary_requirements(code: str, description: str) -> list[dict[str, Any]]:
    matched = _matches_any_prefix(code, DECISION_317_VET_GENERAL_RANGES)
    scope = "товар животного происхождения"
    if not matched:
        for rule in _DECISION_317_VET_CONDITIONAL_RULES:
            candidate = _matches_any_prefix(code, rule["prefixes"])
            if not candidate:
                continue
            if not _contains_all_marker_groups(description, rule["marker_groups"]):
                continue
            matched = candidate
            scope = str(rule["scope"])
            break
    if not matched:
        return []
    return [_advisory_row(
        family="veterinary_control",
        permit_type="ВЕТКОНТРОЛЬ",
        tr_ts=None,
        applicability="needs_clarification",
        hs_prefix=matched,
        direction="import_or_transit",
        section=None,
        rule_name="Единый перечень товаров, подлежащих ветеринарному контролю",
        reason=(
            f"Выявлен advisory-кандидат ({scope}). Код необходимо проверить вместе с наименованием, "
            "назначением, обработкой и эпизоотическими условиями; вид документа не определяется одним кодом."
        ),
        note="Решение Комиссии Таможенного союза №317 от 18.06.2010. Совпадение не означает автоматически ветеринарный сертификат.",
        source_url=DECISION_317_LIST_URL,
    )]


def _phytosanitary_requirements(code: str, description: str) -> list[dict[str, Any]]:
    del description  # Наименование и упаковка нужны при последующем ручном уточнении.
    high_risk = _matches_any_prefix(code, DECISION_318_PHYTO_HIGH_RISK_RANGES)
    if high_risk:
        return [_advisory_row(
            family="phytosanitary_control",
            permit_type="ФСС",
            tr_ts=None,
            applicability="needs_clarification",
            hs_prefix=high_risk,
            direction="import_or_transit",
            section=None,
            risk_level="high",
            certificate_required=True,
            rule_name="Подкарантинная продукция высокого фитосанитарного риска",
            reason=(
                "Код является кандидатом высокого риска. Фитосанитарный сертификат указывается только advisory: "
                "нужно проверить наименование, назначение, обработку, упаковку и исключения перечня."
            ),
            note="Перечень — Решение КТС №318 от 18.06.2010; единые требования — Решение Совета ЕЭК №157 от 30.11.2016.",
            source_url=DECISION_318_LIST_URL,
            requirements_source_url=DECISION_157_REQUIREMENTS_URL,
        )]
    low_risk = _matches_any_prefix(code, DECISION_318_PHYTO_LOW_RISK_RANGES)
    if not low_risk:
        return []
    return [_advisory_row(
        family="phytosanitary_control",
        permit_type="ФИТОКОНТРОЛЬ (без ФСС)",
        tr_ts=None,
        applicability="needs_clarification",
        hs_prefix=low_risk,
        direction="import_or_transit",
        section=None,
        risk_level="low",
        certificate_required=False,
        rule_name="Подкарантинная продукция низкого фитосанитарного риска",
        reason=(
            "Позиция относится к низкому риску и по этому основанию перемещается без фитосанитарного сертификата. "
            "Нужно проверить точное наименование, степень переработки, упаковку и исключения перечня."
        ),
        note="Перечень — Решение КТС №318 от 18.06.2010; пункт 7 требований по Решению Совета ЕЭК №157 от 30.11.2016.",
        source_url=DECISION_318_LIST_URL,
        requirements_source_url=DECISION_157_REQUIREMENTS_URL,
    )]


def evaluate_official_ntm_contours(
    hs_code: str,
    description: str = "",
    *,
    legacy_family_hits: set[str] | None = None,
    family_signals: list[dict[str, Any]] | None = None,
    transaction_facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Возвращает advisory-строки и полный статусный срез семейств мер."""
    code = normalize_hs_code(hs_code)
    broad_requirements = [
        *_decision_30_requirements(code, description),
        *_decision_30_special_requirements(code, description),
        *_sanitary_registration_requirements(code, description),
        *_veterinary_requirements(code, description),
        *_phytosanitary_requirements(code, description),
        *_technical_characteristic_requirements(code, description),
        *_tableware_requirements(code, description),
    ]
    export_control = evaluate_export_control_requirement(code, description)
    if export_control:
        broad_requirements.append(export_control)
    exact_result = evaluate_official_ntm_exact_applicability(
        code,
        description,
        transaction_facts,
        broad_requirements=broad_requirements,
    )
    requirements = exact_result["requirements"]
    hits = {str(row["family"]) for row in requirements}
    hits.update(legacy_family_hits or set())
    signals = list(family_signals or [])
    hits.update(str(row.get("family")) for row in signals if row.get("family"))
    matrix = []
    for item in OFFICIAL_NTM_FAMILIES:
        family = item["family"]
        matched = [row for row in requirements if row.get("family") == family]
        matched_signals = [row for row in signals if row.get("family") == family]
        if matched:
            if any(
                row.get("applicability") == "definite"
                and row.get("requirement_applicable") is not False
                for row in matched
            ):
                status = "definite"
            elif any(row.get("applicability") == "needs_clarification" for row in matched):
                status = "needs_clarification"
            elif any(row.get("applicability") == "excluded" for row in matched):
                status = "legacy_signal" if matched_signals else "excluded"
            else:
                status = "needs_clarification"
        elif family in hits:
            status = "legacy_signal"
        else:
            status = "not_detected"
        matrix.append({
            **item,
            "status": status,
            "requirements_count": len(matched),
            "signals_count": len(matched_signals),
            "permit_types": sorted({str(row.get("permit_type")) for row in [*matched, *matched_signals] if row.get("permit_type")}),
            "regulations": sorted({str(row.get("tr_ts")) for row in [*matched, *matched_signals] if row.get("tr_ts")}),
            "source_labels": sorted({str(row.get("source_label") or row.get("source")) for row in [*matched, *matched_signals] if row.get("source_label") or row.get("source")}),
            "matched_sections": sorted({str(row.get("section")) for row in matched if row.get("section")}),
            "directions": sorted({str(row.get("direction")) for row in matched if row.get("direction")}),
        })
    return {
        "source_kind": OFFICIAL_NTM_SOURCE_KIND,
        "official_range_count": len(DECISION_30_UNIQUE_RANGES),
        "decision_30_section_count": len(DECISION_30_SECTIONS),
        "decision_299_sgr_range_count": len(DECISION_299_SGR_RANGES),
        "requirements": requirements,
        "measure_families": matrix,
        "exact_requirements": exact_result["exact_requirements"],
        "resolved_exclusions": exact_result["resolved_exclusions"],
        "catch_all": exact_result["catch_all"],
        "applicability_summary": {
            **exact_result["summary"],
            "definite_count": sum(
                row.get("applicability") == "definite" for row in requirements
            ),
            "needs_clarification_count": sum(
                row.get("applicability") == "needs_clarification" for row in requirements
            ),
        },
        "disclaimer": (
            "not_detected означает только отсутствие совпадения в подключённых контурах, "
            "а не юридическое отсутствие меры. Для экспорта отсутствие HS-совпадения также не "
            "исключает всеобъемлющий экспортный контроль; нужна проверка товара, технологии, сторон и цели сделки."
        ),
    }
