import re, pathlib
from bs4 import BeautifulSoup
try:
    from backend.app.models_hs import Note
except Exception:
    from ...app.models_hs import Note

SEC_RE = re.compile(r"Примечания?\s+к\s+раздел[ау]?\s+([IVXLCDM]+)", re.IGNORECASE)
CH_RE  = re.compile(r"Примечания?\s+к\s+групп[еы]\s+(\d{2})", re.IGNORECASE)

def parse_notes_html(raw_dir: pathlib.Path, db_session) -> int:
    files = [p for p in raw_dir.glob("**/*.html")] + [p for p in raw_dir.glob("**/*.htm")] + [p for p in raw_dir.glob("**/*.pdf")]
    # PDF пока пропустим; HTML хватит для старта
    files = [p for p in files if p.suffix.lower() != ".pdf"]
    added = 0
    for fp in files:
        html = fp.read_text("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text("\n", strip=True)
        m = SEC_RE.search(text)
        if m:
            db_session.add(Note(level="section", ref_id=m.group(1), text=text)); added += 1; continue
        m = CH_RE.search(text)
        if m:
            db_session.add(Note(level="chapter", ref_id=m.group(1), text=text)); added += 1
    db_session.commit()
    print(f"[notes] inserted: {added}")
    return added