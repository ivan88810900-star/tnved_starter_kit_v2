import re, pathlib
import pdfplumber
try:
    from backend.app.models_hs import HSCode
except Exception:
    from ...app.models_hs import HSCode

CODE_RE = re.compile(r"^\s*(\d{2}(?:[\s\.]?\d{2}){0,4})\b")

def _level_parent_chapter(code: str):
    L=len(code)
    if L==2:  return "chapter", None, code[:2]
    if L==4:  return "heading", code[:2], code[:2]
    if L==6:  return "subheading", code[:4], code[:2]
    if L==8:  return "item", code[:6], code[:2]
    if L==10: return "item", code[:8], code[:2]
    return "unknown", None, None

def parse_pdf_codes(raw_dir: pathlib.Path, db_session) -> int:
    files = [p for p in raw_dir.rglob("*.pdf")]
    added = 0
    seen = set()
    for fp in files:
        with pdfplumber.open(fp) as pdf:
            for page in pdf.pages:
                # 1) Таблицы
                try:
                    tables = page.extract_tables() or []
                except Exception:
                    tables = []
                for row in tables:
                    if not row:
                        continue
                    first = next((c for c in row if c and str(c).strip()), "")
                    m = CODE_RE.match(str(first)) if first else None
                    if not m:
                        continue
                    code_raw = m.group(1)
                    code = re.sub(r"[\s\.]+", "", code_raw)
                    if len(code) not in (2,4,6,8,10):
                        continue
                    title = " ".join([str(c).strip() for c in row[1:] if c])
                    if not title:
                        continue
                    if code in seen:
                        continue
                    seen.add(code)
                    level, parent, chapter = _level_parent_chapter(code)
                    obj = db_session.query(HSCode).filter(HSCode.code==code).one_or_none()
                    if obj:
                        if not obj.title_ru and title:
                            obj.title_ru = title[:512]
                        if not obj.level:   obj.level = level
                        if not obj.parent:  obj.parent = parent
                        if not obj.chapter: obj.chapter = chapter
                    else:
                        db_session.add(HSCode(
                            code=code, title_ru=title[:512],
                            level=level, parent=parent, chapter=chapter
                        ))
                        added += 1

                # 2) Плоский текст
                text = page.extract_text() or ""
                for line in text.splitlines():
                    s = line.strip()
                    m = CODE_RE.match(s)
                    if not m: 
                        continue
                    # убираем пробелы и точки
                    code = re.sub(r"[\s\.]+", "", m.group(1))
                    if len(code) not in (2,4,6,8,10): 
                        continue
                    title = s[m.end():].strip(" .–—-")
                    if not title:
                        continue
                    if code in seen: 
                        continue
                    seen.add(code)
                    level, parent, chapter = _level_parent_chapter(code)

                    # upsert по коду
                    obj = db_session.query(HSCode).filter(HSCode.code==code).one_or_none()
                    if obj:
                        if not obj.title_ru and title:
                            obj.title_ru = title[:512]
                        if not obj.level:   obj.level = level
                        if not obj.parent:  obj.parent = parent
                        if not obj.chapter: obj.chapter = chapter
                    else:
                        db_session.add(HSCode(
                            code=code, title_ru=title[:512],
                            level=level, parent=parent, chapter=chapter
                        ))
                        added += 1
    db_session.commit()
    print(f"[pdf_codes] inserted_or_updated: {added}")
    return added

