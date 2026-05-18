"""Тесты разбора хвоста строки товарной позиции (_parse_commodity_tail)."""

import unittest

from app.services.source_sync.pdf_parser import _parse_commodity_tail


class ParseCommodityTailTests(unittest.TestCase):
    def test_nichego_ne_menee_posle_tire(self):
        desc, unit, duty = _parse_commodity_tail("– – – – прочие – 50, но не менее")
        self.assertIn("прочие", desc)
        self.assertEqual(duty, "– 50, но не менее")
        self.assertEqual(unit, "")

    def test_sht_563_ocr(self):
        desc, unit, duty = _parse_commodity_tail("– – – – матки пчелиные шт 563С)")
        self.assertEqual(unit, "шт")
        self.assertEqual(duty, "563")

    def test_stavka_s_zakryvayushchey_skobkoy(self):
        desc, unit, duty = _parse_commodity_tail("– – – прочая – 1053С)")
        self.assertEqual(duty, "– 1053С)")

    def test_sht_pyat_no_ne_menee(self):
        desc, unit, duty = _parse_commodity_tail("– – розы шт 5, но не менее")
        self.assertEqual(duty, "шт 5, но не менее")

    def test_evro_za_kg(self):
        desc, unit, duty = _parse_commodity_tail(
            "– – для производства сидра, навалом, – 0,06 евро за 1 кг"
        )
        self.assertEqual(duty, "– 0,06 евро за 1 кг")

    def test_dollar_ssha(self):
        _, _, duty = _parse_commodity_tail(
            "– – – – – при среднемесячной цене – 171 доллар США"
        )
        self.assertEqual(duty, "– 171 доллар США")


if __name__ == "__main__":
    unittest.main()
