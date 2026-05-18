import re, pathlib
import pdfplumber
from bs4 import BeautifulSoup

try:
    from backend.app.models_vat import VatRule
except Exception:
    from ...app.models_vat import VatRule

CODE_ANY = re.compile(r"\b(\d[\d\.\s]{1,11})\b")

def norm_code(raw: str):
    d = re.sub(r"\D+", "", raw or "")
    if len(d) in (2,4,6,8,10): return d
    for n in (10,8,6,4,2):
        if len(d) >= n: return d[:n]
    return None

def _add(db, code, rate, source, title):
    if not code: return
    # Используем first() вместо one_or_none(), чтобы не падать при дублях
    obj = db.query(VatRule).filter(
        VatRule.code_prefix == code,
        VatRule.rate == rate,
        VatRule.source == source,
    ).first()
    if obj:
        if title and not obj.title:
            obj.title = title[:512]
        return
    db.add(VatRule(code_prefix=code, rate=rate, source=source, title=(title or "")[:512]))
    # Сразу flush, чтобы последующие запросы в этой же сессии видели добавленную запись
    try:
        db.flush()
    except Exception:
        pass

def parse_html(path: pathlib.Path, rate: int, source: str, db_session):
    html = path.read_text("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    # ищем списки и таблицы
    for el in soup.find_all(["tr","li","p","div","span"]):
        txt = " ".join((el.get_text(" ", strip=True) or "").split())
        if not txt: continue
        m = CODE_ANY.search(txt)
        if not m: continue
        code = norm_code(m.group(1))
        if not code: continue
        title = txt[m.end():].strip(" .–—-")
        _add(db_session, code, rate, source, title)

def parse_pdf(path: pathlib.Path, rate: int, source: str, db_session):
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            # таблицы
            try:
                tables = page.extract_tables() or []
            except Exception:
                tables = []
            for row in tables:
                if not row: continue
                first = next((c for c in row if c and c.strip()), "")
                m = CODE_ANY.search(first or "")
                if not m: continue
                code = norm_code(m.group(1))
                if not code: continue
                title = " ".join([c for c in row[1:] if c])[:512] if len(row)>1 else ""
                _add(db_session, code, rate, source, title)
            # текст
            text = page.extract_text() or ""
            for m in CODE_ANY.finditer(text):
                code = norm_code(m.group(1))
                if not code: continue
                line = text[m.start(): text.find("\n", m.start()) if "\n" in text[m.start():] else len(text)]
                title = line[m.end()-m.start():].strip(" .–—-")[:512]
                _add(db_session, code, rate, source, title)

def load_vat_rules(raw_dir: pathlib.Path, rate: int, source: str, db_session) -> int:
    files = list(raw_dir.glob("**/*"))
    before = db_session.query(VatRule).count()
    for p in files:
        suf = p.suffix.lower()
        if suf in (".html",".htm"):
            parse_html(p, rate, source, db_session)
        elif suf == ".pdf":
            parse_pdf(p, rate, source, db_session)
    db_session.commit()
    after = db_session.query(VatRule).count()
    print(f"[vat_rules {source} {rate}%] added {after - before}")
    return after - before


