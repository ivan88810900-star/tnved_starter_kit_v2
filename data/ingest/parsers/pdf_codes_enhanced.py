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

def extract_codes_from_text(text: str):
    """Извлекает коды и описания из текста PDF"""
    lines = text.split('\n')
    codes = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Ищем коды в начале строки
        match = CODE_RE.match(line)
        if match:
            code_raw = match.group(1)
            code = re.sub(r"[\s\.]+", "", code_raw)
            if len(code) in (2,4,6,8,10):
                # Извлекаем описание (все после кода)
                description = line[match.end():].strip()
                if description:
                    codes.append((code, description))
    
    return codes

def parse_pdf_codes_enhanced(raw_dir: pathlib.Path, db_session) -> int:
    files = [p for p in raw_dir.rglob("*.pdf")]
    added = 0
    seen = set()
    
    for fp in files:
        print(f"[pdf_codes] processing {fp.name}")
        with pdfplumber.open(fp) as pdf:
            for page_num, page in enumerate(pdf.pages):
                try:
                    # 1) Пробуем извлечь из таблиц
                    tables = page.extract_tables() or []
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
                        # Проверяем, существует ли уже код
                        existing = db_session.query(HSCode).filter(HSCode.code == code).first()
                        if not existing:
                            db_session.add(HSCode(code=code, title_ru=title[:512], level=level, parent=parent, chapter=chapter))
                            added += 1
                    
                    # 2) Пробуем извлечь из текста
                    text = page.extract_text()
                    if text:
                        text_codes = extract_codes_from_text(text)
                        for code, title in text_codes:
                            if code in seen:
                                continue
                            seen.add(code)
                            level, parent, chapter = _level_parent_chapter(code)
                            # Проверяем, существует ли уже код
                            existing = db_session.query(HSCode).filter(HSCode.code == code).first()
                            if not existing:
                                db_session.add(HSCode(code=code, title_ru=title[:512], level=level, parent=parent, chapter=chapter))
                                added += 1
                            
                except Exception as e:
                    print(f"[pdf_codes] error on page {page_num} of {fp.name}: {e}")
                    continue
    
    db_session.commit()
    print(f"[pdf_codes] inserted_or_updated: {added}")
    return added
