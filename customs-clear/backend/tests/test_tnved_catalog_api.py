"""API /api/v1/tnved — дерево разделов и карточка позиции."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path

import pytest

try:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from app import db as app_db, main as app_main
    from app.api import tnved_catalog
    from app.db import SessionLocal
    from app.api.tnved_catalog import _format_duty, clear_preview_cache
    from app.main import app
    from app.models.core import ClassificationDecision, HsRate, PreliminaryDecision
    from app.models.tnved import Chapter, Commodity, Section
    from app.services import normative_store, payment_engine, rate_display
    from app.services.normative_store import init_db

    _OK = True
except ImportError:
    _OK = False


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = (
    BACKEND_ROOT / "scripts" / "bootstrap_disposable_classification_inventory.py"
)
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"
DEFAULT_PREVIEW_REVISION = BACKEND_ROOT / "data" / "tnved_preview_cache_revision.txt"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_paths() -> set[Path]:
    paths = {
        DEFAULT_DATABASE.resolve(),
        PINNED_CATALOGUE.resolve(),
        DEFAULT_PREVIEW_REVISION.resolve(),
    }
    configured_url = make_url(app_db.DATABASE_URL)
    if configured_url.drivername.startswith("sqlite") and configured_url.database:
        paths.add(Path(configured_url.database).resolve())

    source_database = os.environ.get("TNVED_SOURCE_DB", "").strip()
    if source_database:
        if source_database.startswith("sqlite:"):
            source_url = make_url(source_database)
            if source_url.database:
                paths.add(Path(source_url.database).resolve())
        elif "://" not in source_database:
            paths.add(Path(source_database).resolve())

    configured_revision = os.environ.get(
        "TNVED_PREVIEW_CACHE_REVISION_FILE", ""
    ).strip()
    if configured_revision:
        paths.add(Path(configured_revision).expanduser().resolve())
    return paths


def _protected_fingerprints() -> dict[Path, str | None]:
    paths = {
        candidate
        for path in _protected_paths()
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    }
    return {
        path: _sha256(path) if path.is_file() else None
        for path in paths
    }


@pytest.fixture(scope="module", autouse=True)
def _disposable_tnved_catalog_database(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Run the real catalogue endpoints against a disposable bootstrapped DB."""
    if not _OK:
        yield
        return

    temp_dir = tmp_path_factory.mktemp("tnved-catalog-api")
    database = temp_dir / "tnved-catalog-api.db"
    preview_revision = temp_dir / "tnved-preview-cache-revision.txt"
    protected_hashes = _protected_fingerprints()
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("TNVED_SOURCE_DB", None)
    env.pop("TNVED_PREVIEW_CACHE_REVISION_FILE", None)
    result = subprocess.run(
        [sys.executable, str(BOOTSTRAP_SCRIPT), str(database)],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _protected_fingerprints() == protected_hashes

    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    patches = pytest.MonkeyPatch()
    patches.setenv("TNVED_PREVIEW_CACHE_REVISION_FILE", str(preview_revision))
    patches.setattr(sys.modules[__name__], "init_db", lambda: None)
    patches.setattr(sys.modules[__name__], "SessionLocal", factory)
    patches.setattr(app_main, "init_db", lambda: None)
    patches.setattr(app_main, "engine", engine)
    patches.setattr(app_db, "engine", engine)
    patches.setattr(app_db, "SessionLocal", factory)
    patches.setattr(normative_store, "engine", engine)
    patches.setattr(normative_store, "SessionLocal", factory)
    patches.setattr(tnved_catalog, "SessionLocal", factory)
    patches.setattr(payment_engine, "SessionLocal", factory)
    patches.setattr(rate_display, "SessionLocal", factory)

    try:
        yield
    finally:
        try:
            tnved_catalog.clear_preview_cache()
        finally:
            patches.undo()
            engine.dispose()
            for path in (
                database,
                Path(f"{database}-shm"),
                Path(f"{database}-wal"),
                preview_revision,
            ):
                if path.exists():
                    path.unlink()
            assert _protected_fingerprints() == protected_hashes


@unittest.skipUnless(_OK, "tnved catalog tests need FastAPI app")
class TnvedCatalogApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls._section_id: int | None = None
        cls._chapter_id: int | None = None
        with SessionLocal() as db:
            sec = Section(roman_number="TST", title="Тестовый раздел", notes="Примечание раздела")
            db.add(sec)
            db.flush()
            # Коды 99xx не пересекаются с типичными выгрузками ТН ВЭД (избегаем коллизий с 0101 и т.п. в БД).
            ch = Chapter(
                section_id=sec.id,
                code="9901",
                title="Тестовая группа",
                notes="Примечание группы",
            )
            db.add(ch)
            db.flush()
            db.add_all([
                Commodity(
                    chapter_id=ch.id,
                    code="9901210000",
                    description="Тестовый товар 10 знаков",
                    unit="кг",
                    import_duty="10 %",
                ),
                Commodity(
                    chapter_id=ch.id,
                    code="9901610000",
                    description="Второй прямой потомок позиции",
                    unit="шт",
                    import_duty="Пошлина: 5% | НДС: 20%",
                ),
                Commodity(
                    chapter_id=ch.id,
                    code="9902110000",
                    description="Групповой подзаголовок",
                ),
                Commodity(
                    chapter_id=ch.id,
                    code="9902111000",
                    description="Первый потомок группового подзаголовка",
                ),
                Commodity(
                    chapter_id=ch.id,
                    code="9902119000",
                    description="Второй потомок группового подзаголовка",
                ),
                Commodity(
                    chapter_id=ch.id,
                    code="9901",
                    description="Позиция на 4 знака",
                    unit="—",
                    import_duty="5 %",
                ),
            ])
            db.add(HsRate(
                hs_code="9901610000",
                hs_prefix="9901610000",
                duty_rate="5",
                vat_import_rate=22.0,
                source_revision="test-tree-leaf",
            ))
            db.add(
                ClassificationDecision(
                    hs_code="9901210000",
                    product_name="Тестовый товар для ПКР",
                    description="Описание решения ФТС",
                    target_entity="Тестовый товар",
                    decision_number="TST-PKR-990121",
                    issue_date="2024-01-15",
                )
            )
            db.add(
                PreliminaryDecision(
                    hs_code="9901210000",
                    description="Предварительное решение IFCG для теста",
                    source="ifcg",
                )
            )
            db.commit()
            cls._section_id = sec.id
            cls._chapter_id = ch.id

    @classmethod
    def tearDownClass(cls):
        if cls._section_id is None:
            return
        sid = cls._section_id
        with SessionLocal() as db:
            ch_ids = [r[0] for r in db.query(Chapter.id).filter(Chapter.section_id == sid).all()]
            for cid in ch_ids:
                db.query(Commodity).filter(Commodity.chapter_id == cid).delete()
            db.query(ClassificationDecision).filter(
                ClassificationDecision.decision_number == "TST-PKR-990121"
            ).delete()
            db.query(PreliminaryDecision).filter(
                PreliminaryDecision.description == "Предварительное решение IFCG для теста"
            ).delete()
            db.query(HsRate).filter(HsRate.source_revision == "test-tree-leaf").delete()
            db.query(Chapter).filter(Chapter.section_id == sid).delete()
            db.query(Section).filter(Section.id == sid).delete()
            db.commit()

    def test_sections_ok(self):
        r = self.client.get("/api/v1/tnved/sections")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("status"), "OK")
        self.assertIsInstance(body.get("sections"), list)
        ids = [s["id"] for s in body["sections"]]
        self.assertIn(self._section_id, ids)

    def test_chapters_ok(self):
        assert self._section_id is not None
        r = self.client.get(f"/api/v1/tnved/sections/{self._section_id}/chapters")
        self.assertEqual(r.status_code, 200)
        chs = r.json().get("chapters") or []
        codes = [c["code"] for c in chs]
        self.assertIn("9901", codes)

    def test_commodities_ok(self):
        assert self._chapter_id is not None
        r = self.client.get(f"/api/v1/tnved/chapters/{self._chapter_id}/commodities")
        self.assertEqual(r.status_code, 200)
        items = r.json().get("commodities") or []
        self.assertTrue(any(x.get("code") == "9901210000" for x in items))

    def test_detail_10(self):
        r = self.client.get("/api/v1/tnved/9901210000")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d.get("code"), "9901210000")
        self.assertIn("notes_combined", d)
        self.assertIn("Раздел", d["notes_combined"])
        self.assertIn("Группа", d["notes_combined"])
        self.assertIn("preliminary_decisions", d)
        block = d["preliminary_decisions"]
        self.assertGreaterEqual(block.get("total_count", 0), 1)
        cls_items = block.get("classification_decisions") or []
        self.assertTrue(any(x.get("decision_number") == "TST-PKR-990121" for x in cls_items))

    def test_preliminary_decisions_endpoint(self):
        r = self.client.get("/api/v1/tnved/9901210000/preliminary-decisions")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("status"), "OK")
        block = body.get("preliminary_decisions") or {}
        self.assertGreaterEqual(block.get("total_count", 0), 2)
        prelim = block.get("preliminary_decisions") or []
        self.assertTrue(any("IFCG" in (x.get("description") or "") for x in prelim))

    def test_preliminary_decisions_empty_message(self):
        r = self.client.get("/api/v1/tnved/9999999999/preliminary-decisions")
        self.assertEqual(r.status_code, 200)
        block = r.json().get("preliminary_decisions") or {}
        self.assertEqual(block.get("total_count"), 0)
        self.assertTrue(block.get("empty_message"))

    def test_detail_4_digit_row(self):
        r = self.client.get("/api/v1/tnved/9901")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("code"), "9901")
        self.assertIn("Позиция на 4 знака", r.json().get("description", ""))

    def test_detail_404(self):
        r = self.client.get("/api/v1/tnved/9999999999")
        self.assertEqual(r.status_code, 404)

    def test_invalid_code_length(self):
        r = self.client.get("/api/v1/tnved/123")
        self.assertEqual(r.status_code, 400)

    def test_format_duty_strips_pdf_footnotes(self):
        """Сноски вида 63С), 563С), 1363С) не попадают в ответ API."""
        self.assertEqual(_format_duty("563С)"), "")
        self.assertEqual(_format_duty("1363С)"), "")
        self.assertEqual(_format_duty("5 563С)"), "5%")
        self.assertEqual(_format_duty("Пошлина: Пошлина: | НДС: НДС:"), "")
        self.assertIn("15", _format_duty("15, но не менее 0,07 евро за 1 л 563С)"))
        self.assertNotIn("563С)", _format_duty("15, но не менее 0,07 евро за 1 л 563С)"))

    def test_children_direct_heading(self):
        r = self.client.get("/api/v1/tnved/children/9901?depth=direct")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("depth"), "direct")
        items = body.get("items") or []
        codes = [x.get("code") for x in items]
        self.assertIn("9901210000", codes)
        self.assertIn("9901610000", codes)
        leaf = next(x for x in items if x.get("code") == "9901610000")
        self.assertTrue(leaf.get("is_leaf"))
        self.assertNotIn("Пошлина:", (leaf.get("duty_rate") or ""))

    def test_children_codeless_has_children(self):
        r = self.client.get("/api/v1/tnved/children/9902110000?depth=direct")
        self.assertEqual(r.status_code, 200)
        items = r.json().get("items") or []
        self.assertEqual(len(items), 2)
        codes = {x.get("code") for x in items}
        self.assertIn("9902111000", codes)
        self.assertIn("9902119000", codes)

    def test_format_duty_strips_garbage_and_parses_composite(self):
        self.assertEqual(_format_duty("Пошлина: Пошлина: | НДС: НДС:"), "")
        self.assertEqual(_format_duty("Пошлина: 5% | НДС: 20%"), "5%")

    def test_children_group_returns_headings(self):
        r = self.client.get("/api/tnved/children/99?depth=direct")
        self.assertEqual(r.status_code, 200)
        items = r.json().get("items") or []
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(all(item.get("level") == "heading" for item in items))
        self.assertTrue(all(not item.get("is_leaf") for item in items))

    def test_children_leaf_returns_empty(self):
        r = self.client.get("/api/tnved/children/9901210000?depth=direct")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("items") or [], [])

    def test_preview_chapter_84_no_sgr(self):
        from app.api.tnved_catalog import clear_preview_cache

        clear_preview_cache()
        r = self.client.get("/api/v1/tnved/preview/8401100000")
        self.assertEqual(r.status_code, 200)
        badges = r.json().get("non_tariff", {}).get("measure_badges") or []
        self.assertNotIn("СГР", badges)

    def test_commodity_chapter_84_duty_from_hs_rates(self):
        # The test owns its tariff evidence instead of depending on a global
        # developer database populated by an unrelated full-catalog import.
        with SessionLocal() as db:
            row = HsRate(
                hs_code="8401300000",
                hs_prefix="8401300000",
                duty_rate="15",
                vat_import_rate=22.0,
                source_revision="test-exact-rate",
            )
            db.add(row)
            db.commit()
            rate_id = row.id
        try:
            r = self.client.get("/api/v1/tnved/8401300000")
            self.assertEqual(r.status_code, 200)
            duty = r.json().get("import_duty") or ""
            self.assertIn("15", duty)
        finally:
            with SessionLocal() as db:
                db.query(HsRate).filter(HsRate.id == rate_id).delete()
                db.commit()

    def test_detail_rate_only_requires_exact_rate(self):
        with SessionLocal() as db:
            row = HsRate(
                hs_code="9988123456",
                hs_prefix="9988123456",
                duty_rate="7.5",
                vat_import_rate=22.0,
                source_revision="test-exact-rate-only",
            )
            db.add(row)
            db.commit()
            rate_id = row.id
        try:
            r = self.client.get("/api/v1/tnved/9988123456")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json().get("code"), "9988123456")
            self.assertIn("7.5", (r.json().get("import_duty") or "").replace(",", "."))
        finally:
            with SessionLocal() as db:
                db.query(HsRate).filter(HsRate.id == rate_id).delete()
                db.commit()

    def test_detail_rate_only_rejects_prefix_rate(self):
        with SessionLocal() as db:
            row = HsRate(
                hs_code="9988000000",
                hs_prefix="9988",
                duty_rate="9",
                vat_import_rate=22.0,
                source_revision="test-prefix-rate-only",
            )
            db.add(row)
            db.commit()
            rate_id = row.id
        try:
            r = self.client.get("/api/v1/tnved/9988123456")
            self.assertEqual(r.status_code, 404)
        finally:
            with SessionLocal() as db:
                db.query(HsRate).filter(HsRate.id == rate_id).delete()
                db.commit()

    def test_children_compat_route(self):
        r = self.client.get("/api/tnved/children/9901?depth=direct")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json().get("items") or []), 1)

    def test_node_leaf_rates(self):
        r = self.client.get("/api/v1/tnved/node/9901210000")
        self.assertEqual(r.status_code, 200)
        node = r.json().get("node") or {}
        self.assertEqual(node.get("code"), "9901210000")
        self.assertIn("10", node.get("duty_rate") or "")

    def test_preview_vat_rate_from_data(self):
        """preview.payments.vat_rates берёт фактическую ставку из hs_rates, без хардкода 20%/22%."""
        # Без hs_rate — стандартная ставка по умолчанию 22 (не 20).
        clear_preview_cache()
        r0 = self.client.get("/api/v1/tnved/preview/9901210000")
        self.assertEqual(r0.status_code, 200)
        self.assertEqual(r0.json().get("payments", {}).get("vat_rates"), [22])
        # С льготной ставкой 10 в hs_rates — preview отдаёт [10].
        with SessionLocal() as db:
            db.add(HsRate(hs_code="9901210000", hs_prefix="9901", duty_rate="10", vat_import_rate=10.0))
            db.commit()
        try:
            clear_preview_cache()
            r1 = self.client.get("/api/v1/tnved/preview/9901210000")
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r1.json().get("payments", {}).get("vat_rates"), [10])
        finally:
            with SessionLocal() as db:
                db.query(HsRate).filter(HsRate.hs_code == "9901210000").delete()
                db.commit()
            clear_preview_cache()

    def test_hierarchy_tree_ok(self):
        r = self.client.get("/api/v1/tnved/hierarchy-tree?prefix=9901")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("status"), "OK")
        tree = body.get("tree") or []

        def collect(nodes: list) -> dict:
            out: dict = {}
            for n in nodes:
                out[n["code"]] = n
                out.update(collect(n.get("children") or []))
            return out

        by_code = collect(tree)
        self.assertIn("9901", by_code)
        self.assertIn("9901210000", by_code)
        leaf = by_code["9901210000"]
        self.assertIn(leaf.get("import_duty"), ("10 %", "10%"))
        self.assertTrue("name" in leaf or "title_ru" in leaf)
        self.assertIn("children", leaf)

