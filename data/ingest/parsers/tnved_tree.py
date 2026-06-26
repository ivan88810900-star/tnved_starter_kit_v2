from __future__ import annotations
import re, pathlib
from bs4 import BeautifulSoup
from lxml import etree
try:
    from backend.app.models_hs import HSCode
except Exception:
    from ...app.models_hs import HSCode

CODE_RE = re.compile(r"\b(\d[\d\.\s]{1,})\b")
def norm_code(raw: str):
    d = re.sub(r"\D+", "", raw or "")
    if len(d) in (2,4,6,8,10): return d
    for n in (10,8,6,4,2):
        if len(d) >= n: return d[:n]
    return None

def level_of(code: str):
    L=len(code)
    if L==2:  return "chapter", None, code[:2]
    if L==4:  return "heading", code[:2], code[:2]
    if L==6:  return "subheading", code[:4], code[:2]
    if L==8:  return "item", code[:6], code[:2]
    if L==10: return "item", code[:8], code[:2]
    return "unknown", None, None

def extract_from_html(path: pathlib.Path):
    html = path.read_text("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    for el in soup.find_all(["tr","p","li","div","span"]):
        txt = " ".join((el.get_text(" ", strip=True) or "").split())
        if not txt: continue
        m = CODE_RE.match(txt)
        if not m: continue
        code = norm_code(m.group(1))
        if not code: continue
        title = txt[m.end():].strip(" .-–—")
        if title: yield code, title

def extract_from_xml(path: pathlib.Path):
    root = etree.parse(str(path))
    for node in root.xpath("//*[code or @code]"):
        code = node.get("code") or "".join(node.xpath(".//code/text()"))
        title = (node.get("name") or node.get("title") or
                 " ".join(t.strip() for t in node.xpath(".//name/text() | .//title/text()")))
        code = norm_code(code); title = (title or "").strip()
        if code and title: yield code, title

def parse_tnved_tree(raw_dir: pathlib.Path, db_session) -> int:
    files = [p for p in raw_dir.glob("**/*") if p.suffix.lower() in (".html",".htm",".xml")]
    if not files:
        print(f"[tnved_tree] no HTML/XML files in {raw_dir}"); return 0
    seen=set(); batch=[]; added=0
    for fp in files:
        it = extract_from_xml(fp) if fp.suffix.lower()==".xml" else extract_from_html(fp)
        for code, title in it:
            if code in seen: continue
            seen.add(code)
            level, parent, chapter = level_of(code)
            batch.append(HSCode(code=code, title_ru=title[:512], level=level, parent=parent, chapter=chapter))
            if len(batch)>=1000:
                db_session.bulk_save_objects(batch); db_session.commit(); added += len(batch); batch=[]
    if batch:
        db_session.bulk_save_objects(batch); db_session.commit(); added += len(batch)
    print(f"[tnved_tree] inserted: {added}")
    return added