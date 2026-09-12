"""Legacy maintenance must not mutate active rates, rules, NTM or source state."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS = (
    ("populate_duty_rules", "main"),
    ("cleanup_legacy_and_backfill_excise", "run"),
    ("load_code_0301_profile", "main"),
    ("seed_geopolitics", "main"),
)
BACKEND = Path(__file__).resolve().parents[1]


def forbidden(*args, **kwargs):
    raise AssertionError("Legacy maintenance reached a database, download or cache write")


@pytest.mark.parametrize("script, entry", SCRIPTS)
def test_public_maintenance_blocks_before_any_side_effect(script, entry):
    module = importlib.import_module("scripts." + script)
    with (
        patch("app.db.SessionLocal", side_effect=forbidden),
        patch("app.services.normative_store.init_db", side_effect=forbidden),
        patch("httpx.Client", side_effect=forbidden),
        patch("httpx.get", side_effect=forbidden),
    ):
        result = getattr(module, entry)()
    assert result["status"] == "manual_review_required"
    assert result["imported"] == 0
    assert result["blockers"]
    for field in ("db_mutated", "active_rates_written", "source_evidence_verified",
                  "legal_review_verified", "retention_verified"):
        assert result[field] is False


@pytest.mark.parametrize("module_name", [
    *("scripts." + script for script, _ in SCRIPTS),
    "app.services.duty_rules_backfill",
])
def test_import_does_not_even_load_database_or_network_modules(tmp_path, module_name):
    db = tmp_path / "not-created.db"
    program = """
import builtins
import importlib
import sys

original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == "app.db" or name.startswith(("sqlalchemy", "httpx")):
        raise AssertionError("Import entered database/network dependencies: " + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
importlib.import_module(sys.argv[1])
assert "app.db" not in sys.modules
print("import_only_no_database")
"""
    result = subprocess.run(
        [sys.executable, "-c", program, module_name], cwd=tmp_path,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db}", "PYTHONPATH": str(BACKEND)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "import_only_no_database"
    assert not db.exists()


@pytest.mark.parametrize("script, _", SCRIPTS)
@pytest.mark.parametrize("arguments", [[], ["--dry-run"], ["--apply", "--approved"]])
def test_maintenance_cli_preserves_existing_database_and_cache(tmp_path, script, _, arguments):
    db = tmp_path / "existing-isolated.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE sentinel (value TEXT)")
        conn.execute("INSERT INTO sentinel VALUES ('unchanged')")
    marker = tmp_path / "cache.txt"
    marker.write_text("unchanged")
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    result = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / (script + ".py")), *arguments],
        cwd=tmp_path,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db}",
             "TNVED_PREVIEW_CACHE_REVISION_FILE": str(marker)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "manual_review_required"
    assert payload["db_mutated"] is False
    assert payload["active_rates_written"] is False
    assert payload["legal_review_verified"] is False
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert marker.read_text() == "unchanged"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["cache.txt", "existing-isolated.db"]


@pytest.mark.parametrize("only_missing", [True, False])
def test_public_backfill_never_touches_supplied_database(only_missing):
    from app.services.duty_rules_backfill import backfill_duty_rules_from_hs_rates

    class ForbiddenDatabase:
        def __getattribute__(self, name):
            raise AssertionError("Public legacy backfill attempted DB access: " + name)

    result = backfill_duty_rules_from_hs_rates(ForbiddenDatabase(), only_missing=only_missing)
    assert result["status"] == "manual_review_required"
    assert result["created"] == result["updated"] == result["skipped"] == 0
    assert result["db_mutated"] is False
    assert result["legal_review_verified"] is False


def test_private_fixture_backfill_rejects_file_database_before_connecting(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.duty_rules_backfill import _backfill_fixture_duty_rules

    filename = tmp_path / "never-created.db"
    engine = create_engine(f"sqlite:///{filename}")
    try:
        with sessionmaker(bind=engine)() as db:
            with pytest.raises(ValueError, match="fixture_backfill_requires_explicit_in_memory_database"):
                _backfill_fixture_duty_rules(db)
        assert not filename.exists()
    finally:
        engine.dispose()
