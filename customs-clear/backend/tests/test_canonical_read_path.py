"""TASK-CANONICAL-004 — canonical read-path для /children за feature flag.

Покрывает:
- флаги по умолчанию OFF и их парсинг (request-time);
- provider/cache: build-once под локом, инвалидация ревизии при изменении
  входов (hs_rates leaf-relevant), сброс, fallback (None) при сбое сборки;
- /children: OFF = legacy, ON = canonical structure, JSON-контракт неизменен,
  parity ON==OFF на seeded-данных, leaf → [], fallback на legacy при сбое
  canonical;
- shadow: ответ не меняется, mismatch логируется.

Замечание про данные: полноценная parity на боевом справочнике ТН ВЭД требует
наполненной БД. Здесь используются собственные seeded-фикстуры (аналогично
существующему test_tnved_catalog_api), поэтому parity проверяется на них, а не на
полном дереве.
"""

from __future__ import annotations

import os
import unittest

try:
    from fastapi.testclient import TestClient

    import app.api.tnved_catalog as catalog
    from app.db import SessionLocal
    from app.main import app
    from app.models.core import HsRate
    from app.models.tnved import Chapter, Commodity, Section
    from app.services.normative_store import init_db
    from app.services import tree_engine
    from app.services.tree_engine import (
        CanonicalModel,
        compare_children,
        flags,
        get_provider,
        provider as provider_mod,
        reset_canonical_provider,
    )

    _OK = True
except ImportError:  # pragma: no cover
    _OK = False


_ENABLED = flags.CANONICAL_TREE_ENABLED_ENV if _OK else "CANONICAL_TREE_ENABLED"
_SHADOW = flags.CANONICAL_TREE_SHADOW_ENV if _OK else "CANONICAL_TREE_SHADOW"


def _clear_flags() -> None:
    for name in (_ENABLED, _SHADOW):
        os.environ.pop(name, None)


# ---------------------------------------------------------------------------
# 1. Feature flags
# ---------------------------------------------------------------------------


@unittest.skipUnless(_OK, "canonical read-path tests need FastAPI app deps")
class CanonicalFlagsTests(unittest.TestCase):
    def setUp(self) -> None:
        _clear_flags()

    def tearDown(self) -> None:
        _clear_flags()

    def test_flags_default_off(self) -> None:
        self.assertFalse(flags.is_canonical_tree_enabled())
        self.assertFalse(flags.is_canonical_tree_shadow_enabled())

    def test_enabled_truthy_values(self) -> None:
        for val in ("1", "true", "TRUE", "yes", "on"):
            os.environ[_ENABLED] = val
            self.assertTrue(flags.is_canonical_tree_enabled(), msg=val)

    def test_enabled_falsy_values(self) -> None:
        for val in ("0", "false", "no", "off", "", "  "):
            os.environ[_ENABLED] = val
            self.assertFalse(flags.is_canonical_tree_enabled(), msg=repr(val))

    def test_shadow_independent_of_enabled(self) -> None:
        os.environ[_SHADOW] = "1"
        self.assertTrue(flags.is_canonical_tree_shadow_enabled())
        self.assertFalse(flags.is_canonical_tree_enabled())

    def test_flags_read_request_time(self) -> None:
        """Изменение env видно немедленно (без рестарта/кэша значения флага)."""
        self.assertFalse(flags.is_canonical_tree_enabled())
        os.environ[_ENABLED] = "1"
        self.assertTrue(flags.is_canonical_tree_enabled())
        os.environ[_ENABLED] = "0"
        self.assertFalse(flags.is_canonical_tree_enabled())


# ---------------------------------------------------------------------------
# 2. Provider / cache
# ---------------------------------------------------------------------------


