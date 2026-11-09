from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import unittest

from fastapi.testclient import TestClient
from app.recovery_main import create_recovery_app
from app.services.tnved_fidelity import NAVIGATION_SCHEMA, SOURCE_TEXT_SCHEMA, printed_code, join_source_lines, source_line_tail
from tests import test_tnved_recovery_http as http_fixture


class FidelityNavigationTests(unittest.TestCase):
    """Synthetic regressions, separate from the actual 96-source HTTP audit."""

    def setUp(self):
        fixture = http_fixture.RecoveryHttpTests()
        fixture.setUp()
        fixture.client.close()
        self.addCleanup(fixture.doCleanups)
        self.database = fixture.database
        self.group_a = "u-" + hashlib.sha256(b"source85:row4").hexdigest()[:24]
        self.group_b = "u-" + hashlib.sha256(b"source85:row7").hexdigest()[:24]
        rows = []
        def add(identifier, code, name, parent, chapter, order, kind="coded"):
            source = "eec-ett-index" if kind in ("section", "chapter") else "source-" + chapter
            rows.append((identifier, code, name, parent, chapter, order, source, None if kind == "section" else 1, "fixture-row-" + str(order), kind, '["Source path"]', printed_code(code) if code else "", ""))
        add("XVI", None, "Машины и оборудование", None, None, 0, "section")
        add("84", "84", "Реакторы ядерные, котлы, оборудование и механические устройства; их части", "XVI", "84", 0, "chapter")
        add("85", "85", "Электрические машины и оборудование", "XVI", "85", 1, "chapter")
        add("8502", "8502", "Генераторы", "85", "85", 0)
        add("850300", "850300", "Части машин 8501 или 8502", "85", "85", 10)
        add("8503001000", "8503001000", "Кольца", "850300", "85", 11)
        add(self.group_a, None, "прочие:", "850300", "85", 12, "codeless")
        add("8503009100", "8503009100", "Чугунные", self.group_a, "85", 13)
        add("8504", "8504", "Трансформаторы", "85", "85", 20)
        add(self.group_b, None, "прочие:", "8504", "85", 21, "codeless")
        add("8504000000", "8504000000", "Аппараты", self.group_b, "85", 22)
        for number in range(1, 51):
            code = "8504" + f"{number:06d}"
            add(code, code, "Synthetic paged row " + str(number), "8504", "85", 30 + number)
        add("I", None, "Живые животные", None, None, 1, "section")
        add("01", "01", "Живые животные", "I", "01", 0, "chapter")
        add("0100000000", "0100000000", "Текстовое упоминание 85", "01", "01", 0)
        with sqlite3.connect(self.database) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript(NAVIGATION_SCHEMA + SOURCE_TEXT_SCHEMA)
            db.executemany("INSERT INTO recovery_navigation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            db.executemany("INSERT INTO recovery_source_text VALUES (?,?,?,?)", [(r[0], r[2], '[]', None if r[9] in ('section', 'chapter') else 2) for r in rows])
            db.execute("INSERT INTO recovery_heading_aliases VALUES (?,?)", ("8503", "850300"))
        self.pin = hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.client = TestClient(create_recovery_app(self.database, self.pin))
        self.addCleanup(self.client.close)

    def test_official_order_title_and_explicit_combined_heading(self):
        group = self.client.get("/api/tnved/children/85").json()["items"]
        self.assertEqual([r["code"] for r in group], ["8502", "850300", "8504"])
        self.assertEqual(group[1]["display_code"], "8503 00")
        card = self.client.get("/api/v1/tnved/8503").json()
        self.assertEqual(card["requested_code"], "8503")
        self.assertEqual(card["code"], "850300")
        self.assertEqual(card["navigation_alias"]["resolved_code"], "850300")
        self.assertEqual(card["navigation_alias"]["printed_code"], "8503 00")
        self.assertIn("Реакторы", self.client.get("/api/v1/tnved/84").json()["name"])
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM recovery_navigation WHERE code='8503'").fetchone()[0], 0)

    def test_repeated_codeless_labels_have_separate_ids_paths_and_children(self):
        for key, child in ((self.group_a, "8503009100"), (self.group_b, "8504000000")):
            row = self.client.get("/api/v1/tnved/" + key).json()
            self.assertEqual(row["code"], "")
            self.assertEqual(row["name"], "прочие:")
            self.assertEqual(row["children"][0]["code"], child)
            self.assertIsNone(row["rates"])
            crumb = self.client.get("/api/tnved/breadcrumb/" + child).json()["breadcrumb"]
            self.assertEqual(crumb[-2]["node_id"], key)
            self.assertTrue(crumb[-2]["is_codeless"])
        self.assertNotEqual(self.group_a, self.group_b)

    def test_numeric_pagination_is_complete_and_excludes_text_mentions(self):
        codes, cursor = [], None
        while True:
            response = self.client.get("/api/v1/tnved/search", params={"q": "85", **({"cursor": cursor} if cursor else {})})
            self.assertEqual(response.status_code, 200)
            page = response.json()
            self.assertEqual(page["mode"], "code_prefix")
            codes.extend(row["code"] for row in page["results"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        self.assertEqual(codes[0], "85")
        self.assertEqual(len(codes), page["total"])
        self.assertEqual(len(codes), len(set(codes)))
        self.assertNotIn("0100000000", codes)
        self.assertGreater(len(codes), 40)
        first = self.client.get("/api/v1/tnved/search", params={"q": "85"}).json()
        last = self.client.get("/api/v1/tnved/search", params={"q": "85", "cursor": first["last_cursor"]}).json()
        self.assertEqual(last["results"][-1]["code"], codes[-1])
        self.assertFalse(last["has_more"])
        self.assertEqual(self.client.get("/api/v1/tnved/search", params={"q": "01", "cursor": first["next_cursor"]}).status_code, 422)

    def test_pin_and_leading_zero_preserved_after_navigation(self):
        card = self.client.get("/api/v1/tnved/0100000000").json()
        self.assertEqual(card["code"], "0100000000")
        self.assertEqual(card["snapshot_sha256"], self.pin)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), self.pin)

    def test_raw_source_and_dash_depth_are_available_without_changing_identity(self):
        card = self.client.get('/api/v1/tnved/8503001000').json()
        self.assertEqual(card['raw_name'], 'Кольца')
        self.assertEqual(card['dash_depth'], 2)
        self.assertEqual(card['kind'], 'coded')
        child = self.client.get('/api/tnved/children/850300').json()['items'][0]
        self.assertEqual(child['dash_depth'], 2)
        self.assertEqual(child['node_id'], '8503001000')


class SourceTextProjectionTests(unittest.TestCase):
    def test_wrapped_compounds_and_split_words_keep_encoded_separators(self):
        def joined(left, right, separator):
            return join_source_lines([{'text': left, 'trailing_space': separator}, {'text': right}])
        self.assertEqual(joined('для научно-', 'исследовательских целей', False), 'для научно-исследовательских целей')
        self.assertEqual(joined('аминогидроксинафталинсульфо-', 'кислоты', True), 'аминогидроксинафталинсульфо-кислоты')
        self.assertEqual(joined("и 4,4'-", 'метилендициклогексилдиизоцианата', False), "и 4,4'-метилендициклогексилдиизоцианата")
        self.assertEqual(joined('метилендициклогексилдиизоци', 'аната в виде раствора', False), 'метилендициклогексилдиизоцианата в виде раствора')
        self.assertEqual(joined('спиро[изобенз', 'офуран-1(3Н)', False), 'спиро[изобензофуран-1(3Н)')
        self.assertEqual(joined('менее', '0,94', True), 'менее 0,94')
        self.assertEqual(joined('без какого-', 'либо покрытия', False), 'без какого-либо покрытия')
        self.assertEqual(joined('неизвестный', 'разрыв', None), 'неизвестный разрыв')

    def test_suspended_hyphen_and_source_dash_are_not_word_joins(self):
        for separator in [True, False, None]:
            self.assertEqual(join_source_lines([{'text':'газо-', 'trailing_space':separator}, {'text':'или дымоанализаторы'}]), 'газо- или дымоанализаторы')
        self.assertEqual(join_source_lines([{'text':'–', 'trailing_space':False}, {'text':'прочие'}]), '– прочие')

    def test_trailing_pdf_space_beyond_ink_is_not_clipped_at_column_boundary(self):
        words = [(392, 100, 400, 113, 'м')]
        chars = [{'x0':392, 'bottom':113, 'height':13, 'text':'м'}, {'x0':400.05, 'bottom':113, 'height':13, 'text':' '}]
        self.assertTrue(source_line_tail(chars,113,words)['trailing_space'])


if __name__ == "__main__":
    unittest.main()
