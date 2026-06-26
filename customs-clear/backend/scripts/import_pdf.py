"""
Импорт ТН ВЭД из 96 PDF-файлов в базу данных.

Использование:
  python import_pdf.py [--data-dir /path/to/pdfs] [--db /path/to/customs.db] [--dry-run]

По умолчанию:
  --data-dir  ../app/services/source_sync/data
  --db        ../customs.db
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Добавляем директорию scripts в sys.path для импорта парсера
sys.path.insert(0, str(Path(__file__).parent))

import sqlite3
from tnved_pdf_parser import parse_pdf, ChapterData

log = logging.getLogger(__name__)

# ── Справочник разделов ТН ВЭД (канонические названия) ─────────────────────
SECTION_TITLES = {
    "I":     "ЖИВЫЕ ЖИВОТНЫЕ; ПРОДУКТЫ ЖИВОТНОГО ПРОИСХОЖДЕНИЯ",
    "II":    "ПРОДУКТЫ РАСТИТЕЛЬНОГО ПРОИСХОЖДЕНИЯ",
    "III":   "ЖИРЫ И МАСЛА ЖИВОТНОГО ИЛИ РАСТИТЕЛЬНОГО ПРОИСХОЖДЕНИЯ И ПРОДУКТЫ ИХ РАСЩЕПЛЕНИЯ; ГОТОВЫЕ ПИЩЕВЫЕ ЖИРЫ; ВОСКИ ЖИВОТНОГО ИЛИ РАСТИТЕЛЬНОГО ПРОИСХОЖДЕНИЯ",
    "IV":    "ГОТОВЫЕ ПИЩЕВЫЕ ПРОДУКТЫ; АЛКОГОЛЬНЫЕ И БЕЗАЛКОГОЛЬНЫЕ НАПИТКИ И УКСУС; ТАБАК И ЕГО ЗАМЕНИТЕЛИ",
    "V":     "МИНЕРАЛЬНЫЕ ПРОДУКТЫ",
    "VI":    "ПРОДУКЦИЯ ХИМИЧЕСКОЙ И СВЯЗАННЫХ С НЕЙ ОТРАСЛЕЙ ПРОМЫШЛЕННОСТИ",
    "VII":   "ПЛАСТМАССЫ И ИЗДЕЛИЯ ИЗ НИХ; КАУЧУК, РЕЗИНА И ИЗДЕЛИЯ ИЗ НИХ",
    "VIII":  "НЕОБРАБОТАННЫЕ ШКУРЫ, ВЫДЕЛАННАЯ КОЖА, НАТУРАЛЬНЫЙ МЕХ И ИЗДЕЛИЯ ИЗ НИХ; ШОРНО-СЕДЕЛЬНЫЕ ИЗДЕЛИЯ И УПРЯЖЬ; ДОРОЖНЫЕ ПРИНАДЛЕЖНОСТИ, ДАМСКИЕ СУМКИ И АНАЛОГИЧНЫЕ ИМ ТОВАРЫ; ИЗДЕЛИЯ ИЗ КИШОК ЖИВОТНЫХ (КРОМЕ КЕТГУТА ИЗ ШЕЛКА)",
    "IX":    "ДРЕВЕСИНА И ИЗДЕЛИЯ ИЗ НЕЁ; ДРЕВЕСНЫЙ УГОЛЬ; ПРОБКА И ИЗДЕЛИЯ ИЗ НЕЁ; ИЗДЕЛИЯ ИЗ СОЛОМЫ, АЛЬФЫ ИЛИ ПРОЧИХ МАТЕРИАЛОВ ДЛЯ ПЛЕТЕНИЯ; КОРЗИНОЧНЫЕ И ДРУГИЕ ПЛЕТЁНЫЕ ИЗДЕЛИЯ",
    "X":     "МАССА ИЗ ДРЕВЕСИНЫ ИЛИ ДРУГИХ ВОЛОКНИСТЫХ ЦЕЛЛЮЛОЗНЫХ МАТЕРИАЛОВ; РЕГЕНЕРИРУЕМЫЕ БУМАГА ИЛИ КАРТОН (МАКУЛАТУРА И ОТХОДЫ); БУМАГА, КАРТОН И ИЗДЕЛИЯ ИЗ НИХ",
    "XI":    "ТЕКСТИЛЬНЫЕ МАТЕРИАЛЫ И ТЕКСТИЛЬНЫЕ ИЗДЕЛИЯ",
    "XII":   "ОБУВЬ, ГОЛОВНЫЕ УБОРЫ, ЗОНТЫ, СОЛНЦЕЗАЩИТНЫЕ ЗОНТЫ, ТРОСТИ, ТРОСТИ-СИДЕНЬЯ, ХЛЫСТЫ, КНУТЫ ДЛЯ ВЕРХОВОЙ ЕЗДЫ И ИХ ЧАСТИ; ПЕРЬЯ ОБРАБОТАННЫЕ И ИЗДЕЛИЯ ИЗ НИХ; ИСКУССТВЕННЫЕ ЦВЕТЫ; ИЗДЕЛИЯ ИЗ ВОЛОС ЧЕЛОВЕКА",
    "XIII":  "ИЗДЕЛИЯ ИЗ КАМНЯ, ГИПСА, ЦЕМЕНТА, АСБЕСТА, СЛЮДЫ ИЛИ АНАЛОГИЧНЫХ МАТЕРИАЛОВ; КЕРАМИЧЕСКИЕ ИЗДЕЛИЯ; СТЕКЛО И ИЗДЕЛИЯ ИЗ НЕГО",
    "XIV":   "ПРИРОДНЫЕ ИЛИ КУЛЬТИВИРОВАННЫЕ ЖЕМЧУГ, ДРАГОЦЕННЫЕ ИЛИ ПОЛУДРАГОЦЕННЫЕ КАМНИ, ДРАГОЦЕННЫЕ МЕТАЛЛЫ, МЕТАЛЛЫ, ПЛАКИРОВАННЫЕ ДРАГОЦЕННЫМИ МЕТАЛЛАМИ, И ИЗДЕЛИЯ ИЗ НИХ; БИЖУТЕРИЯ; МОНЕТЫ",
    "XV":    "НЕДРАГОЦЕННЫЕ МЕТАЛЛЫ И ИЗДЕЛИЯ ИЗ НИХ",
    "XVI":   "МАШИНЫ, ОБОРУДОВАНИЕ И МЕХАНИЗМЫ; ЭЛЕКТРОТЕХНИЧЕСКОЕ ОБОРУДОВАНИЕ; ИХ ЧАСТИ; ЗВУКОЗАПИСЫВАЮЩАЯ И ЗВУКОВОСПРОИЗВОДЯЩАЯ АППАРАТУРА, АППАРАТУРА ДЛЯ ЗАПИСИ И ВОСПРОИЗВЕДЕНИЯ ТЕЛЕВИЗИОННОГО ИЗОБРАЖЕНИЯ И ЗВУКА, ИХ ЧАСТИ И ПРИНАДЛЕЖНОСТИ",
    "XVII":  "СРЕДСТВА НАЗЕМНОГО ТРАНСПОРТА, ЛЕТАТЕЛЬНЫЕ АППАРАТЫ, ПЛАВУЧИЕ СРЕДСТВА И ОТНОСЯЩИЕСЯ К ТРАНСПОРТУ УСТРОЙСТВА И ОБОРУДОВАНИЕ",
    "XVIII": "ИНСТРУМЕНТЫ И АППАРАТЫ ОПТИЧЕСКИЕ, ФОТОГРАФИЧЕСКИЕ, КИНЕМАТОГРАФИЧЕСКИЕ, ИЗМЕРИТЕЛЬНЫЕ, КОНТРОЛЬНЫЕ, ПРЕЦИЗИОННЫЕ, МЕДИЦИНСКИЕ ИЛИ ХИРУРГИЧЕСКИЕ; ЧАСЫ; МУЗЫКАЛЬНЫЕ ИНСТРУМЕНТЫ; ИХ ЧАСТИ И ПРИНАДЛЕЖНОСТИ",
    "XIX":   "ОРУЖИЕ И БОЕПРИПАСЫ; ИХ ЧАСТИ И ПРИНАДЛЕЖНОСТИ",
    "XX":    "РАЗНЫЕ ПРОМЫШЛЕННЫЕ ТОВАРЫ",
    "XXI":   "ПРОИЗВЕДЕНИЯ ИСКУССТВА, ПРЕДМЕТЫ КОЛЛЕКЦИОНИРОВАНИЯ И АНТИКВАРИАТ",
}

# Маппинг глава → раздел (для глав где PDF не содержит info о разделе)
CHAPTER_TO_SECTION: dict[str, str] = {
    **{str(i).zfill(2): "I"   for i in range(1, 6)},
    **{str(i).zfill(2): "II"  for i in range(6, 15)},
    **{str(i).zfill(2): "III" for i in range(15, 16)},
    **{str(i).zfill(2): "IV"  for i in range(16, 25)},
    **{str(i).zfill(2): "V"   for i in range(25, 28)},
    **{str(i).zfill(2): "VI"  for i in range(28, 39)},
    **{str(i).zfill(2): "VII" for i in range(39, 41)},
    **{str(i).zfill(2): "VIII"for i in range(41, 44)},
    **{str(i).zfill(2): "IX"  for i in range(44, 47)},
    **{str(i).zfill(2): "X"   for i in range(47, 50)},
    **{str(i).zfill(2): "XI"  for i in range(50, 64)},
    **{str(i).zfill(2): "XII" for i in range(64, 68)},
    **{str(i).zfill(2): "XIII"for i in range(68, 71)},
    **{str(i).zfill(2): "XIV" for i in range(71, 72)},
    **{str(i).zfill(2): "XV"  for i in range(72, 84)},
    **{str(i).zfill(2): "XVI" for i in range(84, 86)},
    **{str(i).zfill(2): "XVII"for i in range(86, 90)},
    **{str(i).zfill(2): "XVIII"for i in range(90, 93)},
    **{str(i).zfill(2): "XIX" for i in range(93, 94)},
    **{str(i).zfill(2): "XX"  for i in range(94, 97)},
    "97":                       "XXI",
}


# ── Работа с базой данных ─────────────────────────────────────────────────────

def get_or_create_section(
    conn: sqlite3.Connection,
    roman: str,
    title: str = "",
    notes: str = "",
) -> int:
    """Возвращает id раздела, создавая его при необходимости."""
    cur = conn.execute(
        "SELECT id FROM tnved_sections WHERE roman_number = ?", (roman,)
    )
    row = cur.fetchone()
    if row:
        # Обновляем заголовок если он был пустым
        if title:
            conn.execute(
                "UPDATE tnved_sections SET title = ? WHERE roman_number = ? AND (title = '' OR title IS NULL)",
                (title, roman),
            )
        return row[0]
    else:
        canonical_title = SECTION_TITLES.get(roman, title)
        cur = conn.execute(
            "INSERT INTO tnved_sections (roman_number, title, notes) VALUES (?, ?, ?)",
            (roman, canonical_title or title, notes),
        )
        return cur.lastrowid


def get_or_create_chapter(
    conn: sqlite3.Connection,
    chapter_code: str,
    section_id: int,
    title: str = "",
    notes: str = "",
) -> int:
    """Возвращает id главы (группы), обновляя заголовок и примечания."""
    cur = conn.execute(
        "SELECT id FROM tnved_chapters WHERE code = ?", (chapter_code,)
    )
    row = cur.fetchone()
    if row:
        chapter_id = row[0]
        conn.execute(
            "UPDATE tnved_chapters SET title = ?, notes = ?, section_id = ? WHERE id = ?",
            (title, notes, section_id, chapter_id),
        )
        return chapter_id
    else:
        cur = conn.execute(
            "INSERT INTO tnved_chapters (section_id, code, title, notes) VALUES (?, ?, ?, ?)",
            (section_id, chapter_code, title, notes),
        )
        return cur.lastrowid


def import_chapter(
    conn: sqlite3.Connection,
    data: ChapterData,
    dry_run: bool = False,
) -> int:
    """
    Импортирует данные одной группы в БД.
    Возвращает количество импортированных строк.
    """
    # Определяем раздел
    roman = data.section_roman
    if not roman:
        roman = CHAPTER_TO_SECTION.get(data.chapter_code, "I")

    section_title = data.section_title or SECTION_TITLES.get(roman, "")
    section_id = get_or_create_section(conn, roman, section_title, "")

    # Получаем/создаём главу
    chapter_id = get_or_create_chapter(
        conn,
        data.chapter_code,
        section_id,
        data.chapter_title,
        data.notes,
    )

    if dry_run:
        log.info(
            "[dry-run] Группа %s: %d строк → chapter_id=%d",
            data.chapter_code, len(data.rows), chapter_id,
        )
        return len(data.rows)

    # Удаляем старые позиции для этой главы
    conn.execute("DELETE FROM tnved_commodities WHERE chapter_id = ?", (chapter_id,))

    # Вставляем новые позиции (OR IGNORE для защиты от дублей кодов)
    insert_count = 0
    for row in data.rows:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO tnved_commodities
              (chapter_id, code, description, unit, import_duty)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                chapter_id,
                row.code,
                row.description,
                row.unit,
                row.duty,
            ),
        )
        if cur.rowcount:
            insert_count += 1
        else:
            log.debug("Пропущен дубль: %s %s", row.code, row.description[:40])

    return insert_count


# ── Основная функция ──────────────────────────────────────────────────────────

def run_import(
    data_dir: Path,
    db_path: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> None:
    """Запускает импорт всех PDF из data_dir в базу данных db_path."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    pdfs = sorted(data_dir.glob("ru.*.pdf"))
    if not pdfs:
        log.error("PDF файлы не найдены в %s", data_dir)
        sys.exit(1)

    log.info("Найдено %d PDF файлов", len(pdfs))

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    total_rows = 0
    errors: list[tuple[str, str]] = []

    try:
        for i, pdf_path in enumerate(pdfs, 1):
            try:
                log.info("[%d/%d] Парсинг %s...", i, len(pdfs), pdf_path.name)
                chapter_data = parse_pdf(pdf_path)
                count = import_chapter(conn, chapter_data, dry_run=dry_run)
                total_rows += count
                log.info(
                    "  → Группа %s «%s»: %d строк",
                    chapter_data.chapter_code,
                    chapter_data.chapter_title[:50],
                    count,
                )
            except Exception as e:
                log.error("ОШИБКА в %s: %s", pdf_path.name, e, exc_info=verbose)
                errors.append((pdf_path.name, str(e)))

        if not dry_run:
            conn.commit()
            log.info("✓ Транзакция зафиксирована")

    except KeyboardInterrupt:
        log.warning("Прерван пользователем")
        conn.rollback()
    finally:
        conn.close()

    log.info("=" * 60)
    log.info("ИТОГ: %d строк импортировано, %d ошибок", total_rows, len(errors))
    if errors:
        log.error("Ошибки:")
        for fname, err in errors:
            log.error("  %s: %s", fname, err)

    # Финальная статистика
    if not dry_run:
        conn2 = sqlite3.connect(str(db_path))
        for tbl in ("tnved_sections", "tnved_chapters", "tnved_commodities"):
            cnt = conn2.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            log.info("  %s: %d строк", tbl, cnt)
        conn2.close()


# ── Точка входа ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Импорт ТН ВЭД из PDF в SQLite")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent.parent / "app" / "services" / "source_sync" / "data",
        help="Папка с PDF файлами",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).parent.parent / "customs.db",
        help="Путь к БД SQLite",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только парсинг, без записи в БД",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Подробный вывод",
    )

    args = parser.parse_args()

    if not args.data_dir.exists():
        print(f"Ошибка: папка {args.data_dir} не найдена")
        sys.exit(1)

    if not args.dry_run and not args.db.exists():
        print(f"Предупреждение: БД {args.db} не найдена, будет создана новая")

    run_import(
        data_dir=args.data_dir,
        db_path=args.db,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