@unittest.skipUnless(_OK, "canonical read-path tests need FastAPI app deps")
class CanonicalProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        reset_canonical_provider()

    def tearDown(self) -> None:
        reset_canonical_provider()

    def test_get_model_returns_canonical_model(self) -> None:
        model = tree_engine.get_canonical_model()
        self.assertIsInstance(model, CanonicalModel)

    def test_build_once_under_stable_revision(self) -> None:
        prov = get_provider()
        before = prov.build_count
        m1 = prov.get_model()
        m2 = prov.get_model()
        self.assertIsNotNone(m1)
        self.assertIs(m1, m2, "вторая выборка должна вернуть тот же кэш")
        self.assertEqual(prov.build_count, before + 1, "модель должна собираться один раз")

    def test_revision_changes_when_hs_rates_leaf_input_changes(self) -> None:
        prov = get_provider()
        rev0 = prov._compute_revision(SessionLocal)
        code = "9950990000"  # оканчивается на 0000 → влияет на leaf_flags
        with SessionLocal() as db:
            db.add(HsRate(hs_code=code, hs_prefix="9950", duty_rate="0", vat_import_rate=22.0))
            db.commit()
        try:
            rev1 = prov._compute_revision(SessionLocal)
            self.assertNotEqual(rev0, rev1, "revision должен меняться при новом leaf-relevant hs_rate")
        finally:
            with SessionLocal() as db:
                db.query(HsRate).filter(HsRate.hs_code == code).delete()
                db.commit()
        rev2 = prov._compute_revision(SessionLocal)
        self.assertEqual(rev0, rev2, "revision должен вернуться к исходному после отката")

    def test_revision_change_triggers_rebuild(self) -> None:
        prov = get_provider()
        prov.get_model()
        builds_after_first = prov.build_count
        code = "9951990000"
        with SessionLocal() as db:
            db.add(HsRate(hs_code=code, hs_prefix="9951", duty_rate="0", vat_import_rate=22.0))
            db.commit()
        try:
            prov.get_model()
            self.assertEqual(
                prov.build_count,
                builds_after_first + 1,
                "смена revision должна вызвать ровно одну пересборку",
            )
        finally:
            with SessionLocal() as db:
                db.query(HsRate).filter(HsRate.hs_code == code).delete()
                db.commit()

    def test_build_failure_returns_none(self) -> None:
        """Сбой сборки → None (fallback legacy), без исключения наружу."""
        prov = provider_mod.CanonicalTreeProvider()

        def _boom(session_factory):  # noqa: ANN001
            raise RuntimeError("forced build failure")

        prov._build = _boom  # type: ignore[assignment]
        self.assertIsNone(prov.get_model())

    def test_revision_failure_returns_none(self) -> None:
        prov = provider_mod.CanonicalTreeProvider()

        def _boom(session_factory):  # noqa: ANN001
            raise RuntimeError("forced revision failure")

        prov._compute_revision = _boom  # type: ignore[assignment]
        self.assertIsNone(prov.get_model())


# ---------------------------------------------------------------------------
# 3. /children read-path (OFF/ON/shadow) на seeded-фикстурах
# ---------------------------------------------------------------------------


