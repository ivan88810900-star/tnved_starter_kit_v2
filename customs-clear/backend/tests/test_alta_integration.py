"""Tests for Alta-Soft XML helpers (no live HTTP)."""
from __future__ import annotations

import unittest

from app.services.alta_common import apu_request_secret, tik_request_secret
from app.services.alta_xml import parse_apu_codes, parse_apu_suggest, parse_tik_list


class TestAltaSecrets(unittest.TestCase):
    def test_tik_secret_wiki_example(self) -> None:
        # wiki: srchstr zerno, testlogin / testpassword
        self.assertEqual(
            tik_request_secret("зерно", "testlogin", "testpassword"),
            "557272e59fce7d51f7d550301eb5753f",
        )

    def test_apu_secret_wiki_example(self) -> None:
        self.assertEqual(
            apu_request_secret("112675973", "testlogin", "testpassword"),
            "8d43448578371c8a247c82223014e9a0",
        )


class TestAltaXmlParse(unittest.TestCase):
    def test_parse_tik_error(self) -> None:
        xml = """<?xml version="1.0" encoding="utf-8"?>
<Error><ErrorCode>100</ErrorCode><ErrorDescr>Не авторизирован</ErrorDescr></Error>"""
        d = parse_tik_list(xml)
        self.assertEqual(d["status"], "ERROR")
        self.assertEqual(d["error_code"], "100")

    def test_parse_tik_list(self) -> None:
        xml = """<?xml version="1.0" encoding="utf-8"?>
<TikList>
  <TikInfo>
    <Code>1234567890</Code>
    <Count>2</Count>
    <Notes>
      <Note><Name>First</Name></Note>
      <Note><Name>Second</Name></Note>
    </Notes>
  </TikInfo>
</TikList>"""
        d = parse_tik_list(xml)
        self.assertEqual(d["status"], "OK")
        self.assertEqual(len(d["items"]), 1)
        self.assertEqual(d["items"][0]["code"], "1234567890")
        self.assertEqual(d["items"][0]["count"], 2)
        self.assertEqual(len(d["items"][0]["notes"]), 2)

    def test_parse_apu_suggest(self) -> None:
        xml = """<?xml version="1.0" encoding="utf-8"?>
<result>
  <line><term>a</term><tngroup>1,2</tngroup><payload>99</payload><weight>10</weight></line>
</result>"""
        d = parse_apu_suggest(xml)
        self.assertEqual(d["status"], "OK")
        self.assertEqual(d["lines"][0]["payload"], "99")

    def test_parse_apu_codes(self) -> None:
        xml = """<?xml version="1.0" encoding="utf-8"?>
<result>
  <line>
    <tnved>8202100000</tnved>
    <weight>100</weight>
    <descr>d</descr>
    <descr_sh>ds</descr_sh>
    <tncode>8202 10 000 0</tncode>
  </line>
</result>"""
        d = parse_apu_codes(xml)
        self.assertEqual(d["status"], "OK")
        self.assertEqual(d["lines"][0]["tnved"], "8202100000")
        self.assertEqual(d["lines"][0]["weight"], 100)


if __name__ == "__main__":
    unittest.main()
