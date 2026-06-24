from __future__ import annotations

import os
import re
from typing import Any, Dict, List

import httpx
from bs4 import BeautifulSoup
from loguru import logger


# Официальный реестр ТРОИС (ФТС). При 404/403 используем локальный кэш.
TROIS_URLS = [
    "https://customs.gov.ru/registers/objects-intellectual-property",
    "https://customs.gov.ru/reestr",
]

# Интегрированная база товарных знаков в приложении (источник: открытые данные ФТС, TROIS).
# Расширенный список — 100+ брендов для поиска без внешних запросов.
def _mk(name: str, right_holder: str, goods: str) -> Dict[str, Any]:
    return {
        "status": "OK",
        "found": True,
        "details": [{"cols": [name.upper(), "Товарный знак", right_holder, goods]}],
        "note": "Данные в приложении. Официальная проверка: customs.gov.ru",
    }

_LOCAL_CACHE: Dict[str, Dict[str, Any]] = {
    # Электроника и IT
    "apple": _mk("Apple", "Apple Inc.", "Электроника, компьютеры"),
    "samsung": _mk("Samsung", "Samsung Electronics", "Электроника"),
    "huawei": _mk("Huawei", "Huawei Technologies", "Электроника"),
    "xiaomi": _mk("Xiaomi", "Xiaomi Inc.", "Электроника"),
    "sony": _mk("Sony", "Sony Corporation", "Электроника"),
    "lg": _mk("LG", "LG Electronics", "Электроника"),
    "asus": _mk("ASUS", "ASUSTeK Computer Inc.", "Электроника, компьютеры"),
    "lenovo": _mk("Lenovo", "Lenovo Group Ltd.", "Электроника, компьютеры"),
    "dell": _mk("Dell", "Dell Inc.", "Электроника, компьютеры"),
    "hp": _mk("HP", "HP Inc.", "Электроника, компьютеры"),
    "acer": _mk("Acer", "Acer Inc.", "Электроника"),
    "msi": _mk("MSI", "Micro-Star International", "Электроника"),
    "philips": _mk("Philips", "Koninklijke Philips N.V.", "Электроника, бытовая техника"),
    "panasonic": _mk("Panasonic", "Panasonic Corporation", "Электроника"),
    "toshiba": _mk("Toshiba", "Toshiba Corporation", "Электроника"),
    "canon": _mk("Canon", "Canon Inc.", "Фото- и видеотехника"),
    "nikon": _mk("Nikon", "Nikon Corporation", "Фототехника"),
    "gopro": _mk("GoPro", "GoPro Inc.", "Видеокамеры"),
    "dyson": _mk("Dyson", "Dyson Ltd.", "Бытовая техника"),
    "jbl": _mk("JBL", "Harman International", "Аудиотехника"),
    "bose": _mk("Bose", "Bose Corporation", "Аудиотехника"),
    "beats": _mk("Beats", "Beats Electronics", "Аудиотехника"),
    "oppo": _mk("OPPO", "Guangdong OPPO Mobile Telecommunications", "Смартфоны"),
    "vivo": _mk("Vivo", "Vivo Communication Technology", "Смартфоны"),
    "oneplus": _mk("OnePlus", "OnePlus Technology", "Смартфоны"),
    "realme": _mk("Realme", "Realme Chongqing Mobile Telecommunications", "Смартфоны"),
    "honor": _mk("Honor", "Honor Device Co.", "Смартфоны"),
    "zte": _mk("ZTE", "ZTE Corporation", "Электроника"),
    "motorola": _mk("Motorola", "Motorola Mobility LLC", "Смартфоны"),
    "nokia": _mk("Nokia", "Nokia Corporation", "Электроника"),
    "blackberry": _mk("BlackBerry", "BlackBerry Limited", "Смартфоны"),
    "google": _mk("Google", "Google LLC", "Электроника, ПО"),
    "microsoft": _mk("Microsoft", "Microsoft Corporation", "ПО, электроника"),
    "intel": _mk("Intel", "Intel Corporation", "Микропроцессоры"),
    "amd": _mk("AMD", "Advanced Micro Devices", "Микропроцессоры"),
    "nvidia": _mk("NVIDIA", "NVIDIA Corporation", "Видеокарты"),
    "logitech": _mk("Logitech", "Logitech International", "Периферия"),
    "razer": _mk("Razer", "Razer Inc.", "Игровое оборудование"),
    "steelseries": _mk("SteelSeries", "SteelSeries ApS", "Игровое оборудование"),
    # Бытовая техника
    "bosch": _mk("Bosch", "Robert Bosch GmbH", "Бытовая техника"),
    "siemens": _mk("Siemens", "BSH Hausgeräte GmbH", "Бытовая техника"),
    "electrolux": _mk("Electrolux", "Electrolux AB", "Бытовая техника"),
    "whirlpool": _mk("Whirlpool", "Whirlpool Corporation", "Бытовая техника"),
    "miele": _mk("Miele", "Miele & Cie. KG", "Бытовая техника"),
    "indesit": _mk("Indesit", "Indesit Company", "Бытовая техника"),
    "beko": _mk("Beko", "Arçelik A.Ş.", "Бытовая техника"),
    "zanussi": _mk("Zanussi", "Electrolux AB", "Бытовая техника"),
    "gorenje": _mk("Gorenje", "Gorenje d.d.", "Бытовая техника"),
    "tefal": _mk("Tefal", "Groupe SEB", "Кухонная техника"),
    "moulinex": _mk("Moulinex", "Groupe SEB", "Кухонная техника"),
    "braun": _mk("Braun", "Procter & Gamble", "Бытовая техника"),
    "rowenta": _mk("Rowenta", "Groupe SEB", "Бытовая техника"),
    "de longhi": _mk("De'Longhi", "De'Longhi S.p.A.", "Кухонная техника"),
    "delonghi": _mk("De'Longhi", "De'Longhi S.p.A.", "Кухонная техника"),
    "redmond": _mk("Redmond", "Redmond", "Бытовая техника"),
    "polaris": _mk("Polaris", "Polaris", "Бытовая техника"),
    "vitek": _mk("Vitek", "Vitek", "Бытовая техника"),
    "scarlett": _mk("Scarlett", "Scarlett", "Бытовая техника"),
    # Одежда и обувь
    "nike": _mk("Nike", "Nike Innovate C.V.", "Одежда, обувь"),
    "adidas": _mk("Adidas", "Adidas AG", "Одежда, обувь"),
    "puma": _mk("Puma", "Puma SE", "Одежда, обувь"),
    "reebok": _mk("Reebok", "Reebok International", "Одежда, обувь"),
    "new balance": _mk("New Balance", "New Balance Athletics", "Обувь"),
    "under armour": _mk("Under Armour", "Under Armour Inc.", "Спортивная одежда"),
    "champion": _mk("Champion", "HanesBrands Inc.", "Одежда"),
    "converse": _mk("Converse", "Nike Inc.", "Обувь"),
    "vans": _mk("Vans", "VF Corporation", "Обувь"),
    "timberland": _mk("Timberland", "VF Corporation", "Обувь"),
    "dr. martens": _mk("Dr. Martens", "Dr. Martens plc", "Обувь"),
    "drmartens": _mk("Dr. Martens", "Dr. Martens plc", "Обувь"),
    "ugg": _mk("UGG", "Deckers Outdoor Corporation", "Обувь"),
    "lacoste": _mk("Lacoste", "Lacoste S.A.", "Одежда"),
    "chanel": _mk("Chanel", "Chanel S.A.", "Одежда, парфюмерия"),
    "gucci": _mk("Gucci", "Gucci America Inc.", "Одежда, аксессуары"),
    "prada": _mk("Prada", "Prada S.p.A.", "Одежда, аксессуары"),
    "armani": _mk("Armani", "Giorgio Armani S.p.A.", "Одежда"),
    "versace": _mk("Versace", "Gianni Versace S.r.l.", "Одежда"),
    "burberry": _mk("Burberry", "Burberry Group plc", "Одежда"),
    "hermes": _mk("Hermès", "Hermès International", "Одежда, аксессуары"),
    "hugo boss": _mk("Hugo Boss", "Hugo Boss AG", "Одежда"),
    "hugoboss": _mk("Hugo Boss", "Hugo Boss AG", "Одежда"),
    "tommy hilfiger": _mk("Tommy Hilfiger", "PVH Corp.", "Одежда"),
    "calvin klein": _mk("Calvin Klein", "PVH Corp.", "Одежда"),
    "levi's": _mk("Levi's", "Levi Strauss & Co.", "Одежда"),
    "levis": _mk("Levi's", "Levi Strauss & Co.", "Одежда"),
    "zara": _mk("Zara", "Inditex S.A.", "Одежда"),
    "h&m": _mk("H&M", "H&M Hennes & Mauritz AB", "Одежда"),
    "hm": _mk("H&M", "H&M Hennes & Mauritz AB", "Одежда"),
    "uniqlo": _mk("Uniqlo", "Fast Retailing Co.", "Одежда"),
    "the north face": _mk("The North Face", "VF Corporation", "Одежда"),
    "columbia": _mk("Columbia", "Columbia Sportswear Company", "Одежда"),
    "patagonia": _mk("Patagonia", "Patagonia Inc.", "Одежда"),
    "moncler": _mk("Moncler", "Moncler S.p.A.", "Одежда"),
    "canada goose": _mk("Canada Goose", "Canada Goose Inc.", "Одежда"),
    # Автомобили
    "bmw": _mk("BMW", "BMW AG", "Автомобили"),
    "mercedes": _mk("Mercedes-Benz", "Mercedes-Benz Group AG", "Автомобили"),
    "mercedes-benz": _mk("Mercedes-Benz", "Mercedes-Benz Group AG", "Автомобили"),
    "audi": _mk("Audi", "Audi AG", "Автомобили"),
    "volkswagen": _mk("Volkswagen", "Volkswagen AG", "Автомобили"),
    "vw": _mk("Volkswagen", "Volkswagen AG", "Автомобили"),
    "porsche": _mk("Porsche", "Porsche AG", "Автомобили"),
    "toyota": _mk("Toyota", "Toyota Motor Corporation", "Автомобили"),
    "honda": _mk("Honda", "Honda Motor Co.", "Автомобили"),
    "nissan": _mk("Nissan", "Nissan Motor Co.", "Автомобили"),
    "mazda": _mk("Mazda", "Mazda Motor Corporation", "Автомобили"),
    "hyundai": _mk("Hyundai", "Hyundai Motor Company", "Автомобили"),
    "kia": _mk("KIA", "Kia Corporation", "Автомобили"),
    "ford": _mk("Ford", "Ford Motor Company", "Автомобили"),
    "chevrolet": _mk("Chevrolet", "General Motors", "Автомобили"),
    "jeep": _mk("Jeep", "Stellantis", "Автомобили"),
    "land rover": _mk("Land Rover", "Jaguar Land Rover", "Автомобили"),
    "jaguar": _mk("Jaguar", "Jaguar Land Rover", "Автомобили"),
    "volvo": _mk("Volvo", "Volvo Cars", "Автомобили"),
    "renault": _mk("Renault", "Renault S.A.", "Автомобили"),
    "peugeot": _mk("Peugeot", "Stellantis", "Автомобили"),
    "citroen": _mk("Citroën", "Stellantis", "Автомобили"),
    "skoda": _mk("Škoda", "Škoda Auto", "Автомобили"),
    "geely": _mk("Geely", "Zhejiang Geely Holding Group", "Автомобили"),
    "haval": _mk("Haval", "Great Wall Motors", "Автомобили"),
    # Косметика и парфюмерия
    "l'oreal": _mk("L'Oréal", "L'Oréal S.A.", "Косметика"),
    "loreal": _mk("L'Oréal", "L'Oréal S.A.", "Косметика"),
    "estee lauder": _mk("Estée Lauder", "Estée Lauder Companies", "Косметика"),
    "dior": _mk("Dior", "Parfums Christian Dior", "Парфюмерия"),
    "ysl": _mk("YSL", "Yves Saint Laurent", "Парфюмерия"),
    "ysl saint laurent": _mk("YSL", "Yves Saint Laurent", "Парфюмерия"),
    "lancome": _mk("Lancôme", "L'Oréal", "Косметика"),
    "clinique": _mk("Clinique", "Estée Lauder", "Косметика"),
    "mac": _mk("MAC", "Estée Lauder", "Косметика"),
    "kiehl's": _mk("Kiehl's", "L'Oréal", "Косметика"),
    "kiehls": _mk("Kiehl's", "L'Oréal", "Косметика"),
    "nivea": _mk("Nivea", "Beiersdorf AG", "Косметика"),
    "gillette": _mk("Gillette", "Procter & Gamble", "Бритвы"),
    "schick": _mk("Schick", "Edgewell Personal Care", "Бритвы"),
    "oral-b": _mk("Oral-B", "Procter & Gamble", "Гигиена полости рта"),
    "oralb": _mk("Oral-B", "Procter & Gamble", "Гигиена полости рта"),
    "pantene": _mk("Pantene", "Procter & Gamble", "Уход за волосами"),
    "head & shoulders": _mk("Head & Shoulders", "Procter & Gamble", "Уход за волосами"),
    "headandshoulders": _mk("Head & Shoulders", "Procter & Gamble", "Уход за волосами"),
    "dove": _mk("Dove", "Unilever", "Косметика"),
    "rexona": _mk("Rexona", "Unilever", "Дезодоранты"),
    "axe": _mk("Axe", "Unilever", "Дезодоранты"),
    # Детские товары, игрушки
    "lego": _mk("Lego", "The Lego Group", "Игрушки"),
    "mattel": _mk("Mattel", "Mattel Inc.", "Игрушки"),
    "hasbro": _mk("Hasbro", "Hasbro Inc.", "Игрушки"),
    "fisher-price": _mk("Fisher-Price", "Mattel", "Игрушки"),
    "chicco": _mk("Chicco", "Artsana S.p.A.", "Детские товары"),
    # Фармацевтика
    "pfizer": _mk("Pfizer", "Pfizer Inc.", "Фармацевтика"),
    "но-шпа": _mk("НО-ШПА", "Sanofi", "Фармацевтика"),
    "ношпа": _mk("НО-ШПА", "Sanofi", "Фармацевтика"),
    "novartis": _mk("Novartis", "Novartis AG", "Фармацевтика"),
    "roche": _mk("Roche", "F. Hoffmann-La Roche AG", "Фармацевтика"),
    "bayer": _mk("Bayer", "Bayer AG", "Фармацевтика"),
    "abbvie": _mk("AbbVie", "AbbVie Inc.", "Фармацевтика"),
    "johnson": _mk("Johnson & Johnson", "Johnson & Johnson", "Фармацевтика, косметика"),
    "johnson&johnson": _mk("Johnson & Johnson", "Johnson & Johnson", "Фармацевтика"),
    # Продукты питания
    "балтика": _mk("Балтика", "Carlsberg Group", "Пиво"),
    "coca-cola": _mk("Coca-Cola", "The Coca-Cola Company", "Напитки"),
    "cocacola": _mk("Coca-Cola", "The Coca-Cola Company", "Напитки"),
    "pepsi": _mk("Pepsi", "PepsiCo Inc.", "Напитки"),
    "nestle": _mk("Nestlé", "Nestlé S.A.", "Продукты питания"),
    "danone": _mk("Danone", "Danone S.A.", "Молочные продукты"),
    "unilever": _mk("Unilever", "Unilever plc", "Продукты питания, косметика"),
    "mars": _mk("Mars", "Mars Inc.", "Кондитерские изделия"),
    "ferrero": _mk("Ferrero", "Ferrero S.p.A.", "Кондитерские изделия"),
    "mondelez": _mk("Mondelez", "Mondelez International", "Кондитерские изделия"),
    "kellogg's": _mk("Kellogg's", "Kellanova", "Сухие завтраки"),
    "heinz": _mk("Heinz", "The Kraft Heinz Company", "Продукты питания"),
    "campbell": _mk("Campbell", "Campbell Soup Company", "Продукты питания"),
    # Часы и ювелирные изделия
    "rolex": _mk("Rolex", "Rolex SA", "Часы"),
    "omega": _mk("Omega", "Swatch Group", "Часы"),
    "cartier": _mk("Cartier", "Cartier International", "Часы, ювелирные изделия"),
    "tissot": _mk("Tissot", "Swatch Group", "Часы"),
    "casio": _mk("Casio", "Casio Computer Co.", "Часы, электроника"),
    "garmin": _mk("Garmin", "Garmin Ltd.", "Часы, навигация"),
    "fitbit": _mk("Fitbit", "Google LLC", "Фитнес-трекеры"),
    # Прочее
    "ikea": _mk("IKEA", "Inter IKEA Systems B.V.", "Мебель, товары для дома"),
    "le creuset": _mk("Le Creuset", "Le Creuset S.A.S.", "Посуда"),
    "tupperware": _mk("Tupperware", "Tupperware Brands", "Посуда"),
    "victorinox": _mk("Victorinox", "Victorinox AG", "Ножи, часы"),
    "zippo": _mk("Zippo", "Zippo Manufacturing Company", "Зажигалки"),
    "ray-ban": _mk("Ray-Ban", "EssilorLuxottica", "Очки"),
    "rayban": _mk("Ray-Ban", "EssilorLuxottica", "Очки"),
    "oakley": _mk("Oakley", "EssilorLuxottica", "Очки"),
    "persol": _mk("Persol", "EssilorLuxottica", "Очки"),
}

