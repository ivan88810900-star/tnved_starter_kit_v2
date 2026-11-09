"""Synthetic failure/selection contracts, separate from actual PDF/browser proof."""
import base64
import hashlib
import json
import sqlite3
import unittest

from fastapi.testclient import TestClient
from app.recovery_main import create_recovery_app
from app.services.tnved_presentation import SCHEMA, FORMAT_NOTICE, MARKER_NOTICE
from tests import test_tnved_fidelity as fidelity_fixture


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jQ1sAAAAASUVORK5CYII=')


class PresentationTests(unittest.TestCase):
    def setUp(self):
        fixture = fidelity_fixture.FidelityNavigationTests()
        fixture.setUp()
        fixture.client.close()
        self.addCleanup(fixture.doCleanups)
        self.database = fixture.database
        self.marker = 'u-' + hashlib.sha256(b'fixture-reserved-source').hexdigest()[:24]
        with sqlite3.connect(self.database) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.executescript(SCHEMA)
            difference = {'source_text': 'Кольца', 'display_text': 'Кольца', 'impact': 'Fixture representation only', 'status': 'open_limitation'}
            db.execute('INSERT INTO recovery_presentation_items VALUES (?,?,?,?,?)', ('8503001000', 'source-85', FORMAT_NOTICE, '["source_small_glyphs"]', json.dumps(difference)))
            db.execute('INSERT INTO recovery_presentation_items VALUES (?,?,?,?,NULL)', (self.marker, 'source-85', MARKER_NOTICE, '["reserved_marker"]'))
            db.execute('INSERT INTO recovery_reserved_markers VALUES (?,?,?,?,?,?,?)', (self.marker, '85', '[8599]', 20, 0, 1, 'fixture-marker-row'))
            for key in ('8503001000', self.marker):
                db.execute('INSERT INTO recovery_source_fragments VALUES (?,?,?,?,?,?)', (key, 0, 1, '[90,100,404,120]', hashlib.sha256(PNG).hexdigest(), PNG))
        self.client = self.new_client()
        self.addCleanup(self.client.close)

    def new_client(self):
        self.pin = hashlib.sha256(self.database.read_bytes()).hexdigest()
        return TestClient(create_recovery_app(self.database, self.pin))

    def test_reserved_sequence_does_not_change_active_children(self):
        rows = self.client.get('/api/tnved/children/85').json()['items']
        self.assertEqual([r['node_id'] for r in rows], ['8502', '850300', self.marker, '8504'])
        marker = rows[2]
        self.assertEqual(marker['code'], '')
        self.assertEqual(marker['display_code'], '[8599]')
        self.assertFalse(marker['selectable'])
        self.assertFalse(marker['is_leaf'])
        self.assertFalse(marker['has_children'])
        self.assertIn('Правовой статус', marker['format_notice'])
        self.assertTrue(marker['source_url'].startswith('https://'))
        self.assertEqual(len(marker['source_sha256']), 64)
        self.assertEqual([r['node_id'] for r in self.client.get('/api/tnved/children/850300').json()['items']], ['8503001000', 'u-' + hashlib.sha256(b'source85:row4').hexdigest()[:24]])

    def test_marker_is_not_a_numeric_search_code_or_counted_as_active(self):
        self.assertEqual(self.client.get('/api/v1/tnved/8599').status_code, 404)
        page = self.client.get('/api/v1/tnved/search', params={'q': '85'}).json()
        self.assertNotIn(self.marker, [r['node_id'] for r in page['results']])
        self.assertEqual(self.client.get('/api/v1/tnved/search', params={'q': '8599'}).json()['total'], 0)
        status = self.client.get('/api/health/ready').json()['recovered_catalog']
        self.assertEqual(status['reserved_markers'], 1)
        card = self.client.get('/api/v1/tnved/' + self.marker).json()
        self.assertEqual(card['code'], '')
        self.assertFalse(card['selectable'])
        self.assertEqual(card['kind'], 'reserved')
        self.assertEqual(card['children'], [])

    def test_source_fragment_is_the_exact_pinned_blob_not_generated_by_HTTP(self):
        card = self.client.get('/api/v1/tnved/8503001000').json()
        self.assertEqual(card['name'], 'Кольца')
        self.assertEqual(card['raw_name'], 'Кольца')
        self.assertIn('Значение сносок', card['presentation']['notice'])
        self.assertEqual(card['presentation']['spacing_difference']['status'], 'open_limitation')
        response = self.client.get(card['presentation']['fragments'][0]['url'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PNG)
        self.assertEqual(response.headers['etag'], hashlib.sha256(PNG).hexdigest())
        self.assertEqual(response.headers['x-snapshot-sha256'], self.pin)
        self.assertIn('image/png', response.headers['content-type'])
        self.assertIsNone(card['rates'])
        self.assertEqual(card['legal_status'], 'unverified')

    def test_corrupt_fragment_is_explicit_service_failure(self):
        self.client.close()
        with sqlite3.connect(self.database) as db:
            db.execute('UPDATE recovery_source_fragments SET png=? WHERE node_id=?', (b'changed', '8503001000'))
        with self.new_client() as client:
            response = client.get('/api/v1/tnved/8503001000/source-fragments/0.png')
            self.assertEqual(response.status_code, 503)
            self.assertIn('целостности', response.json()['detail'])

    def test_missing_declared_fragment_is_not_silent_plain_text_success(self):
        self.client.close()
        with sqlite3.connect(self.database) as db:
            db.execute('DELETE FROM recovery_source_fragments WHERE node_id=?', ('8503001000',))
        with self.new_client() as client:
            self.assertEqual(client.get('/api/v1/tnved/8503001000').status_code, 503)

    def test_unknown_fragment_does_not_read_arbitrary_paths(self):
        self.assertEqual(self.client.get('/api/v1/tnved/8503001000/source-fragments/999.png').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/tnved/not-a-code/source-fragments/0.png').status_code, 422)


if __name__ == '__main__':
    unittest.main()
