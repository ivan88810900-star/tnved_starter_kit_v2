"""Audit unchanged active rows and actual SQLite -> HTTP presentation bytes.

This is A0 verification, not an independent Claude observation. No DB is mutated.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def connect(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    return db


def audit_roots(client, nav, children, pin):
    response = client.get('/api/tnved/children')
    assert response.status_code == 200
    body = response.json()
    assert body['snapshot_sha256'] == pin
    expected = sorted([r for r in nav.values() if r['kind'] == 'section'], key=lambda r: r['source_order'])
    assert [r['node_id'] for r in body['items']] == [r['id'] for r in expected]
    for section in expected:
        response = client.get('/api/tnved/children/' + section['id'])
        assert response.status_code == 200
        body = response.json()
        assert body['snapshot_sha256'] == pin
        assert [r['node_id'] for r in body['items']] == [r['id'] for r in children[section['id']]]
        assert [r['name'] for r in body['items']] == [r['label'] for r in children[section['id']]]
    return len(expected) + 1


def audit(base, candidate, url, output, registry=None, glyph_findings=None):
    import httpx
    output.mkdir(parents=True, exist_ok=True)
    pin = sha(candidate.read_bytes())
    with closing(connect(base)) as old, closing(connect(candidate)) as db:
        tables = [r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        unchanged = {}
        for table in tables:
            columns = [r[1] for r in old.execute('PRAGMA table_info(' + table + ')')]
            order = ','.join('"' + c + '"' for c in columns)
            a = [tuple(r) for r in old.execute('SELECT * FROM ' + table + ' ORDER BY ' + order)]
            b = [tuple(r) for r in db.execute('SELECT * FROM ' + table + ' ORDER BY ' + order)]
            if table == 'recovery_metadata':
                b = [r for r in b if not r[0].startswith('presentation_')]
            assert a == b, 'Active baseline table changed: ' + table
            unchanged[table] = len(a)
        nav = {r['id']: dict(r) for r in db.execute('SELECT * FROM recovery_navigation')}
        markers = [dict(r) for r in db.execute('SELECT * FROM recovery_reserved_markers ORDER BY chapter,before_order,marker_order')]
        formats = {r['node_id']: dict(r) for r in db.execute('SELECT * FROM recovery_presentation_items')}
        fragments = {(r['node_id'], r['ordinal']): {'page': r['page'], 'sha256': r['sha256'], 'bytes': len(r['png'])} for r in db.execute('SELECT * FROM recovery_source_fragments') if sha(r['png']) == r['sha256']}
        assert len(markers) == 37
        assert len(fragments) == db.execute('SELECT count(*) FROM recovery_source_fragments').fetchone()[0]
        ledger = {key: json.loads(r['spacing_json']) for key, r in formats.items() if r['spacing_json']}
        assert len(ledger) == 10 and all(r['status'] == 'open_limitation' for r in ledger.values())
        assert all(nav[key]['label'] == r['display_text'] for key, r in ledger.items())
        small = {key for key, r in formats.items() if 'source_small_glyphs' in json.loads(r['reasons_json'])}
        if glyph_findings:
            assert small == {r['node_id'] for r in json.loads(glyph_findings.read_text())}, 'Small-glyph identities differ, not just counts'
        if registry:
            reserved = []
            registry_rows = {}
            for chapter in sorted({r['chapter'] for r in markers}):
                rows = [json.loads(line) for line in (registry / f'registry-current-{chapter}.jsonl').read_text().splitlines()]
                registry_rows[chapter] = rows
                reserved += [r for r in rows if r['kind'] == 'reserved']
            assert len(reserved) == len(markers)
            for actual, source in zip(markers, reserved):
                rows = registry_rows[actual['chapter']]
                assert (actual['chapter'], actual['printed_code'], actual['page']) == (source['chapter'], source['printed_code'], source['page'])
                source_meta = db.execute('SELECT s.sha256 FROM recovery_presentation_items p JOIN recovery_sources s ON s.id=p.source_id WHERE p.node_id=?', (actual['id'],)).fetchone()[0]
                assert source_meta == source['source_sha256']
                # First following physical active row determines the insertion
                # point; preserve the relative order of consecutive markers.
                after = [r for r in rows if r['physical_order'] > source['physical_order'] and r['kind'] in ('coded', 'codeless', 'caption')]
                first = after[0] if after else None
                expected_nodes = sorted([n for n in nav.values() if n['chapter'] == actual['chapter'] and n['kind'] not in ('chapter', 'section')], key=lambda n: n['source_order'])
                if first:
                    expected = expected_nodes[actual['before_order']]
                    assert expected['page'] == first['page']
                    assert (expected['code'] or '') == (first['printed_code'].replace(' ', '') if first['kind'] == 'coded' else '')
        sources = {r['id']: dict(r) for r in db.execute('SELECT * FROM recovery_sources')}
        aliases = [tuple(r) for r in db.execute('SELECT heading_code,node_id FROM recovery_heading_aliases')]
    children = {}
    for row in nav.values():
        children.setdefault(row['parent_id'], []).append(row)
    for values in children.values():
        values.sort(key=lambda r: r['source_order'])

    def group(chapter):
        requests, image_requests, differences = 0, 0, []
        with httpx.Client(base_url=url, timeout=30, trust_env=False) as client:
            def get(path, params=None):
                nonlocal requests
                requests += 1
                response = client.get(path, params=params)
                assert response.status_code == 200, (path, response.status_code)
                body = response.json()
                assert body['snapshot_sha256'] == pin
                return body
            own = sorted([r for r in nav.values() if r['chapter'] == chapter and r['kind'] != 'section'], key=lambda r: -1 if r['kind'] == 'chapter' else r['source_order'])
            for row in own:
                items = get('/api/tnved/children/' + row['id'])['items']
                assert [r['node_id'] for r in items if r['kind'] != 'reserved'] == [r['id'] for r in children.get(row['id'], [])]
                if row['kind'] == 'chapter':
                    expected = [(r['source_order'], 1, 0, r['id']) for r in children.get(chapter, [])] + [(r['before_order'], 0, r['marker_order'], r['id']) for r in markers if r['chapter'] == chapter]
                    assert [r['node_id'] for r in items] == [r[-1] for r in sorted(expected)]
                    for r in items:
                        if r['kind'] == 'reserved':
                            assert r['code'] == '' and r['selectable'] is False and not r['has_children'] and not r['is_leaf']
                detail = get('/api/v1/tnved/' + row['id'])
                assert detail['name'] == row['label'] and detail['path'] == json.loads(row['path_json'])
                assert detail['source_sha256'] == sources[row['source_id']]['sha256']
                assert detail['rates'] is None and detail['legal_status'] == 'unverified' and detail['complete'] is False
                chain, parent = [row['id']], row['parent_id']
                while parent:
                    chain.insert(0, parent)
                    parent = nav[parent]['parent_id']
                assert [r['node_id'] for r in detail['breadcrumb']] == chain
                if row['id'] in formats:
                    assert detail['presentation']['spacing_difference'] == ledger.get(row['id'])
                    assert detail['presentation']['notice']
                    for f in detail['presentation']['fragments']:
                        ordinal = int(f['url'].split('/')[-1].split('.')[0])
                        key = (row['id'], ordinal)
                        response = client.get(f['url']); image_requests += 1
                        assert response.status_code == 200 and sha(response.content) == fragments[key]['sha256'] == f['sha256']
                        assert response.headers['x-snapshot-sha256'] == pin and response.headers['x-source-sha256'] == detail['source_sha256']
            expected_codes = [r['code'] for r in own if r['code']]
            actual_codes, cursor = [], None
            while True:
                page = get('/api/v1/tnved/search', {'q': chapter, **({'cursor': cursor} if cursor else {})})
                actual_codes.extend(r['code'] for r in page['results'])
                cursor = page['next_cursor']
                if not cursor:
                    break
            assert actual_codes == expected_codes and page['total'] == len(expected_codes)
            for alias, target in aliases:
                if alias.startswith(chapter):
                    assert get('/api/v1/tnved/' + alias)['code'] == nav[target]['code']
            for marker in [r for r in markers if r['chapter'] == chapter]:
                detail = get('/api/v1/tnved/' + marker['id'])
                assert detail['code'] == '' and detail['selectable'] is False and detail['children'] == []
                assert client.get('/api/v1/tnved/' + marker['printed_code'][1:-1]).status_code == 404
                requests += 1
                for f in detail['presentation']['fragments']:
                    response = client.get(f['url']); image_requests += 1
                    assert response.status_code == 200 and sha(response.content) == f['sha256']
        print(f'PRESENTATION_HTTP {chapter}: nodes={len(own)} requests={requests} images={image_requests} PASS', flush=True)
        return {'chapter': chapter, 'active_navigation_nodes': len(own), 'JSON_requests': requests, 'image_requests': image_requests, 'differences': differences}

    with ThreadPoolExecutor(max_workers=4) as pool:
        groups = list(pool.map(group, [f'{i:02}' for i in range(1, 98) if i != 77]))
    with httpx.Client(base_url=url, trust_env=False) as client:
        root_requests = audit_roots(client, nav, children, pin)
        health = client.get('/api/health/ready').json()['recovered_catalog']
        assert health['snapshot_sha256'] == pin and health['reserved_markers'] == 37 and health['navigation_nodes'] == len(nav)
        assert health['legal_status'] == 'unverified' and health['rates_present'] is False
        index_sha = sha(client.get('/tnved').content)
    report = {'status': 'PASS', 'observer': 'A0; not independent Claude', 'snapshot_sha256': pin, 'base_sha256': sha(base.read_bytes()), 'unchanged_active_tables': unchanged,
              'small_glyph_nodes': len(small), 'small_glyph_identity_crosscheck': bool(glyph_findings), 'reserved_physical_registry_crosscheck': bool(registry),
              'markers': len(markers), 'spacing_distinctions': 10, 'spacing_status': 'open_limitation', 'fragments': len(fragments), 'groups': groups,
              'root_JSON_requests': root_requests,
              'frontend_index_sha256': index_sha, 'legal_status': 'unverified', 'rates_present': False}
    (output / 'HTTP-SQLite-96.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('base', 'candidate', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--url', required=True)
    p.add_argument('--registry', type=Path)
    p.add_argument('--glyph-findings', type=Path)
    a = p.parse_args()
    audit(a.base, a.candidate, a.url, a.output, a.registry, a.glyph_findings)
