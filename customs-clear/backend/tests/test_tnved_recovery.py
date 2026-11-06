from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from app.services.tnved_recovery_store import TnvedRecoveryStore


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_RAW = os.environ.get("TNVED_RECOVERY_SOURCE_DIR")
EXTERNAL = Path(EXTERNAL_RAW) if EXTERNAL_RAW else None
SOURCE_AVAILABLE = EXTERNAL is not None and all(
    (EXTERNAL / relative).is_file()
    for relative in ("data/tnved/catalog.json", "data/tnved/raw/ett-index.html")
)
SOURCE_REASON = "set TNVED_RECOVERY_SOURCE_DIR to the pinned Declarant-full96-ingest directory"
if EXTERNAL is None:
    CATALOG = Path("missing-catalog.json")
    INDEX = Path("missing-ett-index.html")
else:
    CATALOG = EXTERNAL / "data/tnved/catalog.json"
    INDEX = EXTERNAL / "data/tnved/raw/ett-index.html"


def _builder():
    path = ROOT / "scripts/build_tnved_recovery.py"
    spec = importlib.util.spec_from_file_location("build_tnved_recovery", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(not SOURCE_AVAILABLE, reason=SOURCE_REASON)
def test_recovery_build_is_exhaustive_deterministic_and_readable(tmp_path: Path):
    builder = _builder()
    first, second = tmp_path / "first.sqlite", tmp_path / "second.sqlite"
    one = builder.build(CATALOG, INDEX, first, tmp_path / "manifest.json")
    two = builder.build(CATALOG, INDEX, second)
    for database in (first, second):
        assert database.is_file()
        assert not database.with_name(f".{database.name}.building").exists()
        assert all(not Path(f"{database}{suffix}").exists() for suffix in ("-journal", "-wal", "-shm"))
    assert one["logicalSha256"] == two["logicalSha256"]
    assert _sha(first) == _sha(second) == one["sqliteSha256"]
    assert one["integrityCheck"] == "ok"
    assert one["counts"] == {"sources": 99, "editions": 96, "nodes": 18014, "notes": 107, "ten_digit": 13294, "sections": 21, "chapters": 96}

    source = json.loads(CATALOG.read_text())
    with closing(sqlite3.connect(f"file:{first.resolve()}?mode=ro&immutable=1", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        rows = db.execute("SELECT edition_id,code,label,parent_code,source_id,page,path_json,note_refs_json,change_symbol FROM recovery_nodes ORDER BY edition_id,code").fetchall()
        expected = sorted(
            [(n["editionId"], n["code"], n["label"], n.get("parentCode"), n["sourceId"], n["page"], builder._json(n["path"]), builder._json(n.get("noteRefs", [])), n.get("changeSymbol", "")) for n in source["nodes"]]
        )
        assert rows == expected
        assert db.execute("SELECT count(*) FROM recovery_editions WHERE valid_from IS NULL AND valid_to IS NULL AND chain_status='unverified' AND complete=0").fetchone()[0] == 96
        assert db.execute("SELECT count(*) FROM recovery_nodes WHERE code LIKE '0%'").fetchone()[0] == sum(n["code"].startswith("0") for n in source["nodes"])
        assert db.execute("SELECT raw_roman_number,roman_number FROM recovery_sections WHERE roman_number IN ('XII','XIV') ORDER BY roman_number").fetchall() == [("ХII", "XII"), ("ХIV", "XIV")]
        assert db.execute("SELECT count(*) FROM tnved_entries").fetchone()[0] == 18014

    leaf = next(n for n in source["nodes"] if len(n["code"]) == 10 and len(n["path"]) >= 3)
    with TnvedRecoveryStore(first) as store:
        status = store.status()
        assert status["legal_status"] == "unverified" and status["rates_present"] is False
        item = store.lookup(leaf["code"])
        assert item is not None
        assert item["path"] == leaf["path"] and item["note_refs"] == leaf["noteRefs"]
        assert item["valid_from"] is None and item["valid_to"] is None and item["complete"] is False
        assert item["rates"] is None and item["source_sha256"]
        crumb = store.breadcrumb(leaf["code"])
        assert crumb[-1]["code"] == leaf["code"] and crumb[-1]["path"] == leaf["path"]
        assert store.search(leaf["code"], limit=5)[0]["code"] == leaf["code"]
        assert any(r["code"] == leaf["code"] for r in store.search(leaf["label"], limit=200))


@pytest.mark.skipif(not SOURCE_AVAILABLE, reason=SOURCE_REASON)
def test_recovery_rejects_changed_input(tmp_path: Path):
    builder = _builder()
    changed = tmp_path / "catalog.json"
    changed.write_bytes(CATALOG.read_bytes() + b" ")
    try:
        builder.build(changed, INDEX, tmp_path / "bad.sqlite")
    except ValueError as exc:
        assert "approved input" in str(exc)
    else:
        raise AssertionError("changed source was accepted")