TROIS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
}
TROIS_VERIFY_SSL = os.getenv("PERMITS_VERIFY_SSL", "true").lower() not in ("0", "false", "no")

TROIS_DISCLAIMER_RU = (
    "Данные реестра ТРОИС обновляются по расписанию (еженедельно). "
    "Для юридически значимой проверки используйте официальный реестр ФТС: "
    "customs.gov.ru/registers/objects-intellectual-property"
)

TROIS_OFFICIAL_URL = "https://customs.gov.ru/registers/objects-intellectual-property"

_db_cache_loaded = False


def _ensure_db_cache_loaded() -> None:
    global _db_cache_loaded
    if _db_cache_loaded:
        return
    try:
        from .trois_registry_loader import sync_db_to_local_cache

        sync_db_to_local_cache()
    except Exception as exc:
        logger.debug("TROIS DB cache load skipped: {}", exc)
    _db_cache_loaded = True


def _risk_level(found: bool, source: str, error: bool = False) -> str:
    """low | high | unchecked — для UI карточки товара."""
    if error:
        return "unchecked"
    if found:
        return "high"
    if source in ("local_cache", "db_registry", "fuzzy", "external", "search_complete"):
        return "low"
    return "unchecked"


def trouis_conflicts_in_text(text: str) -> List[str]:
    """Находит в тексте упоминания брендов из локального кэша и БД ТРОИС."""
    _ensure_db_cache_loaded()
    if not text or not str(text).strip():
        return []
    low = re.sub(r"\s+", " ", str(text).lower())
    hits: List[str] = []
    for key in _LOCAL_CACHE:
        k = key.strip().lower()
        if len(k) < 2:
            continue
        if len(k) >= 5:
            if k in low:
                hits.append(k)
        else:
            pat = r"(?<![a-z0-9а-яё])" + re.escape(k) + r"(?![a-z0-9а-яё])"
            if re.search(pat, low):
                hits.append(k)
    return sorted(set(hits))


