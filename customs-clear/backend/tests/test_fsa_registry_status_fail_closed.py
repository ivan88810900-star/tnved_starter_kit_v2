"""FSA opendata status must not upgrade an unverified row to VALID."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.opendata_registry import (
    _registry_status_to_verify,
    lookup_fsa_certificate,
)
from app.services.permits_service import normalize_number

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BACKEND_ROOT / "customs.db"
PINNED_CATALOGUE = BACKEND_ROOT / "customs.db.backup_before_pdf_import"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_fingerprints() -> dict[Path, str | None]:
    paths = {
        candidate
        for path in (DEFAULT_DATABASE, PINNED_CATALOGUE)
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    }
    return {
        path: _sha256(path) if path.is_file() else None
        for path in paths
    }


@pytest.fixture(scope="module", autouse=True)
def _isolated_fsa_registry_status_database(tmp_path_factory: pytest.TempPathFactory):
    """Exercise registry status lookups without reading or creating ambient SQLite."""
    protected_hashes = _protected_fingerprints()
    temp_dir = tmp_path_factory.mktemp("fsa-registry-status")
    database = temp_dir / "fsa-registry-status.db"
    patches = pytest.MonkeyPatch()
    preloaded_app_modules = {
        module_name
        for module_name in sys.modules
        if module_name == "app" or module_name.startswith("app.")
    }
    patches.setenv("DATABASE_URL", f"sqlite:///{database}")
    patches.delenv("TNVED_SOURCE_DB", raising=False)
    bootstrap = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services.normative_store import init_db; init_db()",
        ],
        cwd=BACKEND_ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert bootstrap.returncode == 0, bootstrap.stdout + bootstrap.stderr
    assert _protected_fingerprints() == protected_hashes

    from app import db as app_db
    from app.models.tnved import FsaCertificate as IsolatedFsaCertificate

    original_session = app_db.SessionLocal
    original_engine = app_db.engine
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    for module_name, module in tuple(sys.modules.items()):
        if module is None or not (module_name == "app" or module_name.startswith("app.")):
            continue
        if getattr(module, "SessionLocal", None) is original_session:
            patches.setattr(module, "SessionLocal", factory)
        if getattr(module, "engine", None) is original_engine:
            patches.setattr(module, "engine", engine)

    test_module = sys.modules[__name__]
    patches.setattr(test_module, "SessionLocal", factory, raising=False)
    patches.setattr(test_module, "FsaCertificate", IsolatedFsaCertificate, raising=False)

    try:
        yield
    finally:
        patches.undo()
        for module_name, module in tuple(sys.modules.items()):
            if module is None or not (module_name == "app" or module_name.startswith("app.")):
                continue
            if getattr(module, "SessionLocal", None) is factory:
                setattr(module, "SessionLocal", original_session)
            if getattr(module, "engine", None) is engine:
                setattr(module, "engine", original_engine)
        for module_name in tuple(sys.modules):
            if (
                module_name not in preloaded_app_modules
                and (module_name == "app" or module_name.startswith("app."))
            ):
                sys.modules.pop(module_name, None)
        engine.dispose()
        for path in (
            database,
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
        ):
            if path.exists():
                path.unlink()
        assert _protected_fingerprints() == protected_hashes


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Действует", "VALID"),
        ("Зарегистрирован", "VALID"),
        ("active", "VALID"),
        ("valid", "VALID"),
        ("Аннулировано", "NOT_FOUND"),
        ("Не действует", "NOT_FOUND"),
        ("revoked", "NOT_FOUND"),
        ("not active", "NOT_FOUND"),
        ("not registered", "NOT_FOUND"),
        ("Не зарегистрирован", "NOT_FOUND"),
        ("Не зарегистрировано", "NOT_FOUND"),
        ("незарегистрирован", "NOT_FOUND"),
        ("Архив", "UNKNOWN"),
        ("Ожидает проверки", "UNKNOWN"),
        ("unknown-record", "UNKNOWN"),
        ("invalid", "UNKNOWN"),
        ("unregistered", "UNKNOWN"),
        ("", "UNKNOWN"),
    ],
)
def test_registry_status_classification_is_fail_closed(status: str, expected: str) -> None:
    assert _registry_status_to_verify(status, "") == expected


def test_expired_row_is_not_valid_even_with_active_status() -> None:
    assert _registry_status_to_verify("Действует", "2001-01-01") == "NOT_FOUND"


def test_lookup_preserves_unknown_status_as_manual_review_evidence() -> None:
    registry_number = f"TEST-FSA-STATUS-{uuid.uuid4().hex[:12]}"
    with SessionLocal() as db:
        db.add(
            FsaCertificate(
                registry_number=registry_number,
                doc_type="ДС",
                status="Ожидает проверки",
                applicant="TEST HOLDER",
                product_name="Тестовый товар",
            )
        )
        db.commit()

    try:
        found = lookup_fsa_certificate(registry_number, "ДС")
        assert found is not None
        assert found["status"] == "UNKNOWN"
        assert found["number"] == normalize_number(registry_number)
        assert found["holder"] == "TEST HOLDER"
        assert found["raw"]["fsa_status"] == "Ожидает проверки"
    finally:
        with SessionLocal() as db:
            db.query(FsaCertificate).filter(
                FsaCertificate.registry_number == registry_number
            ).delete()
            db.commit()
