"""Подбор СС/ДС и фильтр ТРОИС."""
from __future__ import annotations

import unittest

from app.services.trois_service import trouis_conflicts_in_text
from app.services.permit_suggest_service import suggest_permits


class TroisConflictsTests(unittest.TestCase):
    def test_detects_samsung(self):
        hits = trouis_conflicts_in_text("Заявитель Samsung Electronics")
        self.assertIn("samsung", hits)

    def test_detects_philips_substring(self):
        hits = trouis_conflicts_in_text("philips lamp")
        self.assertIn("philips", hits)


class SuggestPermitsTests(unittest.IsolatedAsyncioTestCase):
    async def test_kettle_excludes_branded_xiaomi_when_trois_on(self):
        r = await suggest_permits("чайник", exclude_trois=True, country_hint="CN", limit=50)
        ids = [x["id"] for x in r["items"]]
        self.assertIn("ref-kettle-ds-oem", ids)
        self.assertNotIn("ref-kettle-ds-branded-xiaomi", ids)
        self.assertGreaterEqual(r.get("excluded_trois_count", 0), 1)

    async def test_kettle_includes_xiaomi_when_trois_off(self):
        r = await suggest_permits("чайник", exclude_trois=False, country_hint="CN", limit=50)
        ids = [x["id"] for x in r["items"]]
        self.assertIn("ref-kettle-ds-branded-xiaomi", ids)

    async def test_hs_boosts_score(self):
        r = await suggest_permits("", hs_code="8516108008", exclude_trois=True, limit=10)
        self.assertTrue(r["items"])
        first = r["items"][0]
        self.assertIn("8516", "".join(first.get("hs_suggest") or []))

    async def test_public_ru_cert_shown_with_cn_country_hint(self):
        """Публичные примеры СС (страна RU) остаются в выдаче при фильтре КНР."""
        r = await suggest_permits(
            "фара трактор",
            exclude_trois=True,
            country_hint="CN",
            limit=50,
        )
        ids = [x["id"] for x in r["items"]]
        self.assertIn("pub-cert-lights-ru-2024", ids)


if __name__ == "__main__":
    unittest.main()
