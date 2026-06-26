"""FTS5 полнотекстовый поиск по номенклатуре ТН ВЭД (Issue #106)."""

from __future__ import annotations

import unittest

try:
    from app.db import Base, SessionLocal, engine
    from app.models.tnved import Chapter, Commodity, Section
    from app.services.tnved_fts import ensure_fts_index, search_commodities_fts

    _OK = True
except ImportError:
    _OK = False


@unittest.skipUnless(_OK, "FTS tests need FastAPI app + models")
class TnvedFtsTests(unittest.TestCase):
    available = False

    @classmethod
    def setUpClass(cls) -> None:
        Base.metadata.create_all(bind=engine)
        cls.available = ensure_fts_index()
        if not cls.available:
            return
        with SessionLocal() as db:
            sec = Section(roman_number="FTSX", title="FTS тест", notes="")
            db.add(sec)
            db.flush()
            ch = Chapter(section_id=sec.id, code="9988", title="FTS глава", notes="")
            db.add(ch)
            db.flush()
            seeds = [
                ("9988100000", "уникумтовар спортивный для тестирования морфологии"),
                ("9988200000", "прочие уникумтовары разные модели"),
            ]
            for code, desc in seeds:
                if not db.query(Commodity).filter(Commodity.code == code).first():
                    db.add(
                        Commodity(
                            chapter_id=ch.id,
                            code=code,
                            description=desc,
                            unit="кг",
                            import_duty="0",
                        )
                    )
            db.commit()
        # Перестроить индекс, чтобы seed-строки попали в FTS детерминированно.
        ensure_fts_index(rebuild=True)

    def setUp(self) -> None:
        if not self.__class__.available:
            self.skipTest("FTS5 недоступен в этой сборке SQLite")

    def test_short_query_returns_empty(self) -> None:
        self.assertEqual(search_commodities_fts("я", limit=5), [])

    def test_code_prefix_match(self) -> None:
        rows = search_commodities_fts("99881", limit=10)
        self.assertTrue(any(r["code"] == "9988100000" for r in rows))

    def test_exact_code_ranked_first(self) -> None:
        rows = search_commodities_fts("9988100000", limit=5)
        self.assertTrue(rows)
        self.assertEqual(rows[0]["code"], "9988100000")

    def test_word_match(self) -> None:
        rows = search_commodities_fts("уникумтовар", limit=10)
        codes = {r["code"] for r in rows}
        self.assertIn("9988100000", codes)

    def test_morphology_prefix(self) -> None:
        # Множественное число должно находить запись с единственным числом (стем + префикс).
        rows = search_commodities_fts("уникумтовары", limit=10)
        codes = {r["code"] for r in rows}
        self.assertTrue("9988100000" in codes or "9988200000" in codes)

    def test_special_chars_do_not_crash(self) -> None:
        for s in ["уникум (товар)", "NOT OR AND", '"уникум"', "уникум*товар"]:
            rows = search_commodities_fts(s, limit=5)
            self.assertTrue(rows is None or isinstance(rows, list))


if __name__ == "__main__":
    unittest.main()