def _find_in_cache_fuzzy(query: str) -> tuple[Dict[str, Any] | None, str]:
    """Поиск в in-memory кэше с fuzzy-вариантами."""
    from .trois_fuzzy import fuzzy_match_score, fuzzy_variants

    best: Dict[str, Any] | None = None
    best_score = 0.0
    for variant in fuzzy_variants(query):
        hit = _find_in_cache(variant)
        if hit:
            return hit, "local_cache"
        for cache_key, data in _LOCAL_CACHE.items():
            sc = fuzzy_match_score(variant, cache_key)
            if sc >= 0.82 and sc > best_score:
                best_score = sc
                best = dict(data)
                best["note"] = f"Fuzzy-match «{query}» → «{cache_key}» (score={sc:.2f}). {best.get('note', '')}"
    if best:
        return best, "fuzzy"
    return None, ""


def _find_in_cache(query: str) -> Dict[str, Any] | None:
    """Поиск в кэше: точное совпадение или по подстроке."""
    key = query.strip().lower()
    if not key:
        return None
    # Точное совпадение
    if key in _LOCAL_CACHE:
        return dict(_LOCAL_CACHE[key])
    # Поиск по подстроке: запрос содержится в ключе или наоборот
    for cache_key, data in _LOCAL_CACHE.items():
        if key in cache_key or cache_key in key:
            result = dict(data)
            result["note"] = f"Найдено по запросу «{query}». {result.get('note', '')}"
            return result
    return None


