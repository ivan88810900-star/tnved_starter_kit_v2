"""Local source-presentation additions; the active catalog is never rewritten.

PDF raster fragments preserve typography without guessing formula or note meaning.
Build dependencies are imported only by the offline builder, never by HTTP.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import xml.etree.ElementTree as ET


class PresentationIntegrityError(RuntimeError):
    """A declared source-presentation artifact is absent or has changed."""


SCHEMA = """
CREATE TABLE recovery_presentation_items (
 node_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, notice TEXT NOT NULL,
 reasons_json TEXT NOT NULL, spacing_json TEXT,
 FOREIGN KEY(source_id) REFERENCES recovery_sources(id)
);
CREATE TABLE recovery_source_fragments (
 node_id TEXT NOT NULL, ordinal INTEGER NOT NULL, page INTEGER NOT NULL,
 bounds_json TEXT NOT NULL, sha256 TEXT NOT NULL, png BLOB NOT NULL,
 PRIMARY KEY(node_id,ordinal),
 FOREIGN KEY(node_id) REFERENCES recovery_presentation_items(node_id)
);
CREATE TABLE recovery_reserved_markers (
 id TEXT PRIMARY KEY, chapter TEXT NOT NULL, printed_code TEXT NOT NULL,
 before_order INTEGER NOT NULL, marker_order INTEGER NOT NULL, page INTEGER NOT NULL,
 source_row_id TEXT NOT NULL,
 FOREIGN KEY(id) REFERENCES recovery_presentation_items(node_id),
 FOREIGN KEY(chapter) REFERENCES recovery_navigation(id)
);
CREATE INDEX recovery_reserved_chapter ON recovery_reserved_markers(chapter,before_order,marker_order);
"""

FORMAT_NOTICE = (
    "Текстовая подпись упрощает оформление индексов и ссылок на примечания. "
    "Для точного чтения используйте фрагмент оригинала ниже. "
    "Значение сносок и юридическая применимость не интерпретированы."
)
MARKER_NOTICE = (
    "Неактивная отметка официальной последовательности, не товарный код для выбора или расчёта. "
    "Правовой статус не устанавливается по квадратным скобкам."
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def page_inventory(pdf: Path, executable: str) -> list[dict]:
    """Retain actual word bounds, small glyphs and bracketed code cells."""
    xml = subprocess.check_output([executable, '-bbox', '-enc', 'UTF-8', str(pdf), '-'], stderr=subprocess.PIPE)
    pages = ET.fromstring(xml).findall('.//{http://www.w3.org/1999/xhtml}page')
    result = []
    for number, page in enumerate(pages, 1):
        words = [(float(w.get('xMin')), float(w.get('yMin')), float(w.get('xMax')), float(w.get('yMax')), w.text or '') for w in page.findall('.//{http://www.w3.org/1999/xhtml}word')]
        names = [w for w in words if w[4] == 'Наименование']
        bottoms = [w for w in words if w[4] == 'долларах']
        lines = []
        if names:
            if len(names) != 1 or len(bottoms) != 1:
                raise ValueError(f'Ambiguous original table header: {pdf.name}/{number}')
            body = [w for w in words if w[1] >= bottoms[0][3] and w[0] < 399]
            for word in sorted((w for w in body if w[3] - w[1] > 10), key=lambda w: (w[3], w[0])):
                match = next((line for line in reversed(lines[-3:]) if abs(line['baseline'] - word[3]) < 3), None)
                if match is None:
                    lines.append({'baseline': word[3], 'words': [word], 'small': []})
                else:
                    match['words'].append(word)
            for word in (w for w in body if w[3] - w[1] <= 10):
                if not lines:
                    raise ValueError('Unattached source glyph')
                def overlap(line):
                    top = min(w[1] for w in line['words'])
                    bottom = max(w[3] for w in line['words'])
                    return max(0, min(bottom, word[3]) - max(top, word[1])), -abs(top + bottom - word[1] - word[3])
                max(lines, key=overlap)['small'].append(word)
        result.append({'page': number, 'width': float(page.get('width')), 'height': float(page.get('height')), 'lines': lines})
    return result


def source_fragment(document, page_meta: dict, lines: list[dict]) -> tuple[bytes, list[float]]:
    """Render the original code/name cells, including raised/lowered glyphs."""
    words = [w for line in lines for w in line['words'] + line['small']]
    bounds = [90.0, max(0, min(w[1] for w in words) - 2), min(page_meta['width'], max(404.0, max(w[2] for w in words) + 2)), min(page_meta['height'], max(w[3] for w in words) + 2)]
    page = document[page_meta['page'] - 1]
    try:
        bitmap = page.render(scale=2, crop=(bounds[0], page_meta['height'] - bounds[3], page_meta['width'] - bounds[2], bounds[1]))
        try:
            image = bitmap.to_pil()
            output = io.BytesIO()
            image.save(output, format='PNG', compress_level=9)
            image.close()
            return output.getvalue(), [round(v, 3) for v in bounds]
        finally:
            bitmap.close()
    finally:
        page.close()


def build(base: Path, base_pin: str, sources: Path, manifest_pin: str, spacing_path: Path, output: Path, executable: str) -> dict:
    import pypdfium2  # build only; HTTP serves pinned bytes from the SAME SQLite
    if any(p.exists() or p.is_symlink() for p in (output, output.with_suffix('.manifest.json'))):
        raise ValueError('Refusing to replace a candidate')
    temporary = output.with_name('.' + output.name + '.building')
    if temporary.exists() or temporary.is_symlink() or any(Path(str(base) + s).exists() for s in ('-wal', '-shm', '-journal')):
        raise ValueError('Existing build or mutable baseline sidecar')
    if digest(base.read_bytes()) != base_pin or digest((sources / 'manifest.json').read_bytes()) != manifest_pin:
        raise ValueError('Explicit baseline/source identity mismatch')
    manifest = json.loads((sources / 'manifest.json').read_text())
    if [r['chapter'] for r in manifest['chapters']] != [f'{i:02}' for i in range(1, 98) if i != 77]:
        raise ValueError('Official chapter coverage mismatch')
    ledger = {r['node_id']: r for r in json.loads(spacing_path.read_text())}
    if len(ledger) != 10 or any(r['status'] != 'open_limitation' for r in ledger.values()):
        raise ValueError('The ten spacing distinctions must remain explicit and open')
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base, temporary)
    temporary.chmod(0o600)
    chapters, marker_total, formatted_total, fragment_total = [], 0, 0, 0
    with closing(sqlite3.connect(temporary)) as db:
        db.row_factory = sqlite3.Row
        metadata = dict(db.execute('SELECT key,value FROM recovery_metadata'))
        if metadata['legal_status'] != 'unverified' or metadata['rates_present'] != 'false':
            raise ValueError('Only the unverified structural profile is allowed')
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(SCHEMA)
        with db:
            for entry in manifest['chapters']:
                chapter = entry['chapter']
                pdf = sources / f'chapter-{chapter}.pdf'
                if digest(pdf.read_bytes()) != entry['sha256']:
                    raise ValueError('Original PDF hash mismatch: ' + chapter)
                source = db.execute('SELECT id FROM recovery_sources WHERE sha256=? AND url=?', (entry['sha256'], entry['url'])).fetchone()
                if source is None:
                    raise ValueError('Original PDF is not a source of this candidate')
                inventory = page_inventory(pdf, executable)
                pages = {p['page']: p for p in inventory}
                nodes = [dict(row) for row in db.execute("SELECT n.*,t.raw_lines_json FROM recovery_navigation n JOIN recovery_source_text t ON t.node_id=n.id WHERE n.chapter=? AND n.kind NOT IN ('chapter','section') ORDER BY n.source_order", (chapter,))]
                positions = [(n['page'], json.loads(n['raw_lines_json'])[0]['baseline'], n['source_order']) for n in nodes]
                markers = []
                for page in inventory:
                    for line in page['lines']:
                        cell = ''.join(w[4] for w in sorted(line['words'], key=lambda w: w[0]) if w[0] < 180).replace('+', '')
                        if re.fullmatch(r'\[\d{4}\]', cell):
                            marker_id = 'u-' + digest(f"reserved:{entry['sha256']}:{page['page']}:{line['baseline']:.3f}".encode())[:24]
                            before = next((order for pg, y, order in positions if (pg, y) > (page['page'], line['baseline'])), len(nodes))
                            markers.append((marker_id, cell, before, page, line))
                document = pypdfium2.PdfDocument(pdf)
                affected = 0
                try:
                    for node in nodes:
                        grouped = defaultdict(list)
                        small = []
                        for raw in json.loads(node['raw_lines_json']):
                            page = pages[raw['page']]
                            line = min(page['lines'], key=lambda l: abs(l['baseline'] - raw['baseline']))
                            if abs(line['baseline'] - raw['baseline']) > .01:
                                raise ValueError('Unmatched source baseline: ' + node['id'])
                            grouped[raw['page']].append(line)
                            small.extend(w[4] for w in line['small'] if w[0] >= 180)
                        difference = ledger.get(node['id'])
                        if difference and (difference['display_text'] != node['label'] or difference['source_sha256'] != entry['sha256'] or difference['page'] != node['page']):
                            raise ValueError('Spacing ledger no longer matches candidate/source')
                        if not small and not difference:
                            continue
                        reasons = (['source_small_glyphs'] if small else []) + (['spacing_difference'] if difference else [])
                        db.execute('INSERT INTO recovery_presentation_items VALUES (?,?,?,?,?)', (node['id'], source['id'], FORMAT_NOTICE if small else 'Написание источника и отображение различаются пробелами; различие сохранено как ограничение.', json.dumps(reasons), json.dumps(difference, ensure_ascii=False) if difference else None))
                        for ordinal, (number, lines) in enumerate(grouped.items()):
                            png, bounds = source_fragment(document, pages[number], lines)
                            db.execute('INSERT INTO recovery_source_fragments VALUES (?,?,?,?,?,?)', (node['id'], ordinal, number, json.dumps(bounds), digest(png), png))
                            fragment_total += 1
                        affected += bool(small)
                    for ordinal, (identifier, printed, before, page, line) in enumerate(markers):
                        db.execute('INSERT INTO recovery_presentation_items VALUES (?,?,?,?,NULL)', (identifier, source['id'], MARKER_NOTICE, '["reserved_marker"]'))
                        db.execute('INSERT INTO recovery_reserved_markers VALUES (?,?,?,?,?,?,?)', (identifier, chapter, printed, before, ordinal, page['page'], f"p{page['page']}-y{line['baseline']:.3f}"))
                        png, bounds = source_fragment(document, page, [line])
                        db.execute('INSERT INTO recovery_source_fragments VALUES (?,?,?,?,?,?)', (identifier, 0, page['page'], json.dumps(bounds), digest(png), png))
                        fragment_total += 1
                finally:
                    document.close()
                marker_total += len(markers)
                formatted_total += affected
                chapters.append({'chapter': chapter, 'source_sha256': entry['sha256'], 'reserved_markers': len(markers), 'small_glyph_nodes': affected})
                print(f'PRESENTATION {chapter}: markers={len(markers)} small_glyph_nodes={affected}', flush=True)
            if marker_total != 37:
                raise ValueError('Reserved marker inventory differs from the reviewed 37 rows')
            if db.execute('SELECT count(*) FROM recovery_presentation_items WHERE spacing_json IS NOT NULL').fetchone()[0] != 10:
                raise ValueError('Missing spacing ledger entry')
            db.execute("INSERT INTO recovery_metadata VALUES ('presentation_schema','1')")
            db.execute("INSERT INTO recovery_metadata VALUES ('presentation_base_sha256',?)", (base_pin,))
        if db.execute('PRAGMA foreign_key_check').fetchall() or db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Presentation candidate integrity failure')
        db.execute('VACUUM')
    temporary.replace(output)
    output.chmod(0o444)
    if digest(base.read_bytes()) != base_pin:
        raise ValueError('Baseline changed during build')
    result = {'sqlite_sha256': digest(output.read_bytes()), 'base_sqlite_sha256': base_pin, 'source_manifest_sha256': manifest_pin, 'spacing_ledger_sha256': digest(spacing_path.read_bytes()), 'chapters': chapters, 'reserved_markers': marker_total, 'small_glyph_nodes': formatted_total, 'source_fragments': fragment_total, 'active_catalog_mutated': False, 'legal_status': 'unverified', 'rates_present': False, 'formatting_policy': 'explicit limitation and original raster fragments; no inferred formula or footnote semantics'}
    output.with_suffix('.manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result