@unittest.skipUnless(_OK, "canonical read-path tests need FastAPI app deps")
class CanonicalChildrenReadPathTests(unittest.TestCase):
    _section_id: int | None = None

    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)
        with SessionLocal() as db:
            # Синтетическая глава 99 (в реальной номенклатуре ТН ВЭД отсутствует),
            # чтобы фикстуры не конфликтовали с наполненной БД.
            sec = Section(roman_number="TSX", title="Canonical test section", notes="")
            db.add(sec)
            db.flush()
            ch = Chapter(section_id=sec.id, code="99", title="Canonical test chapter", notes="")
            db.add(ch)
            db.flush()
            rows = [
                # heading 9971: две прямые 10-значные позиции (не *0000 → всегда leaf)
                ("9971", "Позиция 9971"),
                ("9971110001", "– товар A"),
                ("9971190002", "– товар B"),
                # heading 9972: одиночный L6 *0000 без hs_rate → codeless + synthetic leaf
                ("9972", "Позиция 9972"),
                ("9972130000", "– – одиночная субпозиция"),
                # heading 9973: L6 с двумя L8-детьми (codeless заголовок с детьми)
                ("9973", "Позиция 9973"),
                ("9973110001", "– – – товар C"),
                ("9973110002", "– – – товар D"),
            ]
            for code, desc in rows:
                db.add(Commodity(chapter_id=ch.id, code=code, description=desc, unit="", import_duty=""))
            db.commit()
            cls._section_id = sec.id

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._section_id is None:
            return
        with SessionLocal() as db:
            ch_ids = [r[0] for r in db.query(Chapter.id).filter(Chapter.section_id == cls._section_id).all()]
            for cid in ch_ids:
                db.query(Commodity).filter(Commodity.chapter_id == cid).delete()
            db.query(Chapter).filter(Chapter.section_id == cls._section_id).delete()
            db.query(Section).filter(Section.id == cls._section_id).delete()
            db.commit()

    def setUp(self) -> None:
        _clear_flags()
        reset_canonical_provider()

    def tearDown(self) -> None:
        _clear_flags()
        reset_canonical_provider()

    def _children(self, code: str, depth: str = "direct") -> dict:
        r = self.client.get(f"/api/v1/tnved/children/{code}?depth={depth}")
        self.assertEqual(r.status_code, 200, msg=r.text)
        return r.json()

    # -- OFF path (legacy) -------------------------------------------------

    def test_off_path_returns_headings_for_chapter(self) -> None:
        body = self._children("99")
        codes = {i.get("code") for i in body.get("items") or []}
        self.assertIn("9971", codes)
        self.assertIn("9972", codes)
        self.assertIn("9973", codes)

    def test_off_path_leaf_returns_empty(self) -> None:
        body = self._children("9971110001")
        self.assertEqual(body.get("items") or [], [])

    # -- ON path parity with OFF ------------------------------------------

    def _assert_on_equals_off(self, code: str, depth: str = "direct") -> None:
        _clear_flags()
        reset_canonical_provider()
        off = self._children(code, depth)
        os.environ[_ENABLED] = "1"
        reset_canonical_provider()
        on = self._children(code, depth)
        self.assertEqual(on, off, msg=f"ON != OFF для code={code!r} depth={depth}")

    def test_on_equals_off_chapter(self) -> None:
        self._assert_on_equals_off("99")

    def test_on_equals_off_headings(self) -> None:
        for code in ("9971", "9972", "9973"):
            self._assert_on_equals_off(code)

    def test_on_equals_off_all_depth(self) -> None:
        self._assert_on_equals_off("99", depth="all")

    def test_on_leaf_returns_empty(self) -> None:
        os.environ[_ENABLED] = "1"
        reset_canonical_provider()
        body = self._children("9971110001")
        self.assertEqual(body.get("items") or [], [])

    def test_on_synthetic_l6_matches_legacy(self) -> None:
        """Одиночный L6 *0000 (codeless + synthetic leaf) — parity ON==OFF."""
        self._assert_on_equals_off("9972")

    def test_on_codeless_with_children_matches_legacy(self) -> None:
        self._assert_on_equals_off("9973")

    def test_api_contract_keys_unchanged(self) -> None:
        os.environ[_ENABLED] = "1"
        reset_canonical_provider()
        body = self._children("99")
        self.assertEqual(set(body), {"status", "code", "depth", "items"})
        item = (body.get("items") or [])[0]
        for key in (
            "code", "display_code", "name", "level", "is_leaf", "is_codeless",
            "is_group", "has_children", "import_duty", "duty_rate", "vat_rate",
            "children_count", "has_ds", "has_ss", "measures",
        ):
            self.assertIn(key, item, msg=f"пропало поле {key}")

    # -- fallback to legacy when canonical fails --------------------------

    def test_on_falls_back_to_legacy_when_provider_unavailable(self) -> None:
        _clear_flags()
        reset_canonical_provider()
        off = self._children("99")
        os.environ[_ENABLED] = "1"
        original = catalog.get_canonical_model
        catalog.get_canonical_model = lambda *a, **k: None  # type: ignore[assignment]
        try:
            on = self._children("99")
        finally:
            catalog.get_canonical_model = original  # type: ignore[assignment]
        self.assertEqual(on, off, "при недоступной модели ON должен вернуть legacy-результат")

    # -- shadow mode -------------------------------------------------------

    def _capture_catalog_warnings(self):
        """Контекст: перехватить ``logger.warning`` в ``app.api.tnved_catalog``.

        Патчим сам метод ``warning`` (а не handler/level), чтобы не зависеть от
        конфигурации logging-плагина pytest (уровни/disable/capture).
        """
        records: list[str] = []
        original = catalog.logger.warning

        def _capture(msg, *args, **kwargs):  # noqa: ANN001, ANN002
            try:
                records.append(msg % args if args else str(msg))
            except Exception:  # noqa: BLE001
                records.append(str(msg))

        class _Ctx:
            def __enter__(self_inner):
                catalog.logger.warning = _capture  # type: ignore[assignment]
                return records

            def __exit__(self_inner, *exc):
                catalog.logger.warning = original  # type: ignore[assignment]
                return False

        return _Ctx()

    def test_shadow_does_not_affect_response(self) -> None:
        _clear_flags()
        reset_canonical_provider()
        off = self._children("99")
        os.environ[_SHADOW] = "1"  # ENABLED остаётся OFF
        reset_canonical_provider()
        shadowed = self._children("99")
        self.assertEqual(shadowed, off, "shadow-режим не должен менять ответ")

    def test_shadow_logs_mismatch(self) -> None:
        os.environ[_SHADOW] = "1"
        original = catalog.get_canonical_model
        catalog.get_canonical_model = lambda *a, **k: None  # type: ignore[assignment]
        try:
            with self._capture_catalog_warnings() as records:
                body = self._children("99")
        finally:
            catalog.get_canonical_model = original  # type: ignore[assignment]
        self.assertTrue(body.get("items"), "ответ всё ещё legacy")
        self.assertTrue(
            any("CANONICAL_TREE_SHADOW mismatch" in line for line in records),
            msg=records,
        )

    def test_shadow_no_warning_on_match(self) -> None:
        os.environ[_SHADOW] = "1"
        reset_canonical_provider()
        with self._capture_catalog_warnings() as records:
            self._children("99")
        mismatches = [line for line in records if "CANONICAL_TREE_SHADOW mismatch" in line]
        self.assertEqual(mismatches, [], msg=f"неожиданный mismatch: {mismatches}")

    # -- offline mismatch helper ------------------------------------------

    def test_offline_compare_helper_reports_match(self) -> None:
        reset_canonical_provider()
        with SessionLocal() as db:
            report = catalog.compare_children_structure(db, ["99", "9971", "9972", "9973"])
        self.assertEqual(len(report), 4)
        for entry in report:
            self.assertTrue(entry["match"], msg=f"offline mismatch: {entry}")


