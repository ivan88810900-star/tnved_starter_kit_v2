import re

from fastapi import APIRouter, Query, HTTPException, Depends
from typing import Optional, Any
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import Session
from ..db import get_db, SessionLocal
from ..models_hs import HSCode, Note
from ..models import TariffRate
from ..services import tariff_service
from ..services.permit_resolver import is_codeless_title, permit_measures_for_code

router = APIRouter(prefix="/codes", tags=["codes"])


def _norm_hs_digits(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def build_hierarchy_from_flat_hs_rows(
    rows: list[HSCode],
    duty_by_code: dict[str, str],
) -> list[dict[str, Any]]:
    """
    Плоский список HSCode → дерево: 4 знака — родитель, 6 — дочерний к 4, 10 — дочерний к 6.
    У каждого узла поле import_duty (из TariffRate.duty или пусто).
    """
    nodes: dict[str, dict[str, Any]] = {}

    def _duty(code: str) -> str:
        return (duty_by_code.get(code) or "").strip()

    def _ensure(code: str, title: str = "", duty: str = "") -> dict[str, Any]:
        if code not in nodes:
            nodes[code] = {
                "code": code,
                "title_ru": (title or "").strip(),
                "import_duty": duty,
                "children": [],
            }
        else:
            if title and not nodes[code]["title_ru"]:
                nodes[code]["title_ru"] = (title or "").strip()
            if duty and not nodes[code]["import_duty"]:
                nodes[code]["import_duty"] = duty
        return nodes[code]

    for r in rows:
        c = _norm_hs_digits(r.code or "")
        if len(c) not in (4, 6, 10):
            continue
        _ensure(c, r.title_ru or "", _duty(c))

    # Синтетические родители для дочерних кодов
    for c in list(nodes.keys()):
        if len(c) == 6:
            _ensure(c[:4], "", _duty(c[:4]))
        elif len(c) == 10:
            _ensure(c[:4], "", _duty(c[:4]))
            _ensure(c[:6], "", _duty(c[:6]))

    for n in nodes.values():
        n["children"] = []

    seen_edge: set[tuple[str, str]] = set()

    def _link(parent_code: str, child_code: str) -> None:
        if parent_code not in nodes or child_code not in nodes:
            return
        key = (parent_code, child_code)
        if key in seen_edge:
            return
        seen_edge.add(key)
        parent = nodes[parent_code]
        child = nodes[child_code]
        parent["children"].append(child)

    for c in sorted(nodes.keys(), key=lambda x: (len(x), x)):
        if len(c) == 10:
            _link(c[:6], c)
        elif len(c) == 6:
            _link(c[:4], c)

    def _sort_tree(n: dict[str, Any]) -> None:
        n["children"].sort(key=lambda x: x["code"])
        for ch in n["children"]:
            _sort_tree(ch)

    roots = [nodes[c] for c in nodes if len(c) == 4]
    roots.sort(key=lambda x: x["code"])
    for r in roots:
        _sort_tree(r)
    return roots


@router.get("/hierarchy")
def codes_hierarchy_flat(
    prefix: str = Query("", max_length=10, description="Префикс кода (только цифры)"),
    limit: int = Query(20_000, ge=100, le=100_000),
    db: Session = Depends(get_db),
):
    """
    Иерархическое дерево из плоского hs_codes: 4→6→10, у каждого узла import_duty из tariff_rates.
    """
    p = _norm_hs_digits(prefix)
    stmt = select(HSCode).order_by(HSCode.code)
    if p:
        stmt = stmt.where(HSCode.code.like(f"{p}%"))
    stmt = stmt.limit(limit)
    rows = list(db.execute(stmt).scalars().all())
    codes_norm = [_norm_hs_digits(r.code or "") for r in rows if r.code]
    codes_norm = [c for c in codes_norm if c]
    duty_map: dict[str, str] = {}
    if codes_norm:
        tr = db.query(TariffRate).filter(TariffRate.hs_code.in_(codes_norm)).all()
        duty_map = {(r.hs_code or ""): (r.duty or "") for r in tr}
    tree = build_hierarchy_from_flat_hs_rows(rows, duty_map)
    return {
        "status": "OK",
        "prefix": p,
        "count_rows": len(rows),
        "tree": tree,
    }

def sanitize_title(raw: Optional[str]) -> Optional[str]:
    """Очищает наименования, убирая все табличные артефакты PDF-парсинга."""
    import re
    if not raw:
        return raw
    s = str(raw).strip()

    # ── Фильтры-мусор: если есть — вернуть None ──────────────────────────
    _GARBAGE = [
        r"мас\.%", r"евро\s+за", r"долларов?\s+за", r"руб\.\s+за",
        r"В\s+товарн", r"В\s+данну", r"В\s+суб?позиц",
        r"используемая\s+для", r"работающи[ех]\s+с",
        r"класса,\s+работающ",
        r"^\d+[,\.]\d+\s*[а-яА-Яa-zA-Z]",   # "0,11 евро"
        r"^\s*\d+\)\s*",                       # "1) текст"
        r"^[А-ЯA-Z]\)\s+",                    # "А) текст" — буква пункта
        r"нетто[-\s]масс",
        r"^\s*[-–—]\s*\d+[А-Яа-яA-Za-z]?\)?\s*$",  # одна ссылка на сноску
        r"^\s*,\s*\d{4}",                            # ", 8540, 8541" — ссылки на коды
        r"^\s*\d{4,}\s*,",                           # "8540, ..." — перечень кодов
    ]
    for pat in _GARBAGE:
        if re.search(pat, s, re.IGNORECASE):
            return None

    # ── Убираем PDF-префиксы вида "000 0 – –" ────────────────────────────
    # "000 0 – – семенная – 563С)" → "семенная"
    s = re.sub(r"^\d{3}\s+\d+\s*", "", s)          # "000 0 " в начале
    s = re.sub(r"^(?:\s*[–\-—]\s*)+", "", s)        # Leading dashes
    # Схлопываем "– –" → "–"
    s = re.sub(r"\s*[–\-—]\s*[–\-—]\s*", " – ", s)

    # ── Убираем хвостовые артефакты ───────────────────────────────────────
    s = re.sub(r"\s*[–\-—]\s*\d+[A-Za-zА-Яа-я]?\)?\s*$", "", s)   # "– 563С)"
    s = re.sub(r"\s*\d+[А-Яа-яA-Za-z]?\)\s*$", "", s)               # " 5)"
    s = re.sub(r"\s*(?:[–\-—]\s*)?(?:шт|кг|л|м|см|мм)\b.*$", "", s, flags=re.IGNORECASE)

    # ── Убираем голые нулевые блоки ───────────────────────────────────────
    s = re.sub(r"\b0{3,}\b", "", s)

    # ── Финальная нормализация ─────────────────────────────────────────────
    s = re.sub(r"\s{2,}", " ", s).strip()

    # Повторный проход по ведущим тире/пунктуации (могли остаться после удаления "000")
    s = re.sub(r"^[–\-—,;.\s]+", "", s)

    # Убираем хвостовые тире и пунктуацию
    s = re.sub(r"[–\-—,:;]+\s*$", "", s).strip()

    # Слишком короткий результат — мусор
    if len(s) < 3:
        return None

    return s


_GENERIC_LC = frozenset({"прочие", "прочий", "прочая", "прочее", "другие", "иные"})


def is_garbage_code(code: str, title: Optional[str]) -> bool:
    """Возвращает True если код / заголовок — артефакт PDF-парсинга."""
    import re
    if title is None:
        return False
    t = title.strip()
    if not t:
        return False

    # Явные бессмыслицы
    if re.search(r"^[А-ЯA-Z]\)\s*$|^\d+\s*$|^[-–—]+\s*$", t):
        return True

    # Единицы измерения как первое слово
    if re.match(r"^(?:мм|см|м\b|кг|шт|л\b)\b", t, re.IGNORECASE):
        return True

    # Многословный фрагмент, начинающийся со строчной буквы (продолжение предложения)
    words = t.split()
    if len(words) > 1 and words[0][0].islower() and words[0].lower() not in _GENERIC_LC:
        return True

    return False


def is_generic_title(title: Optional[str]) -> bool:
    if not title:
        return True
    t = title.strip().lower().rstrip(":")
    generics = {
        "прочие", "прочий", "прочая", "прочее",
        "прочие товары", "прочие изделия",
        "другие", "иные", "прочее оборудование",
    }
    return t in generics or len(t) < 3

def compose_title(parent_title: Optional[str], child_title: Optional[str]) -> Optional[str]:
    pt = sanitize_title(parent_title) or ""
    ct = sanitize_title(child_title) or ""
    if not pt and not ct:
        return child_title or parent_title
    if not pt:
        return ct
    if not ct:
        return pt
    # Уберем двоеточие у родителя
    pt = pt.rstrip(": ")
    # Соединяем
    return f"{pt} — {ct}"

# Официальные названия глав ТН ВЭД (краткие, читабельные)
CHAPTER_TITLES = {
    "01": "Живые животные",
    "02": "Мясо и пищевые мясные субпродукты",
    "03": "Рыба и ракообразные, моллюски и прочие водные беспозвоночные",
    "04": "Молочная продукция; яйца птиц; натуральный мёд",
    "05": "Продукты животного происхождения, в другом месте не поименованные",
    "06": "Живые растения и цветы; декоративная зелень",
    "07": "Овощи, съедобные корнеплоды и клубни",
    "08": "Фрукты и орехи; кожура цитрусовых или корок дыни",
    "09": "Кофе, чай, мате и специи",
    "10": "Зерновые культуры",
    "11": "Мука, крупа, солод, крахмал, инулин",
    "12": "Масличные семена и плоды; соломка и корма",
    "13": "Смолы, камеди, растительные соки и экстракты",
    "14": "Материалы растительного происхождения для плетения",
    "15": "Жиры и масла животного или растительного происхождения",
    "16": "Готовые продукты из мяса, рыбы или ракообразных",
    "17": "Сахар и кондитерские изделия из сахара",
    "18": "Какао и продукты из него",
    "19": "Готовые продукты из зерна, муки, крахмала",
    "20": "Продукция переработки овощей, фруктов, орехов",
    "21": "Разные пищевые продукты",
    "22": "Напитки, спиртные и уксус",
    "23": "Остатки пищевой промышленности; корма для животных",
    "24": "Табак и промышленные заменители табака",
    "25": "Соль; сера; земли и камень; гипс, известь и цемент",
    "26": "Руды, шлак и зола",
    "27": "Минеральное топливо, нефть и продукты их перегонки",
    "28": "Продукция химической промышленности прочая",
    "29": "Органические химические соединения",
    "30": "Фармацевтическая продукция",
    "31": "Удобрения",
    "32": "Красящие вещества; краски; лаки; мастики",
    "33": "Эфирные масла; парфюмерные и косметические средства",
    "34": "Мыло, ПАВ, смазки, воски, полироли",
    "35": "Белковые вещества; клеи; ферменты",
    "36": "Взрывчатые вещества; пиротехника; спички",
    "37": "Фотографические и кинотовары",
    "38": "Прочие химические продукты",
    "39": "Пластмассы и изделия из них",
    "40": "Каучук, резина и изделия из них",
    "41": "Необработанные шкуры и кожа",
    "42": "Изделия из кожи; дорожные принадлежности; сумки",
    "43": "Меха и изделия из меха",
    "44": "Древесина и изделия из неё; древесный уголь",
    "45": "Пробка и изделия из пробки",
    "46": "Изделия из соломы, эспарто и материалов для плетения",
    "47": "Масса из древесины; полуцеллюлоза; целлюлоза",
    "48": "Бумага и картон; изделия из бумажной массы",
    "49": "Печатные книги, газеты и иная полиграфия",
    "50": "Шёлк натуральный",
    "51": "Шерсть, тонкий и грубый волос животных",
    "52": "Хлопок",
    "53": "Прочие растительные текстильные волокна",
    "54": "Химические нити",
    "55": "Химические волокна",
    "56": "Вата; войлок и фетр; нетканые материалы",
    "57": "Ковры и прочие текстильные напольные покрытия",
    "58": "Специальные ткани; тюль; кружево",
    "59": "Ткани с пропиткой или покрытием",
    "60": "Трикотажное полотно",
    "61": "Одежда и принадлежности из трикотажа",
    "62": "Одежда и принадлежности, кроме трикотажных",
    "63": "Прочие готовые текстильные изделия",
    "64": "Обувь, гетры и аналогичные изделия",
    "65": "Головные уборы и их части",
    "66": "Зонты, трости, палки; их части",
    "67": "Перья и пух; искусственные цветы",
    "68": "Изделия из камня, гипса, цемента",
    "69": "Керамические изделия",
    "70": "Стекло и изделия из стекла",
    "71": "Жемчуг; драгоценные камни и металлы",
    "72": "Черные металлы",
    "73": "Изделия из черных металлов",
    "74": "Медь и изделия из меди",
    "75": "Никель и изделия из никеля",
    "76": "Алюминий и изделия из алюминия",
    "78": "Свинец и изделия из свинца",
    "79": "Цинк и изделия из цинка",
    "80": "Олово и изделия из олова",
    "81": "Прочие недрагоценные металлы",
    "82": "Инструменты и столовые приборы из металлов",
    "83": "Разные изделия из недрагоценных металлов",
    "84": "Реакторы, котлы и механические машины",
    "85": "Электрические машины и оборудование",
    "86": "Железнодорожный подвижной состав; путь",
    "87": "Автомобили и прочие транспортные средства",
    "88": "Летательные и космические аппараты",
    "89": "Корабли и прочие плавучие средства",
    "90": "Оптические, измерительные, медицинские приборы",
    "91": "Часы и их части",
    "92": "Музыкальные инструменты",
    "93": "Оружие и боеприпасы",
    "94": "Мебель; постельные принадлежности",
    "95": "Игрушки, игры, спортивный инвентарь",
    "96": "Разные готовые изделия",
    "97": "Произведения искусства и антиквариат"
}

@router.get("/search")
async def search_codes(q: str, db: Session = Depends(get_db)):
    q = (q or "").strip()
    q_code = q.replace(".", "")
    # prefix по коду + поиск по наименованию (RU/EN), лимит 50
    code_plain = func.replace(HSCode.code, ".", "")
    q_lower = (q or "").lower()
    def _ru_word_match(w: str):
        parts = [
            HSCode.title_ru.like(f"%{w}%"),
            HSCode.title_ru.like(f"%{w[0].upper() + w[1:]}%"),
        ]
        if len(w) >= 4:
            stem = w[:-1]
            if len(stem) >= 3:
                parts.append(HSCode.title_ru.like(f"%{stem}%"))
        return or_(*parts)

    words = [w for w in q_lower.split() if w]
    # Несколько слов («телефон мобильный»): все должны встречаться в title_ru
    if len(words) >= 2:
        ru_match = and_(*[_ru_word_match(w) for w in words])
    else:
        # SQLite lower() не трогает кириллицу — дублируем шаблон с заглавной первой буквой;
        # для «резина»/«резины» — дополнительно корень без последней буквы
        ru_first = (q_lower[0].upper() + q_lower[1:]) if q_lower else ""
        ru_parts = [HSCode.title_ru.like(f"%{q_lower}%")]
        if ru_first and ru_first != q_lower:
            ru_parts.append(HSCode.title_ru.like(f"%{ru_first}%"))
        if len(q_lower) >= 4:
            stem = q_lower[:-1]
            if len(stem) >= 3:
                ru_parts.append(HSCode.title_ru.like(f"%{stem}%"))
        ru_match = or_(*ru_parts)
    en_match = func.instr(func.lower(HSCode.title_en), q_lower) > 0
    rows = (
        db.query(HSCode)
        .filter(
            or_(
                HSCode.code.like(f"{q_code}%"),
                code_plain.like(f"{q_code}%"),
                ru_match,
                en_match,
            )
        )
        .limit(50)
        .all()
    )
    return [
        {
            "code": (r.code or "").replace(".", ""),
            "title_ru": sanitize_title(r.title_ru) or r.title_ru,
            "title_full": getattr(r, "title_full", None),
            "chapter": getattr(r, "chapter", None),
            "heading": getattr(r, "heading", None),
            "subheading": getattr(r, "subheading", None),
        }
        for r in rows
    ]

@router.get("/suggest")
def suggest_codes(q: str = Query(..., min_length=1, max_length=10)):
    qn = (q or "").replace(".", "").strip()
    if not qn.isdigit():
        db = SessionLocal()
        try:
            rows = (db.execute(
                select(HSCode).where(HSCode.title_ru.ilike(f"%{q}%")).limit(50)
            ).scalars().all())
            return {"input": q, "exact": None, "suggest": [
                {"code": r.code, "title_ru": r.title_ru, "level": r.level, "parent": r.parent}
                for r in rows
            ]}
        finally:
            db.close()

    n = len(qn)
    nlen = _next_len(n)

    db = SessionLocal()
    try:
        exact = db.execute(select(HSCode).where(HSCode.code == qn)).scalar_one_or_none()
        exact_json = ({"code": exact.code, "title_ru": exact.title_ru, "level": exact.level, "parent": exact.parent} if exact else None)
        code_expr = func.substr(HSCode.code, 1, nlen).label("code")
        rows = (db.execute(
            select(
                code_expr,
                func.min(HSCode.title_ru).label("title_ru")
            )
            .where(HSCode.code.like(f"{qn}%"))
            .group_by(code_expr)
            .order_by(code_expr)
            .limit(100)
        ).all())
        def _lvl(c: str):
            L = len(c)
            if L==2: return "chapter"
            if L==4: return "heading"
            if L==6: return "subheading"
            return "item"
        suggest = [{"code": r.code, "title_ru": r.title_ru, "level": _lvl(r.code)} for r in rows]
        return {"input": qn, "exact": exact_json, "suggest": suggest}
    finally:
        db.close()

@router.get("/list")
def list_codes(prefix: Optional[str] = None, limit: int = 2000):
    p = (prefix or "").replace(".", "").strip()
    db = SessionLocal()
    try:
        stmt = select(HSCode).order_by(HSCode.code)
        if p:
            stmt = stmt.where(HSCode.code.like(f"{p}%"))
        if limit:
            stmt = stmt.limit(limit)
        rows = db.execute(stmt).scalars().all()

        buckets = {"2": [], "4": [], "6": [], "8": [], "10": []}
        for r in rows:
            L = str(len(r.code))
            if L in buckets:
                buckets[L].append({
                    "code": r.code,
                    "title_ru": r.title_ru,
                    "level": r.level,
                    "parent": r.parent
                })

        return {
            "prefix": p,
            "counts": {k: len(v) for k, v in buckets.items()},
            "items": buckets
        }
    finally:
        db.close()

@router.get("/tree")
def codes_tree(
    root: str = Query("", description="Корневой префикс кода (без точек)"),
    include_notes: bool = Query(False),
    include_tariff: bool = Query(False),
    db: Session = Depends(get_db),
):
    root = (root or "").replace(".", "")
    q = db.query(HSCode)
    if root:
        q = q.filter(HSCode.code.like(f"{root}%"))
    rows = q.all()

    # Предзагрузка примечаний по главам
    chapter_notes_map = {}
    section_map = {"01": "I", "02": "II", "03": "III", "04": "IV", "05": "V", "06": "VI",
                   "07": "VII", "08": "VIII", "09": "IX", "10": "X", "11": "XI", "12": "XII",
                   "13": "XIII", "14": "XIV", "15": "XV", "16": "XVI", "17": "XVII", "18": "XVIII",
                   "19": "XIX", "20": "XX", "21": "XXI"}
    if include_notes:
        all_notes = db.query(Note).all()
        for n in all_notes:
            if n.level == "chapter":
                chapter_notes_map.setdefault(n.ref_id, []).append({
                    "level": n.level, "ref": n.ref_id, "text": n.text
                })

    # Построение узлов
    code_to_node = {}
    roots = []
    for r in rows:
        code = (r.code or "").replace(".", "")
        node = code_to_node.get(code)
        if not node:
            node = {
                "code": code,
                "title": r.title_ru,
                "level": r.level,
                "children": []
            }
            code_to_node[code] = node
        # Примечания
        if include_notes and r.chapter:
            notes = []
            notes.extend(chapter_notes_map.get(r.chapter, []))
            sect = section_map.get(r.chapter)
            if sect:
                # Примечания по разделу (если нужны, можно добавить выборку здесь)
                pass
            if notes:
                node["notes"] = notes
        # Тарифы (только для 10-значных при запросе)
        if include_tariff and len(code) == 10:
            duty = tariff_service.lookup(code)
            vat_rate, vat_source = tariff_service.resolve_vat_for_code(code)
            node["tariff"] = {**duty, "vat": vat_rate, "vat_source": vat_source}

    # Линковка детей к родителям
    for r in rows:
        code = (r.code or "").replace(".", "")
        parent = (r.parent or "").replace(".", "") if getattr(r, "parent", None) else None
        node = code_to_node[code]
        if parent and parent in code_to_node and (not root or code != root):
            code_to_node[parent]["children"].append(node)
        else:
            roots.append(node)

    # Сортировка детей по коду
    def sort_children(n):
        n["children"].sort(key=lambda x: x["code"])
        for c in n["children"]:
            sort_children(c)
    for n in roots:
        sort_children(n)

    # Если задан root и он существует — вернуть один корневой узел
    if root and root in code_to_node:
        return code_to_node[root]
    return roots

# --- Codes list API ---
 
# --- Suggestions API ---
def _next_len(n: int) -> int:
    if n <= 2: return 4
    if n <= 4: return 6
    if n <= 6: return 8
    return 10


def _has_real_children(db: Session, parent_code: str) -> bool:
    """Есть ли в БД коды длиннее parent_code с тем же префиксом."""
    parent = (parent_code or "").replace(".", "").strip()
    plen = len(parent)
    if plen >= 10 or plen == 0:
        return False
    cnt = db.execute(
        select(func.count(HSCode.code))
        .where(HSCode.code.like(f"{parent}%"))
        .where(func.length(HSCode.code) > plen)
    ).scalar_one()
    return int(cnt or 0) > 0


@router.get("/suggest")
def suggest_codes(q: str = Query(..., min_length=1, max_length=10)):
    qn = (q or "").replace(".", "").strip()
    if not qn.isdigit():
        # если пользователь набрал текст — отдадим обычный search
        db = SessionLocal()
        try:
            rows = (db.execute(
                select(HSCode).where(HSCode.title_ru.ilike(f"%{q}%")).limit(50)
            ).scalars().all())
            return {"input": q, "exact": None, "suggest": [
                {"code": r.code, "title_ru": r.title_ru, "level": r.level, "parent": r.parent}
                for r in rows
            ]}
        finally:
            db.close()

    n = len(qn)
    nlen = _next_len(n)

    db = SessionLocal()
    try:
        # exact (если есть)
        exact = db.execute(select(HSCode).where(HSCode.code == qn)).scalar_one_or_none()
        exact_json = ({"code": exact.code, "title_ru": exact.title_ru, "level": exact.level, "parent": exact.parent} if exact else None)

        # сгруппированные варианты на следующий уровень (4→6→8→10)
        code_expr = func.substr(HSCode.code, 1, nlen).label("code")
        rows = (db.execute(
            select(
                code_expr,
                func.min(HSCode.title_ru).label("title_ru")
            )
            .where(HSCode.code.like(f"{qn}%"))
            .group_by(code_expr)
            .order_by(code_expr)
            .limit(100)
        ).all())

        def _lvl(c: str):
            L = len(c)
            if L==2: return "chapter"
            if L==4: return "heading"
            if L==6: return "subheading"
            return "item"

        suggest = [{"code": r.code, "title_ru": r.title_ru, "level": _lvl(r.code)} for r in rows]
        return {"input": qn, "exact": exact_json, "suggest": suggest}
    finally:
        db.close()

@router.get("/sections")
def get_sections():
    """Получить список разделов ТН ВЭД"""
    sections = {
        "I": {"name": "Живые животные; продукты животного происхождения", "chapters": ["01", "02", "03", "04", "05"]},
        "II": {"name": "Продукты растительного происхождения", "chapters": ["06", "07", "08", "09", "10", "11", "12", "13", "14"]},
        "III": {"name": "Жиры и масла животного, растительного или микробного происхождения", "chapters": ["15"]},
        "IV": {"name": "Готовые пищевые продукты; алкогольные и безалкогольные напитки", "chapters": ["16", "17", "18", "19", "20", "21", "22"]},
        "V": {"name": "Минеральные продукты", "chapters": ["25", "26", "27"]},
        "VI": {"name": "Продукция химической и связанных с ней отраслей промышленности", "chapters": ["28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38"]},
        "VII": {"name": "Пластмассы и изделия из них; каучук и резина", "chapters": ["39", "40"]},
        "VIII": {"name": "Необработанные шкуры, кожа, натуральный мех и изделия из них", "chapters": ["41", "42", "43"]},
        "IX": {"name": "Древесина и изделия из древесины; древесный уголь", "chapters": ["44", "45", "46"]},
        "X": {"name": "Масса из древесины или из других волокнистых целлюлозных материалов", "chapters": ["47", "48", "49"]},
        "XI": {"name": "Текстильные материалы и текстильные изделия", "chapters": ["50", "51", "52", "53", "54", "55", "56", "57", "58", "59", "60", "61", "62", "63"]},
        "XII": {"name": "Обувь, головные уборы, зонты, трости, кнуты, кнуты для верховой езды", "chapters": ["64", "65", "66", "67"]},
        "XIII": {"name": "Изделия из камня, гипса, цемента, асбеста, слюды", "chapters": ["68", "69"]},
        "XIV": {"name": "Жемчуг природный или культивированный, драгоценные или полудрагоценные камни", "chapters": ["71"]},
        "XV": {"name": "Недрагоценные металлы и изделия из них", "chapters": ["72", "73", "74", "75", "76", "78", "79", "80", "81", "82", "83"]},
        "XVI": {"name": "Машины, оборудование и механизмы; электротехническое оборудование", "chapters": ["84", "85"]},
        "XVII": {"name": "Средства наземного транспорта, летательные аппараты, плавучие средства", "chapters": ["86", "87", "88", "89"]},
        "XVIII": {"name": "Оптические, фотографические, кинематографические, измерительные, контрольные", "chapters": ["90", "91", "92"]},
        "XIX": {"name": "Оружие и боеприпасы; их части и принадлежности", "chapters": ["93"]},
        "XX": {"name": "Разные промышленные товары", "chapters": ["94", "95", "96"]},
        "XXI": {"name": "Произведения искусства, предметы коллекционирования и антиквариат", "chapters": ["97"]}
    }
    return sections

@router.get("/chapters")
def get_chapters(db: Session = Depends(get_db)):
    """Список всех глав (2-значные коды) с наименованиями."""
    rows = (
        db.execute(
            select(HSCode).where(func.length(HSCode.code) == 2).order_by(HSCode.code)
        ).scalars().all()
    )
    result = []
    for r in rows:
        t = sanitize_title(r.title_ru)
        # Подставляем официальное краткое название, если очищенное не подходит
        if not t or is_generic_title(t) or len(t) < 6:
            t = CHAPTER_TITLES.get(r.code, t)
        if not t:
            continue
        result.append({"code": r.code, "title_ru": t, "level": r.level})
    return result

@router.get("/children/{hs_code}")
def get_children(
    hs_code: str,
    limit: int = Query(500, ge=1, le=5000),
    group_next: bool = Query(False, description="Группировать по следующей длине (4→6→8→10)"),
    include_tariff: bool = Query(False, description="Добавлять тариф/НДС для 10-значных узлов"),
    db: Session = Depends(get_db),
):
    """Получить дочерние элементы для кода.

    По умолчанию возвращает записи с parent == hs_code.
    При group_next=true вернет сгруппированные узлы следующей длины (substr + min(title)).
    """
    code = (hs_code or "").replace(".", "").strip()
    if not code:
        raise HTTPException(400, "hs_code is required")

    def best_title_for(c: str) -> Optional[str]:
        """Возвращает лучшее доступное наименование: своё или ближайшего предка."""
        for L in (len(c), 8, 6, 4, 2):
            if L <= 0 or L > len(c):
                continue
            node = db.execute(select(HSCode).where(HSCode.code == c[:L])).scalar_one_or_none()
            if node and getattr(node, "title_ru", None):
                return node.title_ru
        return None

    if group_next:
        next_len = _next_len(len(code))

        def _lvl(c: str) -> str:
            L = len(c)
            if L == 2: return "chapter"
            if L == 4: return "heading"
            if L == 6: return "subheading"
            return "item"

        # Шаг 1: получаем список уникальных кодов следующего уровня
        code_expr = func.substr(HSCode.code, 1, next_len).label("next_code")
        raw_codes = db.execute(
            select(code_expr)
            .where(HSCode.code.like(f"{code}%"))
            .where(func.length(HSCode.code) >= next_len)
            .group_by(code_expr)
            .order_by(code_expr)
            .limit(limit)
        ).all()
        next_codes = [r.next_code for r in raw_codes if r.next_code and r.next_code != code]

        # Шаг 2: прямой поиск заголовков для кодов этого уровня (включая title_full из ETL)
        direct_map: dict[str, str] = {}
        full_map: dict[str, Optional[str]] = {}
        if next_codes:
            direct_rows = db.execute(
                select(HSCode.code, HSCode.title_ru, HSCode.title_full)
                .where(HSCode.code.in_(next_codes))
            ).all()
            for r in direct_rows:
                direct_map[r.code] = r.title_ru
                full_map[r.code] = r.title_full

        # Шаг 3: формируем результат
        # Для глав (2→4) берём CHAPTER_TITLES как авторитетный источник
        parent_is_chapter = len(code) == 2
        parent_display_title: Optional[str] = None
        if parent_is_chapter:
            parent_display_title = CHAPTER_TITLES.get(code)
        else:
            parent_row = db.execute(select(HSCode).where(HSCode.code == code)).scalar_one_or_none()
            if parent_row:
                parent_display_title = sanitize_title(parent_row.title_ru)

        items = []
        for child_code in next_codes:
            direct_raw = direct_map.get(child_code)

            if direct_raw:
                direct_title = sanitize_title(direct_raw)
                if not direct_title:
                    # Прямой заголовок существует, но является мусором — пропускаем код
                    continue
                title: Optional[str] = direct_title
            else:
                # Прямой записи нет — берём из ближайшего предка
                title = sanitize_title(best_title_for(child_code))

            # Пропускаем явный мусор (multi-word lowercase = sentence fragment)
            if is_garbage_code(child_code, title):
                continue

            # Если generic ("прочая") — составляем composite с родительским контекстом
            if is_generic_title(title) and parent_display_title:
                title = compose_title(parent_display_title, title) or title

            # is_codeless — по сырому заголовку из БД (sanitize убирает «:»)
            codeless = is_codeless_title(direct_raw or "") or is_codeless_title(title or "")

            node = {
                "code": child_code,
                "title_ru": title,
                "title_full": full_map.get(child_code),
                "level": _lvl(child_code),
                "parent": code,
                "has_children": len(child_code) < 10 and _has_real_children(db, child_code),
                "is_codeless": codeless,
            }
            if include_tariff and len(child_code) == 10 and not node["is_codeless"]:
                t = tariff_service.lookup(child_code)
                vat_rate, vat_source, vat_title = tariff_service.resolve_vat_for_code(child_code)
                node["tariff"] = {**t, "vat": vat_rate, "vat_source": vat_source, "vat_reason": vat_title}
                node["measures"] = permit_measures_for_code(child_code)
            items.append(node)
        return items

    children = (
        db.execute(
            select(HSCode)
            .where(HSCode.parent == code)
            .order_by(HSCode.code)
            .limit(limit)
        ).scalars().all()
    )
    result = []
    for child in children:
        title = sanitize_title(child.title_ru or best_title_for(child.code))
        child_digits = (child.code or "").replace(".", "")
        raw_title = child.title_ru or title
        codeless = is_codeless_title(raw_title or "") or is_codeless_title(title or "")
        node = {
            "code": child.code,
            "title_ru": title,
            "title_full": getattr(child, "title_full", None),
            "level": child.level,
            "parent": child.parent,
            "chapter": child.chapter,
            "has_children": len(child_digits) < 10 and _has_real_children(db, child_digits),
            "is_codeless": codeless,
        }
        if include_tariff and len(child.code) == 10 and not node["is_codeless"]:
            t = tariff_service.lookup(child.code)
            vat_rate, vat_source, vat_title = tariff_service.resolve_vat_for_code(child.code)
            node["tariff"] = {**t, "vat": vat_rate, "vat_source": vat_source, "vat_reason": vat_title}
            node["measures"] = permit_measures_for_code(child.code)
        result.append(node)
    return result

@router.get("/hierarchy/{hs_code}")
def get_hierarchy(
    hs_code: str,
    max_depth: int = Query(3, ge=1, le=5),
    include_tariff: bool = Query(False, description="Добавлять тариф/НДС для 10-значных")
):
    """Получить иерархическую структуру кода с отступами как в примере:
    1501 Жир свиной (включая лярд) и жир домашней птицы...
    150110
    - лярд:
    1501101000
    -- для промышленного применения...
    """
    code = (hs_code or "").replace(".", "").strip()
    if not code:
        raise HTTPException(400, "hs_code is required")
    
    db = SessionLocal()
    try:
        def infer_root_title(prefix: str) -> str:
            """Возвращает осмысленное имя для корня даже если точного узла нет."""
            L = len(prefix)
            # выбираем минимальное (алф) название на следующей длине
            next_len = 0
            if L == 2: next_len = 4
            elif L == 4: next_len = 6
            elif L == 6: next_len = 8
            elif L == 8: next_len = 10
            if next_len:
                row = db.execute(
                    select(func.min(HSCode.title_ru)).where(
                        HSCode.code.like(f"{prefix}%"), func.length(HSCode.code) == next_len
                    )
                ).scalar_one_or_none()
                if row:
                    return row
            # если ничего не нашли, подставим техническое имя
            labels = {2: "Глава", 4: "Товарная позиция", 6: "Субпозиция", 8: "Подсубпозиция", 10: "Товар"}
            return f"{labels.get(L, 'Код')} {prefix}"

        def get_children_recursive(parent_code: str, depth: int = 0):
            if depth >= max_depth:
                return []
            
            # Определяем следующую длину кода
            next_len = 0
            if len(parent_code) == 2: next_len = 4
            elif len(parent_code) == 4: next_len = 6
            elif len(parent_code) == 6: next_len = 8
            elif len(parent_code) == 8: next_len = 10
            
            if next_len == 0:
                return []
            
            # Если ищем 8-значные коды, но их нет, попробуем найти 10-значные
            if next_len == 8:
                # Сначала проверим, есть ли 8-значные
                count_8 = db.execute(
                    select(func.count(HSCode.code))
                    .where(HSCode.code.like(f"{parent_code}%"))
                    .where(func.length(HSCode.code) == 8)
                ).scalar()
                
                if count_8 == 0:
                    # Если 8-значных нет, ищем 10-значные
                    next_len = 10
            
            # Получаем детей по префиксу и длине
            children = db.execute(
                select(HSCode)
                .where(HSCode.code.like(f"{parent_code}%"))
                .where(func.length(HSCode.code) == next_len)
                .order_by(HSCode.code)
            ).scalars().all()
            
            result = []
            for child in children:
                # Определяем отступы
                indent = "  " * depth
                if depth == 0:
                    prefix = ""
                elif depth == 1:
                    prefix = "- "
                else:
                    prefix = "-- "
                
                # Получаем лучшее название (свое или от предка)
                def best_title_for(c: str) -> str:
                    for L in (len(c), 8, 6, 4, 2):
                        if L <= 0 or L > len(c):
                            continue
                        node = db.execute(select(HSCode).where(HSCode.code == c[:L])).scalar_one_or_none()
                        if node and getattr(node, "title_ru", None):
                            return node.title_ru
                    return "Без названия"
                
                title = sanitize_title(child.title_ru or best_title_for(child.code))
                line = f"{indent}{prefix}{child.code} {title}"
                
                node = {
                    "code": child.code,
                    "title_ru": title,
                    "level": child.level,
                    "line": line,
                    "depth": depth,
                }
                # Вставляем тариф/НДС только для 10-значных по запросу
                if include_tariff and len(child.code) == 10:
                    t = tariff_service.lookup(child.code)
                    vat_rate, vat_source, vat_title = tariff_service.resolve_vat_for_code(child.code)
                    node["tariff"] = {**t, "vat": vat_rate, "vat_source": vat_source, "vat_reason": vat_title}
                node["children"] = get_children_recursive(child.code, depth + 1)
                result.append(node)
            
            return result
        
        # Начинаем с корневого кода (если нет — синтетический корень)
        root = db.execute(select(HSCode).where(HSCode.code == code)).scalar_one_or_none()
        if root:
            root_title = root.title_ru or infer_root_title(code)
        else:
            # если точного узла нет — пробуем построить дерево по префиксу
            # и сгенерируем заголовок из детей
            # если вообще нет потомков — 404
            any_child = db.execute(
                select(HSCode.code).where(HSCode.code.like(f"{code}%")).limit(1)
            ).scalar_one_or_none()
            if not any_child:
                raise HTTPException(404, "code not found")
            root_title = infer_root_title(code)
        root_line = f"{code} {root_title}"
        
        return {
            "code": code,
            "title_ru": root_title,
            "line": root_line,
            "depth": 0,
            "children": get_children_recursive(code, 0)
        }
    finally:
        db.close()

@router.get("/{hs_code}")
def get_code(hs_code: str):
    code = hs_code.replace(".","").strip()
    if not code.isdigit():
        raise HTTPException(404, "code not found")
    db = SessionLocal()
    try:
        c = db.execute(select(HSCode).where(HSCode.code == code)).scalar_one_or_none()
        if not c: raise HTTPException(404, "code not found")
        kids = db.execute(select(HSCode).where(HSCode.parent == code)).scalars().all()
        path = []
        def _add(node_code: str):
            n = db.execute(select(HSCode).where(HSCode.code == node_code)).scalar_one_or_none()
            if n:
                path.append({
                    "code": n.code,
                    "title_ru": n.title_ru,
                    "title_full": getattr(n, "title_full", None),
                    "level": n.level,
                })
        L = len(code)
        if L >= 2: _add(code[:2])
        if L >= 4: _add(code[:4])
        if L >= 6: _add(code[:6])
        if L >= 8: _add(code[:8])
        if L >= 10: _add(code[:10])

        tariff = None
        if len(code) == 10:
            t = tariff_service.lookup(code)
            vat_rate, vat_source, vat_title = tariff_service.resolve_vat_for_code(code)
            tariff = {**t, "vat": vat_rate, "vat_source": vat_source, "vat_reason": vat_title}

        clean_code_title = sanitize_title(c.title_ru)
        if not clean_code_title and len(c.code) <= 4:
            clean_code_title = CHAPTER_TITLES.get(c.code[:2]) if len(c.code) == 2 else None

        clean_path = []
        for p in path:
            pt = sanitize_title(p["title_ru"]) if p.get("title_ru") else None
            if len(p["code"]) == 2:
                pt = CHAPTER_TITLES.get(p["code"]) or pt
            clean_path.append({**p, "title_ru": pt})

        return {
            "code": c.code,
            "title_ru": clean_code_title,
            "title_full": getattr(c, "title_full", None),
            "level": c.level,
            "parent": c.parent,
            "path": clean_path,
            "tariff": tariff,
            "measures": permit_measures_for_code(c.code) if len(code) == 10 else [],
            "children": [
                {
                    "code": k.code,
                    "title_ru": sanitize_title(k.title_ru),
                    "title_full": getattr(k, "title_full", None),
                    "level": k.level,
                    "has_children": len((k.code or "").replace(".", "")) < 10,
                }
                for k in kids
            ],
        }
    finally:
        db.close()



