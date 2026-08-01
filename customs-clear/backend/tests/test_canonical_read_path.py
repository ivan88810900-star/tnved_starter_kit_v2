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
        ShadowComparison,
        ShadowMonitor,
        compare_children,
        flags,
        get_shadow_metrics,
        get_provider,
        provider as provider_mod,
        reset_canonical_provider,
        reset_shadow_metrics,
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
    _section_id: int | None = None
    _chapter_id: int | None = None
    _leaf_id: int | None = None
    _ambiguous_code = "9876130000"

    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        with SessionLocal() as db:
            sec = Section(roman_number="TSREV", title="Revision test section", notes="section-v1")
            db.add(sec)
            db.flush()
            ch = Chapter(
                section_id=sec.id,
                code="98",
                title="Revision test chapter",
                notes="chapter-v1",
            )
            db.add(ch)
            db.flush()
            heading = Commodity(
                chapter_id=ch.id,
                code="9876",
                description="Revision heading",
                unit="",
                import_duty="",
            )
            leaf = Commodity(
                chapter_id=ch.id,
                code="9876110001",
                description="Leaf v1",
                unit="шт",
                import_duty="1%",
            )
            ambiguous = Commodity(
                chapter_id=ch.id,
                code=cls._ambiguous_code,
                description="Ambiguous leaf",
                unit="",
                import_duty="",
            )
            db.add_all([heading, leaf, ambiguous])
            db.commit()
            cls._section_id = sec.id
            cls._chapter_id = ch.id
            cls._leaf_id = leaf.id

    @classmethod
    def tearDownClass(cls) -> None:
        with SessionLocal() as db:
            db.query(HsRate).filter(HsRate.hs_code == cls._ambiguous_code).delete()
            if cls._chapter_id is not None:
                db.query(Commodity).filter(Commodity.chapter_id == cls._chapter_id).delete()
                db.query(Chapter).filter(Chapter.id == cls._chapter_id).delete()
            if cls._section_id is not None:
                db.query(Section).filter(Section.id == cls._section_id).delete()
            db.commit()

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

    def test_stable_database_does_not_rehash_full_catalog_per_request(self) -> None:
        prov = provider_mod.CanonicalTreeProvider()
        original = prov._compute_revision
        calls: list[int] = []

        def _counted(session_factory):  # noqa: ANN001
            calls.append(1)
            return original(session_factory)

        prov._compute_revision = _counted  # type: ignore[assignment]
        first = prov.get_model()
        second = prov.get_model()
        self.assertIsNotNone(first)
        self.assertIs(first, second)
        self.assertEqual(len(calls), 1, "stable DB должна использовать cheap source token")

    def test_revision_changes_when_hs_rates_leaf_input_changes(self) -> None:
        prov = get_provider()
        rev0 = prov._compute_revision(SessionLocal)
        code = self._ambiguous_code  # существует в commodities и влияет на leaf_flags
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

    def test_revision_changes_when_inherited_leaf_prefix_changes(self) -> None:
        """Parser читает унаследованный hs_prefix, поэтому он входит в cache-key."""
        prov = provider_mod.CanonicalTreeProvider()
        rev0 = prov._compute_revision(SessionLocal)
        marker = "test-canonical-inherited-prefix"
        with SessionLocal() as db:
            db.add(
                HsRate(
                    hs_code="9876",
                    hs_prefix="9876",
                    duty_rate="0",
                    vat_import_rate=22.0,
                    source_revision=marker,
                )
            )
            db.commit()
        try:
            rev1 = prov._compute_revision(SessionLocal)
            self.assertNotEqual(rev0, rev1)
        finally:
            with SessionLocal() as db:
                db.query(HsRate).filter(HsRate.source_revision == marker).delete()
                db.commit()
        self.assertEqual(rev0, prov._compute_revision(SessionLocal))

    def test_revision_change_triggers_rebuild(self) -> None:
        prov = get_provider()
        prov.get_model()
        builds_after_first = prov.build_count
        code = self._ambiguous_code
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

    def test_in_place_commodity_update_changes_revision_and_rebuilds(self) -> None:
        """RCA: count+max(id) не замечал UPDATE и отдавал stale model."""
        self.assertIsNotNone(self._leaf_id)
        prov = get_provider()
        model_before = prov.get_model()
        self.assertIsNotNone(model_before)
        node_before = model_before.get_by_code("9876110001")
        self.assertEqual(node_before.title, "Leaf v1")
        builds_before = prov.build_count
        revision_before = prov.current_revision

        with SessionLocal() as db:
            row = db.get(Commodity, self._leaf_id)
            row.description = "Leaf v2"
            row.import_duty = "9%"
            db.commit()
        try:
            model_after = prov.get_model()
            self.assertIsNotNone(model_after)
            node_after = model_after.get_by_code("9876110001")
            self.assertIsNot(model_after, model_before)
            self.assertNotEqual(prov.current_revision, revision_before)
            self.assertEqual(prov.build_count, builds_before + 1)
            self.assertEqual(node_after.title, "Leaf v2")
            self.assertEqual(node_after.metadata.get("import_duty"), "9%")
        finally:
            with SessionLocal() as db:
                row = db.get(Commodity, self._leaf_id)
                row.description = "Leaf v1"
                row.import_duty = "1%"
                db.commit()

    def test_chapter_and_section_notes_change_revision(self) -> None:
        self.assertIsNotNone(self._chapter_id)
        self.assertIsNotNone(self._section_id)
        prov = get_provider()
        rev0 = prov._compute_revision(SessionLocal)
        with SessionLocal() as db:
            chapter = db.get(Chapter, self._chapter_id)
            chapter.notes = "chapter-v2"
            db.commit()
        try:
            rev1 = prov._compute_revision(SessionLocal)
            self.assertNotEqual(rev0, rev1)
        finally:
            with SessionLocal() as db:
                chapter = db.get(Chapter, self._chapter_id)
                chapter.notes = "chapter-v1"
                db.commit()

        rev2 = prov._compute_revision(SessionLocal)
        self.assertEqual(rev0, rev2)
        with SessionLocal() as db:
            section = db.get(Section, self._section_id)
            section.notes = "section-v2"
            db.commit()
        try:
            self.assertNotEqual(rev2, prov._compute_revision(SessionLocal))
        finally:
            with SessionLocal() as db:
                section = db.get(Section, self._section_id)
                section.notes = "section-v1"
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

    def test_build_retries_when_inputs_change_mid_build(self) -> None:
        """Модель нельзя публиковать под revision, устаревшей во время build."""
        prov = provider_mod.CanonicalTreeProvider()
        revisions = iter(["r1", "r1", "r2", "r2"])
        builds: list[int] = []

        def _revision(session_factory):  # noqa: ANN001
            return next(revisions)

        def _build(session_factory):  # noqa: ANN001
            builds.append(1)
            return CanonicalModel.from_roots([])

        prov._get_revision = _revision  # type: ignore[assignment]
        prov._build = _build  # type: ignore[assignment]
        model = prov.get_model()
        self.assertIsNotNone(model)
        self.assertEqual(len(builds), 2)
        self.assertEqual(prov.current_revision, "r2")
        self.assertEqual(prov.build_count, 1)