async def _fetch_from_trois(query: str) -> Dict[str, Any]:
    """Запрос к публичному ресурсу ТРОИС. При недоступности — возвращаем подсказку."""
    last_error = ""
    for url in TROIS_URLS:
        try:
            async with httpx.AsyncClient(
                timeout=15.0, follow_redirects=True, headers=TROIS_HEADERS, verify=TROIS_VERIFY_SSL
            ) as client:
                resp = await client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table")
            rows: List[Dict[str, Any]] = []
            if table:
                for tr in table.find_all("tr")[1:6]:
                    cols = [td.get_text(strip=True) for td in tr.find_all("td")]
                    if cols:
                        rows.append({"cols": cols})
            found = bool(rows)
            logger.info(f"ТРОИС {url}: found={found}, rows={len(rows)}")
            return {
                "status": "OK",
                "found": found,
                "details": rows,
                "note": "Проверьте данные на customs.gov.ru",
            }
        except Exception as e:
            last_error = str(e)
            logger.warning(f"ТРОИС {url}: {e}")
            continue
    raise RuntimeError(
        f"Реестр ТРОИС временно недоступен. Проверьте вручную: customs.gov.ru/registers/objects-intellectual-property. ({last_error})"
    )


async def check_trademark(query: str) -> Dict[str, Any]:
    """Проверка товарного знака: in-memory + БД trois_registry + fuzzy + внешний ФТС."""
    from .cache_layer import TROIS_PREFIX, cache_get, cache_set
    from .trois_registry_loader import search_db_registry

    key = (query or "").strip().lower()
    ttl = int(os.getenv("TROIS_CACHE_TTL_SECONDS", "7200"))
    if key:
        layer = await cache_get(TROIS_PREFIX, key)
        if layer is not None:
            return dict(layer)

    _ensure_db_cache_loaded()

    cached, source = _find_in_cache_fuzzy(query)
    if cached:
        cached.setdefault("status", "OK")
        cached["found"] = True
        cached["risk_level"] = _risk_level(True, source)
        cached["disclaimer"] = TROIS_DISCLAIMER_RU
        cached["official_url"] = TROIS_OFFICIAL_URL
        logger.info("ТРОИС: найден в кэше ({}) query={}", source, query)
        out = dict(cached)
        if key:
            await cache_set(TROIS_PREFIX, key, out, ttl)
        return out

    db_hits, db_warning = search_db_registry(query, max_results=5)
    if db_hits:
        from .opendata_registry import OPENDATA_TROIS_SOURCE, get_sync_freshness

        freshness = get_sync_freshness("trois") or {}
        data_as_of = freshness.get("data_as_of") or ""
        details = [
            {
                "cols": [
                    h.get("trademark") or h.get("brand") or "",
                    "Товарный знак",
                    h.get("right_holder") or "—",
                    h.get("reg_number") or "",
                ],
                "reg_number": h.get("reg_number"),
                "match_score": h.get("match_score"),
                "is_active": h.get("is_active"),
                "valid_until": h.get("valid_until"),
            }
            for h in db_hits
        ]
        note = f"Найдено в локальной БД реестра ({len(db_hits)} записей). {TROIS_DISCLAIMER_RU}"
        if data_as_of:
            note = f"Реестр ТРОИС ФТС, обновлён {data_as_of}. {note}"
        out = {
            "status": "OK",
            "found": True,
            "details": details,
            "source": "opendata_db",
            "registry_source": OPENDATA_TROIS_SOURCE,
            "data_as_of": data_as_of,
            "freshness_label": f"Реестр ТРОИС ФТС, обновлён {data_as_of}" if data_as_of else "",
            "risk_level": "high",
            "disclaimer": TROIS_DISCLAIMER_RU,
            "official_url": TROIS_OFFICIAL_URL,
            "note": note,
        }
        if db_warning:
            out["warning"] = db_warning
        if key:
            await cache_set(TROIS_PREFIX, key, out, ttl)
        return out

    try:
        data = await _fetch_from_trois(query)
        data["risk_level"] = _risk_level(bool(data.get("found")), "external")
        data["disclaimer"] = TROIS_DISCLAIMER_RU
        data["official_url"] = TROIS_OFFICIAL_URL
        if data.get("found"):
            _LOCAL_CACHE[query.strip().lower()] = data
        if key:
            await cache_set(TROIS_PREFIX, key, dict(data), ttl)
        return data
    except Exception:
        logger.warning("ТРОИС: внешний реестр недоступен")
        err_out = {
            "status": "ERROR",
            "found": False,
            "details": [],
            "error": "Реестр ТРОИС на customs.gov.ru временно недоступен. Проверьте вручную.",
            "note": f"В приложении {len(_LOCAL_CACHE)} брендов. Введите точное название или часть названия.",
            "risk_level": "unchecked",
            "disclaimer": TROIS_DISCLAIMER_RU,
            "official_url": TROIS_OFFICIAL_URL,
        }
        if key:
            await cache_set(TROIS_PREFIX, key, err_out, ttl)
        return err_out


