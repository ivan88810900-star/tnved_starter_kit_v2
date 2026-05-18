import pathlib, re
import pdfplumber
try:
    from backend.app.models_hs import Note
except Exception:
    from ...app.models_hs import Note

# Заголовки контекста
SECTION_HDR = re.compile(r"\bРаздел\s+([IVXLCDM]+)\b", re.IGNORECASE)
CHAPTER_HDR = re.compile(r"\b(Глава|Групп[аы])\s+(\d{1,2})\b", re.IGNORECASE)

# Заголовок «Примечания» (в любых вариациях)
NOTES_HDR = re.compile(r"\bПримечани[ея]:?\b", re.IGNORECASE)

# Граница конца блока примечаний — следующий крупный заголовок
NEXT_BLOCK = re.compile(r"\b(Раздел\s+[IVXLCDM]+|Глава\s+\d{1,2}|Групп[аы]\s+\d{1,2}|Таблиц[аы]|Приложени[ея])\b", re.IGNORECASE)

def _norm_chapter(n: str) -> str:
    n = re.sub(r"\D+", "", n or "")
    return n.zfill(2) if n else None

def parse_pdf_notes(raw_dir: pathlib.Path, db_session) -> int:
    files = [p for p in raw_dir.glob("*.pdf")]
    added = 0
    for fp in files:
        with pdfplumber.open(fp) as pdf:
            current_section = None    # I..XXI
            current_chapter = None    # 01..99

            # Сканируем постранично, собирая контекст и блоки «Примечания»
            i = 0
            while i < len(pdf.pages):
                text = (pdf.pages[i].extract_text() or "")
                # Обновим контекст по заголовкам
                m = SECTION_HDR.search(text)
                if m:
                    current_section = m.group(1)
                m = CHAPTER_HDR.search(text)
                if m:
                    current_chapter = _norm_chapter(m.group(2))

                if NOTES_HDR.search(text):
                    # Собираем блок от «Примечания…» до следующего крупного заголовка (включая последующие страницы)
                    block = []
                    # обрежем от заголовка «Примечания» до конца страницы
                    start = NOTES_HDR.search(text).start()
                    tail = text[start:]
                    block.append(tail)

                    # возможно, текст продолжается на следующих страницах
                    j = i + 1
                    while j < len(pdf.pages):
                        t2 = (pdf.pages[j].extract_text() or "")
                        if NEXT_BLOCK.search(t2):
                            break
                        block.append(t2)
                        j += 1

                    full = "\n".join(block).strip()
                    # Определим уровень: сначала глава, потом раздел, иначе general
                    if current_chapter:
                        db_session.add(Note(level="chapter", ref_id=current_chapter, text=full))
                    elif current_section:
                        db_session.add(Note(level="section", ref_id=current_section, text=full))
                    else:
                        db_session.add(Note(level="general", ref_id="ETT", text=full))
                    added += 1

                    # Продолжаем после собранного блока
                    i = j
                    continue

                i += 1

    db_session.commit()
    print(f"[pdf_notes] inserted: {added}")
    return added

