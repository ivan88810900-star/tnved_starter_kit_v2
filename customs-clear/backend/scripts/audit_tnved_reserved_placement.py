"""Targeted actual SQLite/HTTP N-001 regression, not a repeat PDF audit.

Expectations are frozen separately from the author's responses. Before/after
container replies remain local evidence; they are not the missing Claude log.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.error import HTTPError
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--before', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    expected = json.loads(args.expected.read_text())
    database = args.database.resolve()
    pin = hashlib.sha256(database.read_bytes()).hexdigest()
    assert pin == expected['snapshot_sha256']
    calls = 0

    def get(path):
        nonlocal calls
        calls += 1
        with urlopen(args.url.rstrip('/') + path, timeout=20) as response:
            return response.read()

    def body(path):
        value = json.loads(get(path))
        assert value['snapshot_sha256'] == pin
        return value

    with sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
        db.row_factory = sqlite3.Row
        nav = {r['id']: dict(r) for r in db.execute('SELECT * FROM recovery_navigation')}
        markers = {r['id']: dict(r) for r in db.execute('SELECT * FROM recovery_reserved_markers')}
        fragments = list(db.execute('SELECT node_id,ordinal,png,sha256 FROM recovery_source_fragments'))
        assert len(nav) == 21207 and len(markers) == 37 and len(fragments) == 895
        for row in fragments:
            assert hashlib.sha256(row['png']).hexdigest() == row['sha256']
        assert db.execute("SELECT count(*) FROM recovery_navigation WHERE length(code)=10").fetchone()[0] == 13294
        assert db.execute('SELECT count(*) FROM recovery_heading_aliases').fetchone()[0] == 271
        health = json.loads(get('/api/health/ready'))
        assert health['recovered_catalog']['snapshot_sha256'] == pin
        assert health['recovered_catalog']['reserved_markers'] == 37
        assert not health['recovered_catalog']['rates_present']
        containers = {key: body('/api/tnved/children/' + key)['items'] for key, row in nav.items() if row['kind'] in ('chapter', 'caption')}
        occurrences = Counter(item['node_id'] for rows in containers.values() for item in rows if item['kind'] == 'reserved')
        assert occurrences == Counter({key: 1 for key in markers})
        assert hashlib.sha256(get('/tnved')).hexdigest() == expected['frontend_index_sha256']
        parent_by_marker = {r['node_id']: key for key, rows in containers.items() for r in rows if r['kind'] == 'reserved'}
        active_children = {}
        for key, row in nav.items():
            if row['parent_id']:
                active_children.setdefault(row['parent_id'], []).append(row)
        for rows in active_children.values():
            rows.sort(key=lambda r: r['source_order'])

        def flatten(key):
            children = containers.get(key)
            keys = [r['node_id'] for r in children] if children is not None else [r['id'] for r in active_children.get(key, [])]
            result = []
            for child in keys:
                result.append(child)
                if child in nav:
                    result.extend(flatten(child))
            return result

        flattened = {chapter: flatten(chapter) for chapter in {r['chapter'] for r in markers.values()}}
        cases, cards, mismatches = [], {}, []
        for e in expected['markers']:
            key = e['id']; marker = markers[key]
            assert marker['printed_code'] == e['printed_code'] and marker['before_order'] == e['before_order']
            card = body('/api/v1/tnved/' + key); cards[key] = card
            assert card['code'] == '' and card['kind'] == 'reserved' and card['selectable'] is False and card['children'] == []
            assert card['legal_status'] == 'unverified' and card['rates'] is None
            crumb = body('/api/tnved/breadcrumb/' + key)['breadcrumb']
            assert crumb == card['breadcrumb']
            for r in containers[parent_by_marker[key]]:
                if r['node_id'] == key:
                    assert not r['selectable'] and not r['is_leaf'] and not r['has_children'] and r['code'] == ''
            digits = e['printed_code'][1:-1]
            assert body('/api/v1/tnved/search?q=' + digits)['total'] == 0
            try:
                get('/api/v1/tnved/' + digits)
            except HTTPError as error:
                assert error.code == 404
            else:
                raise AssertionError('Reserved numeric lookup became active')
            for fragment in card['presentation']['fragments']:
                assert hashlib.sha256(get(fragment['url'])).hexdigest() == fragment['sha256']
            flat = flattened[e['chapter']]; index = flat.index(key)
            # Check both adjacent reserved marks and nearest active physical rows.
            previous_mark = next((m['id'] for m in markers.values() if m['printed_code'] == e['previous_printed']), None)
            next_mark = next((m['id'] for m in markers.values() if m['printed_code'] == e['next_printed']), None)
            previous = flat[index - 1] if index else None
            following = flat[index + 1] if index + 1 < len(flat) else None
            matches = parent_by_marker[key] == e['expected_parent'] and crumb[-2]['node_id'] == e['expected_parent'] and card['path'] == e['expected_path']
            matches = matches and previous == (previous_mark or e['previous_physical']) and following == (next_mark or e['next_physical'])
            case = {'marker': e['printed_code'], 'id': key, 'actual_parent': parent_by_marker[key], 'expected_parent': e['expected_parent'], 'breadcrumb_parent': crumb[-2]['node_id'], 'previous': previous, 'next': following, 'correct': matches}
            cases.append(case)
            if not matches:
                mismatches.append(case)
        before = json.loads(args.before.read_text()) if args.before else None
        if before:
            for key, rows in containers.items():
                active = lambda values: [r for r in values if r['kind'] != 'reserved']
                assert active(rows) == active(before['containers'][key]), key
            changed_cards = []
            for key, card in cards.items():
                if card != before['cards'][key]:
                    changed_cards.append(card['printed_code'])
                    assert {k: v for k, v in card.items() if k not in ('path', 'breadcrumb')} == {k: v for k, v in before['cards'][key].items() if k not in ('path', 'breadcrumb')}
            assert len(changed_cards) == 4
            assert not mismatches, mismatches
        else:
            changed_cards = None
            assert len(mismatches) == 4, mismatches
        (args.output / 'container-items-and-cards.json').write_text(json.dumps({'containers': containers, 'cards': cards}, ensure_ascii=False, indent=2) + '\n')
    assert hashlib.sha256(database.read_bytes()).hexdigest() == pin
    report = {'observer': 'A0; not independent Claude', 'scope': 'N001 all37 markers, all chapter/caption child lists; no repeat PDF audit', 'status': 'PASS' if before else 'N001_REPRODUCED', 'snapshot_sha256': pin, 'frontend_index_sha256': expected['frontend_index_sha256'], 'independent_expected_sha256': expected['independent_expected_sha256'], 'markers': cases, 'mismatches': mismatches, 'changed_marker_cards': changed_cards, 'container_count': len(containers), 'HTTP_requests': calls, 'all_markers_appear_once': True, 'all_895_fragment_hashes_unchanged': True, 'active_container_items_unchanged': bool(before), 'active_10_digit_codes': 13294, 'aliases': 271}
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('markers', 'mismatches')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