# ---------------------------------------------------------------------------
# 4. Shadow comparison unit (без БД)
# ---------------------------------------------------------------------------


@unittest.skipUnless(_OK, "canonical read-path tests need FastAPI app deps")
class ShadowCompareUnitTests(unittest.TestCase):
    def test_identical_children_match(self) -> None:
        a = [{"code": "9701110001", "name": "x", "children": []}]
        b = [{"code": "9701110001", "name": "x", "children": []}]
        self.assertTrue(compare_children("9701", a, b).match)

    def test_count_mismatch(self) -> None:
        res = compare_children("9701", [{"code": "a"}], [{"code": "a"}, {"code": "b"}])
        self.assertFalse(res.match)
        self.assertEqual(res.reason, "count_mismatch")

    def test_fingerprint_mismatch(self) -> None:
        res = compare_children("9701", [{"code": "a", "name": "x"}], [{"code": "a", "name": "y"}])
        self.assertFalse(res.match)
        self.assertEqual(res.reason, "fingerprint_mismatch")

    def test_canonical_unresolved(self) -> None:
        res = compare_children("9701", [{"code": "a"}], None)
        self.assertFalse(res.match)
        self.assertEqual(res.reason, "canonical_unresolved")


if __name__ == "__main__":
    unittest.main()