def suggest_trois_brands(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Подсказки брендов из локального кэша (SequenceMatcher + fuzzy + подстрока)."""
    from difflib import SequenceMatcher

    from .trois_fuzzy import fuzzy_match_score, fuzzy_variants

    _ensure_db_cache_loaded()
    q = (query or "").strip().lower()
    if not q or len(q) < 2:
        return []
    keys = list(_LOCAL_CACHE.keys())
    scored: List[tuple[float, str]] = []
    for variant in fuzzy_variants(query):
        for k in keys:
            if variant in k:
                base = 0.52 + 0.33 * (len(variant) / max(len(k), 1))
            else:
                base = max(SequenceMatcher(None, variant, k).ratio(), fuzzy_match_score(variant, k))
            if base < 0.28:
                continue
            scored.append((base, k))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for score, k in scored:
        if k in seen:
            continue
        seen.add(k)
        row = _LOCAL_CACHE.get(k) or {}
        cols = (row.get("details") or [{}])[0].get("cols") if row.get("details") else []
        label = cols[0] if cols else k
        out.append({"key": k, "label": str(label), "note": row.get("note"), "score": round(min(score, 1.0), 3)})
        if len(out) >= limit:
            break
    return out


def get_trois_local_cache_stats() -> Dict[str, Any]:
    _ensure_db_cache_loaded()
    sample = sorted(_LOCAL_CACHE.keys())[:20]
    db_count = 0
    try:
        from .trois_registry_loader import count_db_brands

        db_count = count_db_brands()
    except Exception:
        pass
    return {
        "local_brands_count": len(_LOCAL_CACHE),
        "db_registry_rows": db_count,
        "sample_keys": sample,
        "disclaimer": TROIS_DISCLAIMER_RU,
    }


def load_extra_brands_from_file(path: str) -> int:
    """Доп. бренды из JSON: список или {\"brands\": [{name, right_holder, goods}]}. Возвращает число добавленных."""
    import json
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if isinstance(data, dict) and "brands" in data:
        items = data["brands"]
    elif isinstance(data, list):
        items = data
    else:
        return 0
    n = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or item.get("brand") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in _LOCAL_CACHE:
            continue
        holder = (item.get("right_holder") or item.get("holder") or "—").strip()
        goods = (item.get("goods") or item.get("products") or "—").strip()
        _LOCAL_CACHE[key] = _mk(name, holder, goods)
        n += 1
    return n
