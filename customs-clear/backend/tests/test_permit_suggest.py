"""Подбор СС/ДС и фильтр ТРОИС."""
from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.services.trois_service import trouis_conflicts_in_text
from app.services.permit_suggest_service import suggest_permits


BACKEND_ROOT = Path(__file__).resolve().parents[1]
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
    for value in (
        os.environ.get("DATABASE_URL", ""),
        os.environ.get("TNVED_SOURCE_DB", ""),
    ):
        value = value.strip()
        if not value:
            continue
        if value.startswith("sqlite:"):
            url = make_url(value)
            if url.database:
                paths.add(Path(url.database).resolve())
        elif "://" not in value:
            paths.add(Path(value).resolve())
    return paths


def _protected_fingerprints() -> dict[Path, str | None]:
    return {
        candidate: _sha256(candidate) if candidate.is_file() else None
        for path in _protected_paths()
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    }


@pytest.fixture(scope="module", autouse=True)
def _isolated_trois_registry_database(tmp_path_factory: pytest.TempPathFactory):
    """Load the TROIS cache from disposable SQLite, never ambient databases."""
    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("permit-suggest")
    database = temp_dir / "permit-suggest.db"
    database_url = f"sqlite:///{database}"
    patches = pytest.MonkeyPatch()
    patches.setenv("DATABASE_URL", database_url)
    patches.delenv("TNVED_SOURCE_DB", raising=False)

    from app import db as app_db
    from app.models.tnved import TroisRegistry
    from app.services import trois_registry_loader, trois_service

    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    TroisRegistry.__table__.create(engine)
    patches.setattr(app_db, "engine", engine)
    patches.setattr(app_db, "SessionLocal", factory)
    patches.setattr(trois_registry_loader, "SessionLocal", factory)
    patches.setattr(trois_service, "_db_cache_loaded", False)

    try:
        yield
    finally:
        patches.undo()
        engine.dispose()
        disposable_paths = (database, Path(f"{database}-wal"), Path(f"{database}-shm"))
        for path in disposable_paths:
            if path.exists():
                path.unlink()
        assert not any(path.exists() for path in disposable_paths)
        assert _protected_fingerprints() == protected_hashes


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
