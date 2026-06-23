"""Тесты парсеров официальных opendata (фикстуры из реальных снимков)."""

from __future__ import annotations

import unittest

from app.services.opendata_client import parse_fts_meta_csv, parse_fsa_meta_xml, snapshot_date_from_id
from app.services.opendata_trois import _parse_trois_csv


TROIS_SAMPLE = '''REGNOM;G31_12;NOTE;NPRAVO;DPRAVO;NAME;INN;KPP;NAMEL;ADDRESS;ADDRESSL;ADDRESSU;MKTU;NAMET;NAMETB;DATEEND;COMM;COMMB;PARTICIPID
"00257/00062-074/ТЗ-221104";"СМОРОДИНКА";"Срок истек";"";"";"ОАО <РОТ ФРОНТ>";"";"";"";"";"";"";"30";"Кондитерские изделия";"";"2012.11.21";"";"";""
'''

FSA_META_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<meta>
  <identifier>7736638268-rss</identifier>
  <title>Сведения из Реестра сертификатов соответствия</title>
  <modified>31.05.2026</modified>
  <format>7Z</format>
  <data>
    <dataversion>
      <source>https://fsa.gov.ru/opendata/7736638268-rss/data-20260430-structure-20260604.7z </source>
      <structure>https://fsa.gov.ru/opendata/7736638268-rss/structure-20190917.csv </structure>
    </dataversion>
  </data>
</meta>
"""

FTS_META_SAMPLE = """property,value
identifier,7730176610-trois
modified,20260620
format,CSV
data-20260620T0000-structure-20150409T0000.csv,https://customs.gov.ru/storage/opendata/7730176610-trois/data-20260620T0000-structure-20150409T0000.csv
"""


class OpendataParserTests(unittest.TestCase):
    def test_parse_trois_csv(self) -> None:
        rows = _parse_trois_csv(TROIS_SAMPLE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reg_number"], "00257/00062-074/ТЗ-221104")
        self.assertEqual(rows[0]["trademark"], "СМОРОДИНКА")
        self.assertIn("РОТ ФРОНТ", rows[0]["right_holder"])

    def test_parse_fts_meta(self) -> None:
        meta = parse_fts_meta_csv(FTS_META_SAMPLE)
        self.assertEqual(meta.identifier, "7730176610-trois")
        self.assertEqual(len(meta.versions), 1)
        self.assertIn("20260620", meta.versions[0].snapshot_id)

    def test_parse_fsa_meta_xml(self) -> None:
        meta = parse_fsa_meta_xml(FSA_META_SAMPLE)
        self.assertEqual(meta.identifier, "7736638268-rss")
        self.assertEqual(meta.data_format, "7Z")
        self.assertTrue(meta.versions[0].url.endswith(".7z"))

    def test_snapshot_date(self) -> None:
        self.assertEqual(snapshot_date_from_id("data-20260620T0000-structure-20150409T0000.csv"), "20.06.2026")


if __name__ == "__main__":
    unittest.main()
