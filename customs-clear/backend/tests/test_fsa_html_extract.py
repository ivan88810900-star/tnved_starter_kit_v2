"""Парсинг HTML-ответов ФСА (таблица vs SPA-оболочка)."""
from __future__ import annotations

import unittest

from app.services.permits_service import _extract_fsa_from_html, normalize_number


SEARCH_NUMBER = "ЕАЭС RU Д-RU.РА01.А.12345/26"


def _table(*rows: tuple[str, str, str]) -> str:
    body = "".join(
        f"<tr><td>{number}</td><td>{status}</td><td>{valid_to}</td></tr>"
        for number, status, valid_to in rows
    )
    return (
        "<html><body><table>"
        "<tr><th>Регистрационный номер</th><th>Статус</th><th>Действует до</th></tr>"
        f"{body}</table></body></html>"
    )


class FsaHtmlExtractTests(unittest.TestCase):
    def test_unstructured_table_does_not_prove_validity(self):
        html = """<html><body>
        <table><tr><th>A</th></tr><tr><td>cell</td></tr></table>
        </body></html>"""
        r = _extract_fsa_from_html(html, "СС", "ЕАЭС RU С-X")
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertEqual(r["raw"].get("rows_count"), 1)
        self.assertIsNone(r["raw"].get("identity_match"))

    def test_exact_active_number_is_valid(self):
        r = _extract_fsa_from_html(
            _table((SEARCH_NUMBER, "Действует", "31.12.2099")),
            "ДС",
            SEARCH_NUMBER,
        )
        self.assertEqual(r["status"], "VALID")
        self.assertTrue(r["raw"].get("identity_match"))
        self.assertEqual(r["raw"].get("matched_count"), 1)

    def test_other_trustworthy_number_is_not_found(self):
        r = _extract_fsa_from_html(
            _table(("ЕАЭС RU Д-RU.РА01.А.99999/26", "Действует", "31.12.2099")),
            "ДС",
            SEARCH_NUMBER,
        )
        self.assertEqual(r["status"], "NOT_FOUND")
        self.assertFalse(r["raw"].get("identity_match"))

    def test_blank_number_row_keeps_non_match_unknown(self):
        r = _extract_fsa_from_html(
            _table(
                ("ЕАЭС RU Д-RU.РА01.А.99999/26", "Действует", "31.12.2099"),
                ("", "Действует", "31.12.2099"),
            ),
            "ДС",
            SEARCH_NUMBER,
        )
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertIsNone(r["raw"].get("identity_match"))

    def test_exact_number_uses_fail_closed_status(self):
        cases = [
            ("Аннулировано", "31.12.2099", "NOT_FOUND"),
            ("Ожидает проверки", "31.12.2099", "UNKNOWN"),
            ("Действует", "01.01.2001", "NOT_FOUND"),
            ("", "31.12.2099", "UNKNOWN"),
        ]
        for status, valid_to, expected in cases:
            with self.subTest(status=status, valid_to=valid_to):
                r = _extract_fsa_from_html(
                    _table((SEARCH_NUMBER, status, valid_to)),
                    "ДС",
                    SEARCH_NUMBER,
                )
                self.assertEqual(r["status"], expected)

    def test_duplicate_exact_rows_fail_closed_regardless_of_order(self):
        cases = [
            (
                (SEARCH_NUMBER, "Действует", "31.12.2099"),
                (SEARCH_NUMBER, "Аннулировано", "31.12.2099"),
            ),
            (
                (SEARCH_NUMBER, "Аннулировано", "31.12.2099"),
                (SEARCH_NUMBER, "Действует", "31.12.2099"),
            ),
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                r = _extract_fsa_from_html(_table(*rows), "ДС", SEARCH_NUMBER)
                self.assertEqual(r["status"], "NOT_FOUND")
                self.assertEqual(r["raw"].get("matched_count"), 2)

    def test_missing_expiry_header_is_unknown(self):
        html = f"""<html><body><table>
        <tr><th>Регистрационный номер</th><th>Статус</th></tr>
        <tr><td>{SEARCH_NUMBER}</td><td>Действует</td></tr>
        </table></body></html>"""
        r = _extract_fsa_from_html(html, "ДС", SEARCH_NUMBER)
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertIsNone(r["raw"].get("identity_match"))
        self.assertEqual(r["raw"].get("incomplete_rows_count"), 1)

    def test_missing_expiry_cell_is_unknown(self):
        html = f"""<html><body><table>
        <tr><th>Регистрационный номер</th><th>Статус</th><th>Действует до</th></tr>
        <tr><td>{SEARCH_NUMBER}</td><td>Действует</td></tr>
        </table></body></html>"""
        r = _extract_fsa_from_html(html, "ДС", SEARCH_NUMBER)
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertIsNone(r["raw"].get("identity_match"))

    def test_rowspan_does_not_shift_status_into_false_valid(self):
        html = f"""<html><body><table>
        <tr><th>Регистрационный номер</th><th>Статус</th><th>Действует до</th></tr>
        <tr><td rowspan="2">{SEARCH_NUMBER}</td><td>Действует</td><td>31.12.2099</td></tr>
        <tr><td>Аннулировано</td><td>31.12.2099</td></tr>
        </table></body></html>"""
        r = _extract_fsa_from_html(html, "ДС", SEARCH_NUMBER)
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertIsNone(r["raw"].get("identity_match"))
        self.assertEqual(r["raw"].get("incomplete_rows_count"), 2)

    def test_misleading_metadata_table_cannot_mask_revoked_record(self):
        html = f"""<html><body>
        <table>
          <tr><th>Регистрационный номер запроса</th><th>Статус запроса</th><th>Действует до</th></tr>
          <tr><td>{SEARCH_NUMBER}</td><td>Действует</td><td>31.12.2099</td></tr>
        </table>
        <table>
          <tr><th>Регистрационный номер</th><th>Статус</th><th>Действует до</th></tr>
          <tr><td>{SEARCH_NUMBER}</td><td>Аннулировано</td><td>31.12.2099</td></tr>
        </table>
        </body></html>"""
        r = _extract_fsa_from_html(html, "ДС", SEARCH_NUMBER)
        self.assertEqual(r["status"], "NOT_FOUND")
        self.assertTrue(r["raw"].get("identity_match"))
        self.assertEqual(r["raw"].get("matched_count"), 1)

    def test_misleading_metadata_table_alone_is_unknown(self):
        html = f"""<html><body><table>
        <tr><th>Регистрационный номер запроса</th><th>Статус запроса</th><th>Действует до</th></tr>
        <tr><td>{SEARCH_NUMBER}</td><td>Действует</td><td>31.12.2099</td></tr>
        </table></body></html>"""
        r = _extract_fsa_from_html(html, "ДС", SEARCH_NUMBER)
        self.assertEqual(r["status"], "UNKNOWN")

    def test_colspan_ambiguity_is_unknown(self):
        html = f"""<html><body><table>
        <tr><th>Регистрационный номер</th><th>Статус</th><th>Действует до</th></tr>
        <tr><td>{SEARCH_NUMBER}</td><td colspan="2">Действует 31.12.2099</td></tr>
        </table></body></html>"""
        r = _extract_fsa_from_html(html, "ДС", SEARCH_NUMBER)
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertIsNone(r["raw"].get("identity_match"))

    def test_help_not_found_text_does_not_preempt_exact_active_record(self):
        html = _table((SEARCH_NUMBER, "Действует", "31.12.2099")).replace(
            "<body>", "<body><aside>Если записей не найдено, уточните запрос.</aside>"
        )
        r = _extract_fsa_from_html(html, "ДС", SEARCH_NUMBER)
        self.assertEqual(r["status"], "VALID")
        self.assertTrue(r["raw"].get("identity_match"))
        self.assertEqual(r["raw"].get("candidate_numbers"), [normalize_number(SEARCH_NUMBER)])

    def test_incomplete_result_row_downgrades_exact_active_match(self):
        html = f"""<html><body><table>
        <tr><th>Регистрационный номер</th><th>Статус</th><th>Действует до</th></tr>
        <tr><td>{SEARCH_NUMBER}</td><td>Действует</td><td>31.12.2099</td></tr>
        <tr><td></td><td>Действует</td><td>31.12.2099</td></tr>
        </table></body></html>"""
        r = _extract_fsa_from_html(html, "ДС", SEARCH_NUMBER)
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertTrue(r["raw"].get("identity_match"))
        self.assertEqual(r["raw"].get("incomplete_rows_count"), 1)

    def test_ambiguous_second_table_downgrades_active_match(self):
        html = _table((SEARCH_NUMBER, "Действует", "31.12.2099")).replace(
            "</body></html>",
            f"""<table>
            <tr><th colspan="2">Регистрационный номер</th><th>Статус</th><th>Действует до</th></tr>
            <tr><td>{SEARCH_NUMBER}</td><td>Аннулировано</td><td>31.12.2099</td></tr>
            </table></body></html>""",
        )
        r = _extract_fsa_from_html(html, "ДС", SEARCH_NUMBER)
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertTrue(r["raw"].get("identity_match"))
        self.assertEqual(r["raw"].get("incomplete_rows_count"), 1)

    def test_organization_number_header_cannot_prove_identity(self):
        html = f"""<html><body><table>
        <tr><th>Регистрационный номер организации</th><th>Статус</th><th>Действует до</th></tr>
        <tr><td>{SEARCH_NUMBER}</td><td>Действует</td><td>31.12.2099</td></tr>
        </table></body></html>"""
        r = _extract_fsa_from_html(html, "ДС", SEARCH_NUMBER)
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertIsNone(r["raw"].get("identity_match"))

    def test_unparseable_expiry_cannot_prove_active_record(self):
        r = _extract_fsa_from_html(
            _table((SEARCH_NUMBER, "Действует", "не указано")),
            "ДС",
            SEARCH_NUMBER,
        )
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertTrue(r["raw"].get("identity_match"))

    def test_metadata_table_does_not_downgrade_complete_active_record(self):
        html = f"""<html><body>
        <table>
          <tr><th>Регистрационный номер запроса</th><th>Статус запроса</th></tr>
          <tr><td>{SEARCH_NUMBER}</td><td>Выполнен</td></tr>
        </table>
        <table>
          <tr><th>Регистрационный номер</th><th>Статус</th><th>Действует до</th></tr>
          <tr><td>{SEARCH_NUMBER}</td><td>Действует</td><td>31.12.2099</td></tr>
        </table>
        </body></html>"""
        r = _extract_fsa_from_html(html, "ДС", SEARCH_NUMBER)
        self.assertEqual(r["status"], "VALID")
        self.assertTrue(r["raw"].get("identity_match"))
        self.assertEqual(r["raw"].get("incomplete_rows_count"), 0)

    def test_not_found_phrase(self):
        html = "<html><body><p>Ничего не найдено по запросу</p></body></html>"
        r = _extract_fsa_from_html(html, "ДС", "X")
        self.assertEqual(r["status"], "NOT_FOUND")

    def test_spa_shell_marks_note(self):
        html = """<!doctype html><html lang="ru" data-critters-container>
        <head><title>ФГИС</title></head><body><p>Загрузка</p></body></html>"""
        r = _extract_fsa_from_html(html, "СС", "ЕАЭСRUС-TEST")
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertTrue((r.get("raw") or {}).get("spa_shell"))
        self.assertIn("браузере", (r.get("raw") or {}).get("note", ""))


if __name__ == "__main__":
    unittest.main()
