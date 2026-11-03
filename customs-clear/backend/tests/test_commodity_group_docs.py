"""Tests for commodity group regulatory documents."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import db as app_db
from app.db import SessionLocal
from scripts import seed_commodity_group_docs


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = BACKEND_ROOT / "scripts" / "bootstrap_disposable_classification_inventory.py"
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_paths() -> set[Path]:
    paths = {DEFAULT_DATABASE.resolve(), PINNED_CATALOGUE.resolve()}
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
    return paths


def _protected_fingerprints() -> dict[Path, str | None]:
    return {
        path: _sha256(path) if path.is_file() else None
        for path in _protected_paths()
    }


@pytest.fixture(scope="module")
def commodity_group_docs_session_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sessionmaker]:
    """Build and seed an isolated catalogue without using configured databases."""
    temp_dir = tmp_path_factory.mktemp("commodity-group-docs")
    database = temp_dir / "commodity-group-docs.db"
    protected_hashes = _protected_fingerprints()
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("TNVED_SOURCE_DB", None)
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
    patches.setattr(sys.modules[__name__], "SessionLocal", factory)
    patches.setattr(app_db, "engine", engine)
    patches.setattr(app_db, "SessionLocal", factory)
    patches.setattr(seed_commodity_group_docs, "SessionLocal", factory)
    patches.setattr(seed_commodity_group_docs, "DRY_RUN", False)

    def totals() -> tuple[int, int]:
        with engine.connect() as connection:
            return (
                int(
                    connection.execute(
                        text("SELECT COUNT(*) FROM regulatory_documents")
                    ).scalar_one()
                ),
                int(
                    connection.execute(
                        text("SELECT COUNT(*) FROM regulatory_doc_hs_mapping")
                    ).scalar_one()
                ),
            )

    try:
        before = totals()
        seed_commodity_group_docs.run()
        initial = totals()
        seed_commodity_group_docs.run()
        repeated = totals()
        assert initial[0] > before[0]
        assert initial[1] > before[1]
        assert repeated == initial
        yield factory
    finally:
        patches.undo()
        engine.dispose()
        for suffix in ("", "-shm", "-wal"):
            candidate = Path(f"{database}{suffix}")
            if candidate.exists():
                candidate.unlink()
        assert _protected_fingerprints() == protected_hashes


class TestCommodityGroupDocs:
    @pytest.fixture(autouse=True)
    def _db(self, commodity_group_docs_session_factory: sessionmaker):
        self.db = commodity_group_docs_session_factory()
        try:
            yield
        finally:
            self.db.close()

    def _count_docs_with_prefix(self, prefix: str) -> int:
        return self.db.execute(text(
            "SELECT COUNT(DISTINCT m.doc_id) FROM regulatory_doc_hs_mapping m "
            "WHERE m.hs_prefix LIKE :pat"
        ), {"pat": f"{prefix}%"}).scalar()

    def test_electronics_has_crypto_notifications(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents "
            "WHERE agency IN ('FSB') AND title LIKE '%отификаци%'"
        )).scalar()
        assert count >= 8, f"Expected >= 8 FSB crypto notifications, got {count}"

    def test_automobiles_has_otts_docs(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents WHERE title LIKE '%ОТТС%'"
        )).scalar()
        assert count >= 5, f"Expected >= 5 OTTS docs, got {count}"

    def test_food_has_country_vet_requirements(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents "
            "WHERE agency = 'RSN' AND title LIKE '%етеринарн%требован%импорт%'"
        )).scalar()
        assert count >= 5, f"Expected >= 5 country-specific vet docs, got {count}"

    def test_pharma_has_ru_docs(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents "
            "WHERE agency = 'ROSZDRAV' AND title LIKE '%егистрац%'"
        )).scalar()
        assert count >= 3, f"Expected >= 3 registration docs, got {count}"

    def test_precious_metals_has_kimberley(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents WHERE title LIKE '%имберли%'"
        )).scalar()
        assert count >= 1

    def test_weapons_has_license_docs(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents "
            "WHERE title LIKE '%ицензиров%импорт%оруж%'"
        )).scalar()
        assert count >= 3

    def test_clothing_has_honest_mark(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents WHERE title LIKE '%естный Знак%'"
        )).scalar()
        assert count >= 3

    def test_chemicals_has_safety_sheets(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM regulatory_documents WHERE title LIKE '%аспорт%безопасн%'"
        )).scalar()
        assert count >= 1
