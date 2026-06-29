"""Чистые helpers дерева ТН ВЭД (без FastAPI и SQL)."""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Коды
# ---------------------------------------------------------------------------


def digits(raw: str) -> str:
    """Только цифры из строки."""
    return re.sub(r"\D", "", raw or "")


def pad_code(raw: str) -> str:
    """
    Приводим код к каноническому виду:
    - 4-значный: 4 цифры с ведущими нулями
    - 10-значный: 10 цифр с ведущими нулями
    """
    d = digits(raw)
    if not d:
        return raw.strip()
    if len(d) <= 4:
        return d.zfill(4)
    return d.zfill(10)[:10]


# ---------------------------------------------------------------------------
# Ставки пошлин
# ---------------------------------------------------------------------------

_DUTY_FOOTNOTE_RE = re.compile(r"\d+[СC]\)")


def strip_duty_footnotes(s: str) -> str:
    """Убирает ссылки на сноски в колонке ставки (цифры + С + закрывающая скобка)."""
    if not s:
        return ""
    t = _DUTY_FOOTNOTE_RE.sub("", s)
    return re.sub(r"\s+", " ", t).strip()


def format_duty(raw: str) -> str:
    """Нормализация ставки пошлины: '5' → '5%', '5 %' → '5%', '5 eur/kg' → без изменений."""
    t = strip_duty_footnotes((raw or "").strip())
    if not t or t in ("-", "—"):
        return ""
    low = t.lower()
    if "пошлина:" in low and "ндс:" in low:
        if not re.search(r"\d", t):
            return ""
        duty_part = re.split(r"\|", t, maxsplit=1)[0]
        duty_part = re.sub(r"^.*?пошлина:\s*", "", duty_part, flags=re.I).strip()
        if not duty_part or not re.search(r"\d", duty_part):
            return ""
        t = duty_part
        low = t.lower()
    if low in {"пошлина:", "ндс:", "пошлина", "ндс"}:
        return ""
    if "%" in t or "eur" in t.lower() or "€" in t.lower() or any(c.isalpha() for c in t):
        return re.sub(r"\s+", " ", t).replace(" %", "%")
    clean = t.replace(",", ".").replace(" ", "")
    try:
        num = float(clean)
        if num == int(num):
            return f"{int(num)}%"
        return f"{num}%".replace(".", ",")
    except ValueError:
        return t


# ---------------------------------------------------------------------------
# Имена / описания
# ---------------------------------------------------------------------------

_LEADING_DASHES_RE = re.compile(r"^[\s\u2013\u2014\-]+")
_TRAILING_NOISE_RE = re.compile(r"[\s\u2013\u2014\-,]+$")
_PAD_SUBHEADING_RE = re.compile(r"^(.+?)\s[\u2013\u2014\-]\s(.+)$")

_GENERIC_PREFIXES: tuple[str, ...] = (
    "прочие",
    "другие",
    "иные",
    "для ",
    "животные для",
    "растения для",
    "из ",
    "в том числе",
    "обработанные",
    "необработанные",
    "шт ",
)


def strip_leading_dashes(s: str) -> str:
    """Убирает ведущие «–»/«—»/«-» и завершающие запятые/тире из строки."""
    t = _LEADING_DASHES_RE.sub("", s.strip())
    return _TRAILING_NOISE_RE.sub("", t).strip()


def split_position_pad_name(raw: str) -> tuple[str, str]:
    """Разбивает описание XXXX000000 на заголовок позиции и подзаголовок субпозиции."""
    s = (raw or "").strip()
    m = _PAD_SUBHEADING_RE.match(s)
    if m:
        title = m.group(1).strip()
        sub = strip_leading_dashes(m.group(2).strip())
        return title, sub
    return strip_leading_dashes(s), ""


def count_leading_dashes(s: str) -> int:
    """Считает количество ведущих тире «–» (с пробелами между ними)."""
    m = re.match(r"^([\s\u2013\u2014\-]+)", s)
    if not m:
        return 0
    return len(re.findall(r"[\u2013\u2014\-]", m.group(1)))


def is_meaningful_name(s: str) -> bool:
    """True, если строка — осмысленное наименование, а не generic-подкатегория."""
    if not s or len(s) < 4:
        return False
    low = s.lower().strip()
    for prefix in _GENERIC_PREFIXES:
        if low.startswith(prefix):
            return False
    if s.rstrip().endswith("-"):
        return False
    return True


def best_name_for_group(leaves: list[dict]) -> str:
    """Выбирает наилучшее наименование для синтетического узла из листьев."""
    if not leaves:
        return ""
    by_dashes = sorted(leaves, key=lambda n: count_leading_dashes(n.get("name", "") or ""))
    cleaned: list[str] = []
    for node in by_dashes:
        raw = (node.get("name") or "").strip()
        stripped = strip_leading_dashes(raw)
        if not stripped:
            continue
        candidate = stripped[:1].upper() + stripped[1:] if stripped else ""
        if candidate:
            cleaned.append(candidate)

    if not cleaned:
        return ""

    meaningful = [name for name in cleaned if is_meaningful_name(name)]
    if meaningful:
        return meaningful[0]
    return cleaned[0]


# ---------------------------------------------------------------------------
# Obsolete / reserved
# ---------------------------------------------------------------------------

OBSOLETE_RESERVED_DESC_PREFIX = "Товарная позиция"


def is_obsolete_reserved_description(description: str | None) -> bool:
    """Упразднённые резервные позиции без реального содержания."""
    return (description or "").strip().startswith(OBSOLETE_RESERVED_DESC_PREFIX)


# ---------------------------------------------------------------------------
# Уровни иерархии
# ---------------------------------------------------------------------------


def node_level(code10: str) -> int:
    """Структурный уровень 10-значного кода ТН ВЭД: 4 / 6 / 8 / 9 / 10."""
    if code10[9] != "0":
        return 10
    if code10[8] != "0":
        return 9
    if code10[6:8] != "00":
        return 8
    if code10[4:6] != "00":
        return 6
    return 4


def is_direct_position_subheading(code10: str) -> bool:
    """Субпозиция XXXX30 / XXXX90 — прямой потомок 4-значной позиции."""
    if node_level(code10) != 6:
        return False
    return code10[4] != "0" and code10[5] == "0"


def needs_pad_subheading_group(pad_sub: str, level6_codes: list[str]) -> bool:
    """Codeless-узел pad-sub нужен только если есть «прямые» XXXX30/90 и другие level-6."""
    if not pad_sub or not level6_codes:
        return False
    direct = sum(1 for c in level6_codes if is_direct_position_subheading(c))
    return 0 < direct < len(level6_codes)


# ---------------------------------------------------------------------------
# Legacy dict-узлы дерева
# ---------------------------------------------------------------------------


def make_tree_node(
    code: str,
    name: str,
    import_duty: str,
    notes: str,
    *,
    is_leaf: bool,
    is_codeless: bool,
    is_group: bool,
) -> dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "import_duty": import_duty,
        "notes": notes,
        "is_leaf": is_leaf,
        "is_codeless": is_codeless,
        "is_group": is_group,
        "display_code": digits(code),
        "children": [],
    }


def collect_leaf_names(node: dict[str, Any], acc: list[dict[str, Any]]) -> None:
    for ch in node["children"]:
        if not ch["children"]:
            acc.append(ch)
        else:
            collect_leaf_names(ch, acc)