# ---------------------------------------------------------------------------
# 3. /children read-path (OFF/ON/shadow) на seeded-фикстурах
# ---------------------------------------------------------------------------


@unittest.skipUnless(_OK, "canonical read-path tests need FastAPI app deps")
class CanonicalChildrenReadPathTests(unittest.TestCase):
    _section_id: int | None = None

    @staticmethod
    def _delete_fixture(db) -> None:  # noqa: ANN001
        """Удаляет только синтетическую главу этого класса, включая хвост от прерванного прогона."""
        section_ids = [row[0] for row in db.query(Section.id).filter(Section.roman_number == "MMM").all()]
        if not section_ids:
            return
        chapter_ids = [
            row[0]
            for row in db.query(Chapter.id).filter(Chapter.section_id.in_(section_ids)).all()
        ]
        if chapter_ids:
            db.query(Commodity).filter(Commodity.chapter_id.in_(chapter_ids)).delete(
                synchronize_session=False
            )
            db.query(Chapter).filter(Chapter.id.in_(chapter_ids)).delete(synchronize_session=False)
        db.query(Section).filter(Section.id.in_(section_ids)).delete(synchronize_session=False)
        db.flush()

    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        cls.client = TestClient(app)
        with SessionLocal() as db:
            cls._delete_fixture(db)
            # Синтетическая глава 99 (в реальной номенклатуре ТН ВЭД отсутствует),
            # чтобы фикстуры не конфликтовали с наполненной БД.
            # Валидный, но практически невозможный реальный Roman-section.
            sec = Section(roman_number="MMM", title="Canonical test section", notes="")
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
        with SessionLocal() as db:
            cls._delete_fixture(db)
            db.commit()
        cls._section_id = None

    def setUp(self) -> None:
        _clear_flags()
        reset_canonical_provider()
        reset_shadow_metrics()

    def tearDown(self) -> None:
        _clear_flags()
        reset_canonical_provider()
        reset_shadow_metrics()

    def _children(self, code: str, depth: str = "direct") -> dict:
        r = self.client.get(f"/api/v1/tnved/children/{code}?depth={depth}")
        self.assertEqual(r.status_code, 200, msg=r.text)
        return r.json()

    def _root_children(self, depth: str = "direct") -> dict:
        r = self.client.get(f"/api/v1/tnved/children?depth={depth}")
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

    def test_root_and_roman_section_remain_table_backed(self) -> None:
        _clear_flags()
        root_off = self._root_children()
        roman_off = self._children("MMM")
        os.environ[_ENABLED] = "1"
        root_on = self._root_children()
        roman_on = self._children("MMM")
        self.assertEqual(root_on, root_off)
        self.assertEqual(roman_on, roman_off)

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
        metrics = get_shadow_metrics()
        self.assertEqual(metrics.shadow_match, 1)
        self.assertEqual(metrics.shadow_mismatch, 0)

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
        metrics = get_shadow_metrics()
        self.assertEqual(metrics.shadow_match, 0)
        self.assertEqual(metrics.shadow_mismatch, 1)

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

    def test_monitor_counts_and_samples_mismatches(self) -> None:
        monitor = ShadowMonitor(mismatch_log_every=3)
        match = ShadowComparison(code="9701", match=True)
        mismatch = ShadowComparison(code="9701", match=False)

        self.assertFalse(monitor.record(match))
        decisions = [monitor.record(mismatch) for _ in range(6)]
        self.assertEqual(decisions, [True, False, True, False, False, True])
        snapshot = monitor.snapshot()
        self.assertEqual(snapshot.shadow_match, 1)
        self.assertEqual(snapshot.shadow_mismatch, 6)

        monitor.reset()
        self.assertEqual(monitor.snapshot().shadow_match, 0)
        self.assertEqual(monitor.snapshot().shadow_mismatch, 0)


if __name__ == "__main__":
    unittest.main()
