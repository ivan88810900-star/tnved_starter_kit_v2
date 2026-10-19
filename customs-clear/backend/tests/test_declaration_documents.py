"""Tests for declaration documents reference — Issue #87."""
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
from app.services import normative_store
from app.services.normative_store import find_declaration_documents
from scripts import seed_declaration_documents


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
def declaration_documents_session_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[sessionmaker]:
    """Build and seed an isolated catalogue without using configured databases."""
    temp_dir = tmp_path_factory.mktemp("declaration-documents")
    database = temp_dir / "declaration-documents.db"
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
    patches.setattr(normative_store, "SessionLocal", factory)
    patches.setattr(seed_declaration_documents, "engine", engine)
    patches.setattr(seed_declaration_documents, "SessionLocal", factory)
    patches.setattr(seed_declaration_documents, "DRY_RUN", False)

    try:
        initial = seed_declaration_documents.seed()
        repeated = seed_declaration_documents.seed()
        assert repeated == {"inserted": 0, "total": initial["total"]}
        yield factory
    finally:
        patches.undo()
        engine.dispose()
        for suffix in ("", "-shm", "-wal"):
            candidate = Path(f"{database}{suffix}")
            if candidate.exists():
                candidate.unlink()
        assert _protected_fingerprints() == protected_hashes


@pytest.fixture(autouse=True)
def _declaration_documents_lookup_database(
    declaration_documents_session_factory: sessionmaker,
) -> None:
    """Ensure lookup-only tests share the same isolated seeded database."""


class TestDeclarationDocumentsData:
    @pytest.fixture(autouse=True)
    def _db(self, declaration_documents_session_factory: sessionmaker):
        self.db = declaration_documents_session_factory()
        try:
            yield
        finally:
            self.db.close()

    def test_total_entries_above_50(self) -> None:
        total = self.db.execute(text("SELECT COUNT(*) FROM declaration_documents")).scalar()
        assert total >= 50, f"Expected >= 50, got {total}"

    def test_universal_docs_exist(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM declaration_documents WHERE hs_prefix = ''"
        )).scalar()
        assert count >= 10

    def test_conformity_docs_exist(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM declaration_documents WHERE category = 'conformity'"
        )).scalar()
        assert count >= 20

    def test_all_have_legal_ref(self) -> None:
        missing = self.db.execute(text(
            "SELECT COUNT(*) FROM declaration_documents WHERE legal_ref IS NULL OR legal_ref = ''"
        )).scalar()
        assert missing == 0

    def test_mandatory_docs_exist(self) -> None:
        count = self.db.execute(text(
            "SELECT COUNT(*) FROM declaration_documents WHERE is_mandatory = 1"
        )).scalar()
        assert count >= 30


class TestDeclarationDocumentsLookup:
    def test_universal_docs_for_any_code(self) -> None:
        docs = find_declaration_documents("8517120000")
        universal = [d for d in docs if d["hs_prefix"] == ""]
        assert len(universal) >= 10
        dt_found = any(d["doc_type"] == "ДТ" for d in universal)
        assert dt_found, "ДТ (декларация на товары) should be in universal docs"

    def test_electronics_has_conformity(self) -> None:
        docs = find_declaration_documents("8517120000")
        conformity = [d for d in docs if d["category"] == "conformity"]
        assert len(conformity) >= 2

    def test_meat_has_vet_cert(self) -> None:
        docs = find_declaration_documents("0201300000")
        vet = [d for d in docs if d["doc_type"] == "vet_cert"]
        assert len(vet) >= 1

    def test_pharma_has_registration(self) -> None:
        docs = find_declaration_documents("3004900000")
        reg = [d for d in docs if d["doc_type"] == "reg_cert"]
        assert len(reg) >= 1

    def test_vehicle_has_ottc_and_recycling(self) -> None:
        docs = find_declaration_documents("8703220000")
        doc_types = {d["doc_type"] for d in docs}
        assert "OTTC" in doc_types
        assert "recycling_fee" in doc_types

    def test_weapons_has_license(self) -> None:
        docs = find_declaration_documents("9302000000")
        lic = [d for d in docs if d["doc_type"] == "license_weapon"]
        assert len(lic) >= 1

    def test_mandatory_sorted_first(self) -> None:
        docs = find_declaration_documents("8517120000")
        if len(docs) > 1:
            mandatory_indices = [i for i, d in enumerate(docs) if d["is_mandatory"]]
            optional_indices = [i for i, d in enumerate(docs) if not d["is_mandatory"]]
            if mandatory_indices and optional_indices:
                assert max(mandatory_indices) < max(optional_indices) or min(mandatory_indices) < min(optional_indices)

    def test_crypto_notification_for_8517(self) -> None:
        docs = find_declaration_documents("8517120000")
        crypto = [d for d in docs if d["doc_type"] == "notification_crypto"]
        assert len(crypto) >= 1
        assert crypto[0]["condition"] != ""
