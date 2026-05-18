"""Tariff & TN VED tree scraper (skeleton).
Usage:
  python tariff_scraper.py --source html_dir/ --out out.sqlite
You provide official HTML/CSV/XML dumps locally (no live scraping here).
The script parses hierarchy (sections -> chapters -> headings -> subheadings),
titles (ru/en), and extracts Notes to Sections/Chapters.
"""

import argparse, pathlib, re, sqlite3, json
from bs4 import BeautifulSoup

def ensure_db(path: str):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.executescript(open(str(pathlib.Path(__file__).parent.parent.parent / "sql" / "schema.sql"), "r", encoding="utf-8").read())
    conn.commit()
    return conn

def parse_html_file(fp: pathlib.Path):
    html = fp.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    # Heuristics: users must adapt selectors to their official dump structure
    # Try to find code/title pairs and notes
    items = []
    notes = []
    for row in soup.select("tr"):
        tds = [td.get_text(" ", strip=True) for td in row.find_all("td")]
        if len(tds) >= 2 and re.match(r"^\d{2}(\.?\d{2})?(\.?\d{2})?(\.?\d{2})?$", tds[0]):
            code = tds[0].replace(" ", "")
            title = tds[1]
            items.append((code, title))
    # Notes: look for headings like 'Примечания к разделу' / 'Примечания к группе'
    for n in soup.find_all(text=re.compile(r"Примечания\s+к\s+(разделу|группе)", re.I)):
        section = n.parent.get_text(" ", strip=True)
        block = section
        # capture following siblings text
        sib = n.parent.find_next_sibling()
        parts = [section]
        while sib and sib.name in ("p", "div", "ul", "ol"):
            parts.append(sib.get_text(" ", strip=True))
            sib = sib.find_next_sibling()
        notes.append("\n".join(parts))
    return items, notes

def import_dir(html_dir: str, out_db: str):
    conn = ensure_db(out_db)
    cur = conn.cursor()
    for fp in pathlib.Path(html_dir).glob("**/*.html"):
        items, notes = parse_html_file(fp)
        for code, title in items:
            # naive mapping to chapter/heading/subheading
            chapter = code[:2] if len(code) >= 2 else None
            heading = code[:4] if len(code) >= 4 else None
            subheading = code[:6] if len(code) >= 6 else None
            cur.execute("INSERT OR IGNORE INTO hs_codes(code,title_ru,chapter,heading,subheading) VALUES(?,?,?,?,?)",
                        (code, title, chapter, heading, subheading))
        for block in notes:
            # try to detect level/id
            m = re.search(r"Примечания\s+к\s+(разделу|группе)\s+([IVXLC]+|\d{2})", block, re.I)
            level = "section"
            ref_id = "I"
            if m:
                level = "section" if m.group(1).lower().startswith("раздел") else "chapter"
                ref_id = m.group(2)
            cur.execute("INSERT INTO notes(level, ref_id, text) VALUES(?,?,?)", (level, ref_id, block))
        conn.commit()
    conn.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="Directory with official HTML/CSV/XML dumps (downloaded)" )
    ap.add_argument("--out", default="out.sqlite", help="Path to SQLite DB file" )
    args = ap.parse_args()
    import_dir(args.source, args.out)
    print("Imported to", args.out)
