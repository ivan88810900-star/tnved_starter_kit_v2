#!/usr/bin/env python3
"""
Диагностика окружения CustomsClear: SQLite (customs.db), переменные окружения, список CLI-скриптов.

  cd customs-clear/backend
  python3 scripts/diagnostics.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")
load_dotenv()

from sqlalchemy import inspect, text  # noqa: E402

from app.db import DATABASE_URL, engine  # noqa: E402

_EXPECTED_CHAPTERS: tuple[str, ...] = tuple(f"{i:02d}" for i in range(1, 98))


def _hr(title: str, width: int = 72) -> str:
    pad = max(2, width - len(title) - 4)
    return f"\n{'═' * width}\n  {title}\n{'─' * width}"


def _env_status(name: str) -> tuple[str, str]:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return name, "Не установлен"
    return name, "Установлен"


def _sqlite_db_path(url: str) -> Path | None:
    if not url.startswith("sqlite:///"):
        return None
    raw = url.replace("sqlite:///", "", 1)
    p = Path(raw)
    if not p.is_absolute():
        p = (_ROOT / p).resolve()
    return p


def _print_database() -> None:
    print(_hr("База данных"))
    print(f"  URL (без секретов): {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")
    sp = _sqlite_db_path(DATABASE_URL)
    if sp is not None:
        print(f"  Файл SQLite: {sp}")
        print(f"  Файл существует: {'да' if sp.is_file() else 'нет'}")

    insp = inspect(engine)
    names = insp.get_table_names()
    if not names:
        print("  (таблицы не найдены — проверьте миграции: alembic upgrade head)")
        return

    print(f"\n  {'Таблица':<42} {'Строк':>10}")
    print("  " + "-" * 54)
    with engine.connect() as conn:
        for t in sorted(names):
            try:
                n = conn.execute(text(f'SELECT COUNT(*) AS c FROM "{t}"')).scalar()
            except Exception as e:
                n = f"? ({e})"
            ts = str(n) if n is not None else "0"
            print(f"  {t:<42} {ts:>10}")


def _print_non_tariff_chapters() -> None:
    """Сводка non_tariff_measures по первым двум цифрам кода (глава ТН ВЭД)."""
    print(_hr("Нетарифные меры (non_tariff_measures) по главам ТН ВЭД"))
    sql_counts = text(
        """
        SELECT substr(commodity_code, 1, 2) AS chapter, COUNT(*) AS cnt
        FROM non_tariff_measures
        WHERE length(commodity_code) = 10
          AND substr(commodity_code, 1, 2) BETWEEN '01' AND '97'
        GROUP BY substr(commodity_code, 1, 2)
        ORDER BY chapter
        """
    )
    sql_commodity_chapters = text(
        """
        SELECT DISTINCT substr(code, 1, 2) AS chapter
        FROM tnved_commodities
        WHERE length(code) = 10
          AND substr(code, 1, 2) BETWEEN '01' AND '97'
        ORDER BY chapter
        """
    )
    insp = inspect(engine)
    if "non_tariff_measures" not in insp.get_table_names():
        print("  Таблица non_tariff_measures отсутствует (выполните alembic upgrade head).")
        return

    try:
        with engine.connect() as conn:
            rows = list(conn.execute(sql_counts).mappings())
            if "tnved_commodities" in insp.get_table_names():
                commodity_chapters = {
                    str(r["chapter"]) for r in conn.execute(sql_commodity_chapters).mappings() if r["chapter"]
                }
            else:
                commodity_chapters = set()
    except Exception as e:
        print(f"  (не удалось выполнить запрос: {e})")
        return

    by_ch: dict[str, int] = {str(r["chapter"]): int(r["cnt"]) for r in rows if r.get("chapter")}
    if not by_ch and not rows:
        print("  Нет строк с 10-значным commodity_code в диапазоне глав 01–97.")
    else:
        print(f"  {'Глава':<8} {'Записей':>10}")
        print("  " + "-" * 22)
        for ch in sorted(by_ch.keys()):
            n = by_ch[ch]
            print(f"  Глава {ch}: {n} строк")

    missing_measures: list[str] = []
    for ch in _EXPECTED_CHAPTERS:
        if by_ch.get(ch, 0) == 0:
            missing_measures.append(ch)

    missing_catalog: list[str] = [ch for ch in _EXPECTED_CHAPTERS if ch not in commodity_chapters]

    print("\n  Главы без ни одной записи в non_tariff_measures (0 строк по префиксу кода):")
    if missing_measures:
        print(f"    {', '.join(missing_measures)}")
    else:
        print("    (нет — по всем главам 01–97 есть хотя бы одна запись)")

    if missing_catalog:
        print("\n  Главы без кодов в tnved_commodities (каталог не содержит 10-значных кодов с этим префиксом):")
        print(f"    {', '.join(missing_catalog)}")


def _print_environment() -> None:
    print(_hr("Переменные окружения (значения секретов не выводятся)"))
    keys = [
        "DATABASE_URL",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_BASE_URL",
        "GEMINI_MODEL_NAME",
        "ANTHROPIC_API_KEY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "REDIS_URL",
        "REGULATORY_SYNC_SCHEDULER_ENABLED",
        "HISTORICAL_CRAWLER_USE_PLAYWRIGHT",
        "TNVED_SOURCE_DB",
    ]
    w = max(len(k) for k in keys) + 2
    for k in keys:
        name, st = _env_status(k)
        print(f"  {name:<{w}} {st}")


def _script_one_liner(py: Path) -> str:
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return "(не удалось прочитать)"
    doc = ast.get_docstring(tree)
    if doc:
        line = doc.strip().splitlines()[0].strip()
        return (line[:100] + "…") if len(line) > 100 else line
    return "(нет docstring — см. имя файла)"


def _print_scripts() -> None:
    print(_hr("CLI-скрипты (scripts/)"))
    d = _ROOT / "scripts"
    files = sorted(d.glob("*.py"))
    if not files:
        print("  (пусто)")
        return
    print(f"  {'Скрипт':<36} Описание")
    print("  " + "-" * 68)
    for py in files:
        if py.name.startswith("__"):
            continue
        desc = _script_one_liner(py)
        print(f"  {py.name:<36} {desc}")


def main() -> int:
    print("\n╔" + "═" * 70 + "╗")
    print("║" + " CustomsClear — диагностика системы ".center(70) + "║")
    print("╚" + "═" * 70 + "╝")
    _print_database()
    _print_non_tariff_chapters()
    _print_environment()
    _print_scripts()
    print("\n" + "═" * 72)
    print("  Готово.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
